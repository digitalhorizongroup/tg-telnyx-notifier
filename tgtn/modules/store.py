"""Очередь и история отказов сообщений в SQLite.

Успешно отправленное сообщение строку не переживает: ``mark_sent`` удаляет её
тем же ходом, что засчитывает отправку, — очередь никогда не хранит больше,
чем реально ждёт отправки. Отброшенное неустранимо остаётся в таблице до
``purge``: без него причина отказа терялась бы сразу после журнала.

Дедупликация — на уникальности ``event_id``. Telnyx повторяет доставку webhook
до трёх раз, пока не получит успешный ответ, поэтому одно и то же сообщение
приходит по нескольку раз; без уникального ключа канал получил бы дубли.

Счётчики принятого и отправленного за сутки живут отдельной таблицей
(``daily_counters``): строка, по которой считался счётчик, к моменту отчёта
может быть уже удалена, а факт события — нет.

Сутки везде считаются по UTC — той же зоне, в которой пишется журнал.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Self

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS message (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT    NOT NULL UNIQUE,
    sender      TEXT    NOT NULL,
    recipient   TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    media       TEXT    NOT NULL,
    received_at TEXT    NOT NULL,
    failed_at   TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT
);
CREATE INDEX IF NOT EXISTS message_queue ON message(failed_at, id);
CREATE INDEX IF NOT EXISTS message_failed_received ON message(failed_at, received_at);

-- Один ряд на сутки UTC. `received`/`sent` копят события, переживших свою
-- строку в `message`; `failed_today` в `counters()` считается прямо по
-- `message`, потому что отброшенные строки там и остаются.
CREATE TABLE IF NOT EXISTS daily_counters (
    day      TEXT PRIMARY KEY,
    received INTEGER NOT NULL DEFAULT 0,
    sent     INTEGER NOT NULL DEFAULT 0
);
"""

# Голова очереди: самое раннее принятое, ещё не отброшенное. Отправленное этой
# строки уже не застаёт — `mark_sent` удаляет её раньше, чем сюда доходят.
_HEAD = """
SELECT id, event_id, sender, recipient, body, media, received_at, attempts
FROM message
WHERE failed_at IS NULL
ORDER BY id
LIMIT 1
"""

_BUMP_RECEIVED = """
INSERT INTO daily_counters(day, received, sent) VALUES (?, 1, 0)
ON CONFLICT(day) DO UPDATE SET received = received + 1
"""

_BUMP_SENT = """
INSERT INTO daily_counters(day, received, sent) VALUES (?, 0, 1)
ON CONFLICT(day) DO UPDATE SET sent = sent + 1
"""


def _today() -> str:
    """Сегодняшняя дата по UTC — ключ строки в ``daily_counters``."""
    return datetime.now(UTC).date().isoformat()


@dataclass(frozen=True, slots=True)
class Incoming:
    """Принятое сообщение — то, что кладут в очередь.

    Отдельный объект вместо россыпи аргументов: поля путешествуют вместе от
    разбора webhook до записи, и порядок их перечисления не может разъехаться.

    Attributes:
        event_id: Идентификатор сообщения у Telnyx; ключ дедупликации.
        sender: Номер отправителя.
        recipient: Номер профиля, на который пришло сообщение.
        body: Текст сообщения; у MMS без подписи пустой.
        media: Ссылки на вложения, по одной в строке.
        received_at: Когда Telnyx принял сообщение. ``None`` — момент записи.
    """

    event_id: str
    sender: str
    recipient: str
    body: str
    media: str = ""
    received_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Pending:
    """Сообщение, ждущее отправки.

    Attributes:
        row_id: Ключ строки; им же адресуются отметки об исходе отправки.
        event_id: Идентификатор сообщения у Telnyx, по которому шла дедупликация.
        sender: Номер отправителя.
        recipient: Номер профиля, на который пришло сообщение.
        body: Текст сообщения; у MMS без подписи пустой.
        media: Ссылки на вложения, по одной в строке.
        received_at: Когда сообщение принято от Telnyx.
        attempts: Сколько отправок уже не удалось. Ноль у неотправлявшегося.
    """

    row_id: int
    event_id: str
    sender: str
    recipient: str
    body: str
    media: str
    received_at: datetime
    attempts: int

    def render(self) -> str:
        """Собрать текст поста для канала.

        Разметка не используется: текст пришёл снаружи, и любой служебный
        символ в нём Telegram разбирал бы как тег.
        """
        header = f"{self.sender} → {self.recipient}"
        parts = [header, self.body] if self.body else [header]
        if self.media:
            parts.append(self.media)
        return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class Counters:
    """Счётчики за сутки и длина очереди.

    Attributes:
        received_today: Принято от Telnyx с начала суток UTC.
        sent_today: Ушло в канал с начала суток UTC.
        failed_today: Отброшено по неустранимой причине с начала суток UTC.
        pending: Длина очереди сейчас, включая принятое в прошлые сутки.
    """

    received_today: int
    sent_today: int
    failed_today: int
    pending: int


