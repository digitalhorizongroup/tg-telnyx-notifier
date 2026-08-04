# Участие в разработке

Перед началом создайте issue с описанием задачи, ожидаемого поведения и способа проверки.
Уязвимости сообщайте по инструкции из [`SECURITY.md`](SECURITY.md), а не через публичный issue.

## Проверка

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov=tgtn --cov-report=term-missing --cov-fail-under=80
```

## Pull request

- Один pull request решает одну задачу.
- Изменение поведения сопровождается тестами.
- Правила комментариев, докстрингов и версии описаны в [`AGENTS.md`](AGENTS.md).
- В описании указываются риски и выполненные проверки.
