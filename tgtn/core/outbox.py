"""Отправка из очереди: одно сообщение за проход, пауза растёт под наплывом.

Порядок прохода: взять голову очереди, отправить, выждать паузу, посмотреть на
очередь. Осталось что-то — пауза удваивается, очередь пуста — возвращается к
базовой. Потолок паузы задан настройками, поэтому шкала по умолчанию выходит
5 → 10 → 20 → 30 → 30 …

Пауза стоит **после** отправки, а не перед ней: первое сообщение спокойной
очереди уходит сразу, а темп ограничивается только при непрерывном потоке.
Смысл её — не дать Telegram выдать лимит на канал, поэтому она отмеряется от
факта отправки.

Простая очередь ждёт на событии, а не крутит опрос: пустая очередь не обращается
к базе вовсе, а первое же принятое сообщение будит воркер немедленно.
"""

import asyncio
import contextlib
import logging

from tgtn.core.store import Pending, Store
from tgtn.core.telegram import RejectedError, Telegram, UnavailableError

LOG = logging.getLogger(__name__)


class Outbox:
    """Воркер очереди отправки.

    Живёт одной фоновой задачей рядом с HTTP-сервером, на том же цикле событий.
    """

    def __init__(self, store: Store, telegram: Telegram, base_delay: float, max_delay: float) -> None:
        self._store = store
        self._telegram = telegram
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._delay = base_delay
        self._arrivals = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def delay(self) -> float:
        """Текущая пауза между отправками; базовая, пока очередь спокойна."""
        return self._delay

    def notify(self) -> None:
        """Сообщить воркеру, что в очередь что-то положили.

        Зовётся приёмом webhook после успешной записи. Спящий воркер
        просыпается сразу, работающий отметку просто игнорирует.
        """
        self._arrivals.set()

    async def start(self) -> None:
        """Поднять фоновую задачу; повторный вызов ничего не делает."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="outbox")

    async def stop(self) -> None:
        """Остановить задачу и дождаться её завершения."""
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        """Крутить проходы, пока задачу не снимут."""
        while True:
            try:
                await self._step()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Проход сорвался не на отправке — значит на базе. Цикл обязан
                # пережить это: иначе задача тихо умирает, очередь замирает, а
                # приём продолжает копить сообщения без единого признака беды.
                # Пауза перед повтором — базовая: та же мера, с которой воркер
                # работает и в остальное время.
                LOG.exception("проход очереди сорвался; повтор через %.0f с", self._base_delay)
                await asyncio.sleep(self._base_delay)

    def _next_delay(self, *, has_pending: bool) -> float:
        """Пауза для следующего прохода.

        Очередь не опустела за время паузы — наплыв продолжается, и пауза
        удваивается до потолка. Опустела — таймер истёк вхолостую, и пауза
        возвращается к базовой. При значениях по умолчанию шкала выходит
        5 → 10 → 20 → 30 → 30 …
        """
        if not has_pending:
            return self._base_delay
        return min(self._delay * 2, self._max_delay)

    async def _step(self) -> None:
        """Сделать один проход: отправку и паузу либо ожидание сообщений."""
        # `clear` до проверки, а не после: сообщение, принятое между проверкой и
        # ожиданием, иначе снимало бы отметку впустую и воркер спал бы до
        # следующего — то есть до сообщения, которое некому прислать.
        self._arrivals.clear()
        if not await self._store.has_pending():
            self._delay = self._base_delay
            await self._arrivals.wait()
            return

        message = await self._store.head()
        if message is not None:
            await self._deliver(message)

        await asyncio.sleep(self._delay)
        self._delay = self._next_delay(has_pending=await self._store.has_pending())

    async def _deliver(self, message: Pending) -> None:
        """Отправить одно сообщение и записать исход.

        Устранимый отказ оставляет сообщение головой очереди: следующий проход
        возьмёт его же. Неустранимый — отбрасывает, иначе одно битое сообщение
        закрыло бы канал всем остальным.
        """
        try:
            await self._telegram.send(message.render())
        except UnavailableError as exc:
            await self._store.record_attempt(message.row_id, str(exc))
            LOG.warning("telegram недоступен, сообщение %s остаётся в очереди: %s", message.event_id, exc)
            if exc.retry_after is not None:
                await asyncio.sleep(exc.retry_after)
        except RejectedError as exc:
            await self._store.mark_failed(message.row_id, str(exc))
            LOG.exception("сообщение %s отброшено", message.event_id)
        else:
            await self._store.mark_sent(message.row_id)
            LOG.info("сообщение %s ушло в канал", message.event_id)


__all__ = ["Outbox"]
