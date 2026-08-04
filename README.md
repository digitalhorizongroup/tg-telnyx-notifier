# Telnyx SMS/MMS to Telegram Notifier

[Telegram](https://t.me/digitalhorizongroup) · [Discord](https://discord.com/invite/fjqzSYCETC)

Self-hosted Python-сервис для пересылки входящих Telnyx SMS и MMS в Telegram-канал.
FastAPI принимает Telnyx webhooks, SQLite сохраняет надёжную очередь, а aiogram
публикует сообщения и отвечает на `/activity`. Проект подходит для самостоятельного
развёртывания через Docker или `uv`.

Ключевые возможности: дедупликация по `event_id`, устойчивая очередь SQLite, адаптивная
пауза между отправками, Telegram webhook с секретом и healthcheck с версией сборки.

## Как это работает

```
Telnyx ──webhook──▶ /notification, /failure ──▶ очередь (SQLite) ──▶ Telegram-канал
                                                     ▲
Telegram ──apdejt──▶ /telegram/updates ─────────────┘  (команда /activity)
```

- **Приём.** Telnyx шлёт webhook на `/notification` (основной адрес профиля) и
  `/failure` (запасной, куда Telnyx повторяет доставку, если основной не
  ответил). Сообщение сразу пишется в очередь, ответ уходит немедленно —
  Telnyx ждёт его считаные секунды.
- **Очередь.** Фоновый воркер (`Outbox`) забирает голову очереди и отправляет
  в канал. Пауза между отправками растёт под непрерывным наплывом (по
  умолчанию 5 → 10 → 20 → 30 с) и возвращается к базовой, как только очередь
  опустела, — так канал не упирается в лимит Telegram.
- **Хранилище.** Один файл SQLite (WAL). Успешно отправленное сообщение
  удаляется из базы тем же ходом, что засчитывает отправку: очередь никогда не
  хранит больше, чем реально ждёт отправки. Отброшенное по неустранимой
  причине (бота выгнали из канала, канал удалён) остаётся в базе до истечения
  `TGTN_HISTORY_DAYS` — это единственная история, которую хранит сервис.
- **Команда бота.** `/activity` в самом канале или от адреса из
  `TGTN_ADMIN_IDS` отвечает сводкой: сколько принято, отправлено, отброшено за
  сутки UTC, длина очереди и доступность Telegram.
- **Дедупликация.** Telnyx повторяет доставку webhook до трёх раз, пока не
  получит успешный ответ. Ключ дедупликации — `event_id`; повтор отвечает
  `duplicate` и не отправляется вторично.

## Маршруты

| Маршрут | Метод | Источник | Назначение |
| --- | --- | --- | --- |
| `/health` | GET | — | Признак живости процесса и версия сборки. Не проверяет Telegram — по этому адресу бьёт `HEALTHCHECK` образа. |
| `/notification` | POST | Telnyx | Основной адрес профиля для входящих сообщений. |
| `/failure` | POST | Telnyx | Запасной адрес, куда Telnyx повторяет доставку. |
| `/telegram/updates` | POST | Telegram | Апдейты бота; требует заголовок `X-Telegram-Bot-Api-Secret-Token`. |

## Требования

- Python 3.13 или новее и `uv` либо Docker.
- Telnyx Messaging Profile с номером, принимающим SMS/MMS.
- Telegram-бот с правом публикации в целевом канале.
- HTTPS-адрес, доступный Telnyx и Telegram, для работы webhooks.

## Установка и быстрый запуск (Installation)

### uv

```bash
cp .env.example .env
uv sync
uv run tgtn
```

Перед `uv run tgtn` заполните в `.env` как минимум `TGTN_BOT_TOKEN`,
`TGTN_CHAT_ID` и `TGTN_TELEGRAM_WEBHOOK_SECRET`.

### Docker

```bash
docker build -t tg-telnyx-notifier .
docker run --env-file .env -p 8000:8000 -v tgtn-data:/app/data tg-telnyx-notifier
```

Том обязателен: без него очередь и история отказов пропадают вместе с
контейнером. `TGTN_PUBLIC_URL` можно не задавать локально — тогда webhook
Telegram не регистрируется, `/activity` недоступна, а пересылка сообщений
работает как обычно.

## Пример результата (Examples)

После запуска healthcheck показывает статус и точную версию сборки:

```bash
curl http://localhost:8000/health
```

```json
{"status":"ok","version":"0.4.1"}
```

Входящее `message.received` с направлением `inbound` получает ответ `202 Accepted` со
статусом `queued`, `duplicate` или `ignored`. Ответ `queued` означает, что сообщение надёжно
записано в SQLite и будет отправлено фоновым воркером.

## Настройка

Все переменные — в [`.env.example`](.env.example), каждая с пояснением. Без
значения по умолчанию обязательны только `TGTN_BOT_TOKEN`, `TGTN_CHAT_ID` и
`TGTN_TELEGRAM_WEBHOOK_SECRET`; отсутствие любой из них роняет процесс на
старте, а не откладывает отказ до первого сообщения.

## Структура пакета

- `tgtn/core` — настройки (`TGTN_*`), схемы запросов и ответов, доступ
  обработчиков к состоянию приложения (`core/deps.py`).
- `tgtn/modules` — бизнес-логика: очередь и хранилище (`store.py`), воркер
  отправки (`outbox.py`), канал доставки в Telegram (`telegram.py`).
- `tgtn/handlers` — разбор входящих событий по источнику: `notification.py`
  (Telnyx), `telegram.py` (апдейты бота), `commands.py` (`/activity`),
  `health.py`.

## Разработка

```bash
uv run ruff check .          # линт
uv run ruff format .         # форматирование
uv run mypy                  # типы, --strict
uv run pytest --cov=tgtn --cov-report=term-missing --cov-fail-under=80
```

Соглашения по коду, докстрингам и версионированию — в [`AGENTS.md`](AGENTS.md);
адреса документации сторонних библиотек — в [`.claude/CLAUDE.md`](.claude/CLAUDE.md).

## Поддержка и участие

Ошибку или предложение можно оформить через [GitHub Issues](https://github.com/digitalhorizongroup/tg-telnyx-notifier/issues).
Порядок локальной проверки и pull request описан в [`CONTRIBUTING.md`](CONTRIBUTING.md), а уязвимости
следует сообщать по инструкции из [`SECURITY.md`](SECURITY.md).
Новости и обсуждения доступны в [Telegram](https://t.me/digitalhorizongroup) и
[Discord](https://discord.com/invite/fjqzSYCETC) Digital Horizon Group.

## Лицензия

Проект распространяется по [MIT License](LICENSE).
