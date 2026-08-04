import re
from importlib import metadata

import tg_telnyx_notifier
from tg_telnyx_notifier import _version

DISTRIBUTION = "tg-telnyx-notifier"

# Публичная версия по PEP 440: epoch, release и необязательные pre/post/dev/local.
PEP_440 = re.compile(
    r"^(\d+!)?\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?(\+[a-z0-9]+([.-][a-z0-9]+)*)?$",
    re.IGNORECASE,
)


def test_distribution_metadata_is_built_from_the_code_variable() -> None:
    # Arrange
    declared = _version.__version__

    # Act
    installed = metadata.version(DISTRIBUTION)

    # Assert
    assert installed == declared


def test_package_reexports_version_from_the_version_module() -> None:
    assert tg_telnyx_notifier.__version__ is _version.__version__


def test_version_literal_is_valid_pep_440() -> None:
    assert PEP_440.match(_version.__version__)
