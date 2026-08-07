import pytest

from polymarket import PRODUCTION, Environment


def test_environment_only_exposes_its_name() -> None:
    assert PRODUCTION.name == "production"
    assert {name for name in dir(PRODUCTION) if not name.startswith("_")} == {"name"}
    assert repr(PRODUCTION) == "Environment(name='production')"


def test_environment_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError, match="provided by the SDK"):
        Environment()