class Store:
    """Соединение с базой очереди.

    Одно соединение на процесс: aiosqlite сериализует обращения на своём потоке,
    и второе соединение к тому же файлу дало бы конкуренцию за запись без
    выигрыша — писатель здесь всё равно один.

    Работает как асинхронный контекстный менеджер; вне него методы требуют
    открытого соединения.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: aiosqlite.Connection | None = None
        # Отметки об исходе отправки читают и пишут одну строку подряд; лок
        # держит эту пару неделимой относительно приёма новых сообщений.
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    @property
    def _db(self) -> aiosqlite.Connection:
        """Открытое соединение.

        Raises:
            RuntimeError: Если хранилище ещё не открыто.
        """
        if self._connection is None:
            message = "хранилище не открыто: нужен `async with Store(...)` или `await store.open()`"
            raise RuntimeError(message)
        return self._connection

    async def open(self) -> None:
        """Открыть базу, настроить соединение и создать схему, если её нет.

        Настройки PRAGMA рассчитаны на нагрузку этой базы — один писатель,
        частые короткие транзакции, файл на смонтированном томе — а не общий
        рецепт. `auto_vacuum` берётся только у файла, созданного заново: у уже
        существующей базы значение меняется лишь после `VACUUM`.
        """
        self._path.parent.mkdir(exist_ok=True, parents=True)
        self._connection = await aiosqlite.connect(self._path)
        # WAL: читающий счётчики не ждёт пишущего приём, и наоборот.
        await self._connection.execute("PRAGMA journal_mode=WAL")
        # NORMAL безопасен ровно вместе с WAL: коммит переживает падение
        # процесса, а не только (более редкий) сбой самой ОС посреди
        # контрольной точки — FULL здесь платит лишним fsync без такой надобности.
        await self._connection.execute("PRAGMA synchronous=NORMAL")
        # Один писатель на процесс, но короткое ожидание вместо "database is
        # locked" нужно и ему — контрольная точка WAL занимает файл на
        # мгновение, и без таймаута случайно попавший в эту паузу запрос падает.
        await self._connection.execute("PRAGMA busy_timeout=5000")
        # Временные B-деревья под ORDER BY и COUNT — в памяти: строк в очереди
        # мало, а диск в контейнере — смонтированный том, не tmpfs.
        await self._connection.execute("PRAGMA temp_store=MEMORY")
        # FULL: `mark_sent` удаляет строку сразу после отправки, и без
        # авто-вакуума файл базы растёт вслед за общим числом сообщений за всё
        # время, а не длиной очереди, которая обычно близка к нулю.
        await self._connection.execute("PRAGMA auto_vacuum=FULL")
        await self._connection.executescript(_SCHEMA)
        await self._connection.commit()

    async def close(self) -> None:
        """Закрыть соединение; повторный вызов ничего не делает."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def enqueue(self, message: Incoming) -> bool:
        """Поставить сообщение в очередь.

        Returns:
            ``True``, если сообщение принято; ``False``, если такой ``event_id``
            уже лежит в базе — то есть Telnyx повторил доставку webhook.
        """
        moment = (message.received_at or datetime.now(UTC)).astimezone(UTC).isoformat()
        async with self._lock:
            cursor = await self._db.execute(
                """
                INSERT OR IGNORE INTO message(event_id, sender, recipient, body, media, received_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message.event_id, message.sender, message.recipient, message.body, message.media, moment),
            )
            accepted = cursor.rowcount == 1
            if accepted:
                await self._db.execute(_BUMP_RECEIVED, (_today(),))
            await self._db.commit()
            return accepted

    async def head(self) -> Pending | None:
        """Взять голову очереди, не снимая её оттуда.

        Строка остаётся на месте до явной отметки об исходе: процесс, упавший
        между чтением и отправкой, не теряет сообщение.
        """
        async with self._db.execute(_HEAD) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return Pending(
            row_id=row[0],
            event_id=row[1],
            sender=row[2],
            recipient=row[3],
            body=row[4],
            media=row[5],
            received_at=datetime.fromisoformat(row[6]),
            attempts=row[7],
        )

    async def has_pending(self) -> bool:
        """Есть ли в очереди хоть одно сообщение."""
        async with self._db.execute("SELECT 1 FROM message WHERE failed_at IS NULL LIMIT 1") as cursor:
            return await cursor.fetchone() is not None

    async def mark_sent(self, row_id: int) -> None:
        """Засчитать сообщение ушедшим и удалить его строку.

        Строка не переживает свою отправку: хранить её дальше означало бы
        держать в очереди то, что в неё уже не входит, — ради истории, которую
        никто не читает и не запрашивал.
        """
        async with self._lock:
            await self._db.execute("DELETE FROM message WHERE id = ?", (row_id,))
            await self._db.execute(_BUMP_SENT, (_today(),))
            await self._db.commit()

    async def mark_failed(self, row_id: int, error: str) -> None:
        """Отбросить сообщение: причина неустранима, повтор ничего не изменит.

        Строка выбывает из очереди, но остаётся в базе — иначе отказ виден
        только в журнале и не попадает в сводку активности.
        """
        async with self._lock:
            await self._db.execute(
                "UPDATE message SET failed_at = ?, attempts = attempts + 1, last_error = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), error, row_id),
            )
            await self._db.commit()

    async def record_attempt(self, row_id: int, error: str) -> None:
        """Запомнить неудачную попытку, оставив сообщение в очереди.

        Счётчик попыток ничего не отсекает: пока причина устранима (Telegram
        недоступен, сработал лимит), сообщение обязано дождаться отправки, а не
        быть отброшенным по числу заходов.
        """
        async with self._lock:
            await self._db.execute(
                "UPDATE message SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                (error, row_id),
            )
            await self._db.commit()

    async def counters(self) -> Counters:
        """Собрать счётчики за сутки UTC и текущую длину очереди.

        ``received``/``sent`` — из ``daily_counters``: строка, по которой шёл
        подсчёт, к моменту отчёта могла уже уйти из ``message``.
        ``failed_today`` и ``pending`` считаются прямо по ``message`` — эти
        строки из неё не удаляются.
        """
        since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        async with self._db.execute(
            """
            SELECT
                (SELECT received FROM daily_counters WHERE day = ?),
                (SELECT sent     FROM daily_counters WHERE day = ?),
                (SELECT COUNT(*) FROM message WHERE failed_at >= ?),
                (SELECT COUNT(*) FROM message WHERE failed_at IS NULL)
            """,
            (_today(), _today(), since),
        ) as cursor:
            row = await cursor.fetchone()
        counts = row or (0, 0, 0, 0)
        return Counters(
            received_today=counts[0] or 0,
            sent_today=counts[1] or 0,
            failed_today=counts[2],
            pending=counts[3],
        )

    async def purge(self, history_days: int) -> int:
        """Удалить старые отброшенные сообщения.

        Единственная история, которая остаётся в ``message``, — это отказы:
        отправленное чистит сама ``mark_sent``. Очередь не трогается ни при
        каком сроке. Неположительный срок отключает чистку.

        Returns:
            Сколько строк удалено.
        """
        if history_days <= 0:
            return 0
        edge = (datetime.now(UTC) - timedelta(days=history_days)).isoformat()
        async with self._lock:
            cursor = await self._db.execute(
                "DELETE FROM message WHERE failed_at IS NOT NULL AND received_at < ?",
                (edge,),
            )
            await self._db.commit()
            return cursor.rowcount


__all__ = ["Counters", "Incoming", "Pending", "Store"]
