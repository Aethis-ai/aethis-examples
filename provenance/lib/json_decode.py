"""Normalize expected failures only at the untrusted JSON decoder boundary."""
from __future__ import annotations

import json


MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 100_000


def validate_json_tree(payload: object) -> None:
    """Bound the whole envelope, including unused fields, without recursion.

    The depth cap leaves room for subsequent JSON serialization, copying and
    comparison. The node cap bounds traversal, including cyclic injected data.
    """
    pending = [(payload, 0)]
    nodes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
            raise json.JSONDecodeError("JSON envelope exceeds depth or node bound", "", 0)
        if isinstance(value, dict):
            if len(value) > MAX_JSON_NODES - nodes - len(pending):
                raise json.JSONDecodeError("JSON envelope exceeds node bound", "", 0)
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            if len(value) > MAX_JSON_NODES - nodes - len(pending):
                raise json.JSONDecodeError("JSON envelope exceeds node bound", "", 0)
            pending.extend((child, depth + 1) for child in value)


def decode_json(raw: str | bytes | bytearray) -> dict:
    """Decode owning object envelopes, preserving failures from reader code."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("Expected JSON object", "", 0)
        validate_json_tree(payload)
        return payload
    except json.JSONDecodeError:
        raise
    except (ValueError, OverflowError, RecursionError):
        # CPython integer digit limits raise plain ValueError. Keep diagnostics
        # bounded and never widen the exception boundary around transport/read.
        raise json.JSONDecodeError("JSON decoder rejected input", "", 0) from None
