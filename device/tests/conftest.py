import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

META_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "meta.schema.json"


@pytest.fixture(scope="session")
def meta_validator() -> Draft202012Validator:
    schema = json.loads(META_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)
