import logging
from collections.abc import Iterator

import pytest

from tgtn.core.config import SERVICE


@pytest.fixture
def restore_logging() -> Iterator[None]:
    """Вернуть дерево логгеров в исходное состояние после теста.

    setup_logging правит глобальный root-логгер, и без отката следующий тест
    получил бы чужие пороги и чужой обработчик.
    """
    root = logging.getLogger()
    handlers, root_level = root.handlers[:], root.level
    service_level = logging.getLogger(SERVICE).level

    yield

    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(root_level)
    logging.getLogger(SERVICE).setLevel(service_level)
