# pyright: reportPrivateUsage=false

from typing import NoReturn

import pytest

from polymarket import PRODUCTION, Environment, PublicClient
from polymarket._internal import context as context_module
from polymarket._internal.environment import PRODUCTION_CONFIG


def test_environment_only_exposes_its_name() -> None:
    assert PRODUCTION.name == "production"
    assert {name for name in dir(PRODUCTION) if not name.startswith("_")} == {"name"}
    assert repr(PRODUCTION) == "Environment(name='production')"


def test_environment_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError, match="provided by the SDK"):
        Environment()


def test_client_context_reuses_ingested_environment_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_lookup(_environment: Environment) -> NoReturn:
        raise AssertionError("context should reuse the config resolved by the client")

    monkeypatch.setattr(context_module, "get_environment_config", unexpected_lookup)

    with PublicClient() as client:
        assert client._ctx.environment_config is PRODUCTION_CONFIG
