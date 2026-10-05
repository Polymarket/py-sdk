"""Small public production response samples captured on 2026-09-08."""

import json
from pathlib import Path
from typing import Any, cast


def sample(name: str) -> Any:
    path = Path(__file__).parents[1] / "fixtures" / "data_v2" / f"{name}.json"
    return json.loads(path.read_text())


def position_payload(**overrides: object) -> dict[str, Any]:
    return {**cast(dict[str, Any], sample("positions")[0]), **overrides}
