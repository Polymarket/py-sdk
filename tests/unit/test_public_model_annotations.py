import inspect
from types import ModuleType
from typing import cast, get_args, get_type_hints

from pydantic import BaseModel
from pydantic.functional_serializers import PlainSerializer
from pydantic.functional_validators import BeforeValidator

import polymarket
import polymarket.models
import polymarket.models.clob
import polymarket.models.perps
import polymarket.streams

_PUBLIC_MODULES = (
    polymarket,
    polymarket.models,
    polymarket.models.clob,
    polymarket.models.perps,
    polymarket.streams,
)

_REMOVED_ALIASES = (
    "DecimalFromE6String",
    "DecimalFromString",
    "EpochMsOrIsoTimestamp",
    "EpochMsTimestamp",
    "EpochOrIsoTimestamp",
    "EpochSecondsOrMsTimestamp",
    "EpochSecondsTimestamp",
    "ExpirationTimestamp",
    "OptionalPerpsTimestamp",
    "OptionalTxHash",
    "PerpsTimestamp",
    "RequiredEpochOrIsoTimestamp",
    "TradeStatusField",
    "_DecimalFromNumberOrString",
    "_DecimalFromString",
    "_OptionalDecimalFromNumberOrString",
)


def _public_models(module: ModuleType) -> set[type[BaseModel]]:
    models: set[type[BaseModel]] = set()
    exports = cast(tuple[str, ...], module.__dict__["__all__"])
    for name in exports:
        value: object = getattr(module, name)
        if isinstance(value, type) and issubclass(value, BaseModel):
            models.add(value)
    return models


def _all_public_models() -> set[type[BaseModel]]:
    models: set[type[BaseModel]] = set()
    for module in _PUBLIC_MODULES:
        models.update(_public_models(module))
    return models


def _contains_validation_metadata(annotation: object) -> bool:
    if isinstance(annotation, BeforeValidator | PlainSerializer):
        return True
    return any(_contains_validation_metadata(arg) for arg in get_args(annotation))


def test_public_model_fields_expose_canonical_annotations() -> None:
    for model in _all_public_models():
        hints = get_type_hints(model, include_extras=True)
        signature = inspect.signature(model)
        for field in model.model_fields:
            annotation = hints[field]
            assert not _contains_validation_metadata(annotation), f"{model.__name__}.{field}"

        for parameter in signature.parameters.values():
            assert not _contains_validation_metadata(parameter.annotation), (
                f"{model.__name__}({parameter.name}=...)"
            )


def test_public_model_source_annotations_do_not_use_removed_aliases() -> None:
    for model in _all_public_models():
        source_annotations = repr(model.__dict__.get("__annotations__", {}))
        for alias in _REMOVED_ALIASES:
            assert alias not in source_annotations, f"{model.__name__} still uses {alias}"
