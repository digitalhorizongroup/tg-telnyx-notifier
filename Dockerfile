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
COPY tg_telnyx_notifier ./tg_telnyx_notifier
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

# Процесс не root: запись в образ ему не нужна, наружу торчит только порт.
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()" || exit 1

# Адрес и порт — в CMD, а не в ENTRYPOINT: так `docker run … --port 9000`
# переопределяет их, не повторяя имя приложения. `0.0.0.0` обязателен —
# на `127.0.0.1` порт виден только изнутри контейнера.
ENTRYPOINT ["uvicorn", "tg_telnyx_notifier.app:app"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
