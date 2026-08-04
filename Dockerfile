# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

# `UV_COMPILE_BYTECODE` — .pyc собираются при установке, а не при первом
# импорте: старт контейнера не тратит на это время. `UV_LINK_MODE=copy` — кэш
# uv лежит на отдельном mount'е, и жёсткие ссылки через границу файловых
# систем не создаются.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Слой зависимостей: кэшируется, пока не изменятся манифест и lock. Исходники
# сюда не входят — `--no-install-project` ставит только зависимости, поэтому
# правка кода не пересобирает этот слой.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Слой кода. `--no-editable`: пакет копируется в venv целиком, и рантайм-образу
# не нужно дерево исходников. `--frozen` запрещает молчаливое обновление
# lock-файла — состав образа совпадает с зафиксированным в репозитории.
COPY tgtn ./tgtn
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Рантайм-образ: собранный venv без uv, без исходников и без dev-группы.
FROM python:3.13-slim-bookworm

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv

# venv впереди PATH — `uvicorn` и `python` берутся из него, активация не нужна.
# `PYTHONUNBUFFERED` — иначе stdout буферизуется поблочно и логи всплывают в
# `docker logs` пачками, с задержкой.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Процесс не root. Каталог данных заводится и отдаётся ему заранее: том
# монтируется сюда, и без владельца очередь в нём не создастся.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data \
    && chown app:app /app/data
USER app

# База очереди переживает пересоздание контейнера только на томе: без него
# принятые, но не отправленные сообщения уходят вместе со слоем.
VOLUME ["/app/data"]
ENV TGTN_DATA_DIR=/app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()" || exit 1

# Консольная команда из манифеста, а не `uvicorn` напрямую: сервер поднимает
# `main()`, и там же выбирается цикл uvloop и ставится логирование. Адрес и порт
# приходят переменными `TGTN_HOST`/`TGTN_PORT`, поэтому CMD пуст.
ENTRYPOINT ["tgtn"]
