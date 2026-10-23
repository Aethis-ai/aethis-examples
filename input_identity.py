"""Public RFC 8785/NFC input identity used by examples and proof checks."""

import hashlib
import unicodedata
from typing import Any

import rfc8785


def _nfc(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {unicodedata.normalize("NFC", str(k)): _nfc(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_nfc(v) for v in value]
    return value


def canonical_input_hash(field_values: dict[str, Any]) -> str:
    """Return the public API's NFC-normalised RFC 8785 input digest."""
    return "sha256:" + hashlib.sha256(rfc8785.dumps(_nfc(field_values))).hexdigest()


def needs_numeric_schema(field_values: dict[str, Any]) -> bool:
    """Only schema-sensitive decimal values need an additional schema read."""
    return any(
        isinstance(v, float) and v != float(format(v, ".15g"))
        for v in field_values.values()
    )


def decision_input_hash(
    field_values: dict[str, Any],
    envelope: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> str:
    """Bind inputs using the public decimal contract and exact decision schema.

    Decimal fields use 15 significant digits. Other field types retain their
    submitted representation. A schema from another publication is insufficient.
    """
    if not needs_numeric_schema(field_values):
        return canonical_input_hash(field_values)
    if not isinstance(schema, dict) or any(
        not envelope.get(k) or schema.get(k) != envelope[k]
        for k in ("ruleset_id", "ruleset_version", "content_digest")
    ):
        raise ValueError("Decimal input identity needs the exact decision schema")
    fields = schema.get("fields")
    if not isinstance(fields, list) or any(not isinstance(f, dict) for f in fields):
        raise ValueError("Malformed field schema")
    sorts: dict[str, str] = {}
    supported = {"integer", "real", "boolean", "enum", "date", "duration", "string"}
    for field in fields:
        name, kind = field.get("field_id"), field.get("field_type")
        if (
            not isinstance(name, str)
            or not name
            or name in sorts
            or kind not in supported
        ):
            raise ValueError("Field schema needs unique IDs and supported types")
        sorts[name] = kind
    if any(isinstance(v, float) and k not in sorts for k, v in field_values.items()):
        raise ValueError("Decimal input is not declared in the schema")
    values = {
        k: float(format(v, ".15g"))
        if sorts.get(k) == "real" and isinstance(v, float)
        else v
        for k, v in field_values.items()
    }
    return canonical_input_hash(values)
