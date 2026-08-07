from polymarket.environments import (
    PRODUCTION,
    Environment,
    _create_environment,  # pyright: ignore[reportPrivateUsage]
    _EnvironmentConfig,  # pyright: ignore[reportPrivateUsage]
    _WalletDerivation,  # pyright: ignore[reportPrivateUsage]
)

EnvironmentConfig = _EnvironmentConfig
WalletDerivationConfig = _WalletDerivation


def get_environment_config(environment: Environment) -> _EnvironmentConfig:
    return environment._config  # pyright: ignore[reportPrivateUsage]


PRODUCTION_CONFIG = get_environment_config(PRODUCTION)


def create_environment(*, name: str, config: EnvironmentConfig) -> Environment:
    return _create_environment(name=name, config=config)


def with_environment_config(environment: Environment, *, config: EnvironmentConfig) -> Environment:
    return create_environment(name=environment.name, config=config)


__all__ = [
    "EnvironmentConfig",
    "PRODUCTION_CONFIG",
    "WalletDerivationConfig",
    "create_environment",
    "get_environment_config",
    "with_environment_config",
]
