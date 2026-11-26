import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = SCHEMA_DIR / "examples"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def example_paths(name: str) -> list[Path]:
    return sorted((EXAMPLES_DIR / name).glob("*.json"))


@pytest.fixture(scope="session")
def meta_schema() -> dict[str, Any]:
    return load_json(SCHEMA_DIR / "meta.schema.json")


@pytest.fixture(scope="session")
def meta_validator(meta_schema: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(meta_schema)


@pytest.fixture(scope="session")
def correction_schema() -> dict[str, Any]:
    return load_json(SCHEMA_DIR / "correction.schema.json")


@pytest.fixture(scope="session")
def correction_validator(
    correction_schema: dict[str, Any],
) -> Draft202012Validator:
    return Draft202012Validator(correction_schema)


@pytest.fixture(scope="session")
def aoa_schema() -> dict[str, Any]:
    return load_json(SCHEMA_DIR / "aoa.schema.json")


@pytest.fixture(scope="session")
def aoa_validator(aoa_schema: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(aoa_schema)
