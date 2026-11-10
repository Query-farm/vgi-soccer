"""Metadata and conversion helpers shared by every soccer schema and function."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pyarrow as pa

_COMMENT_KEY = b"comment"

TIMESTAMP = pa.timestamp("us", tz="UTC")


def field(name: str, kind: pa.DataType, comment: str, *, nullable: bool = True) -> pa.Field:
    """Build an Arrow field carrying its SQL column comment."""
    return pa.field(name, kind, nullable=nullable, metadata={_COMMENT_KEY: comment.encode()})


def comment_of(value: pa.Field) -> str:
    """Return the comment stored on an Arrow field."""
    if value.metadata and _COMMENT_KEY in value.metadata:
        return value.metadata[_COMMENT_KEY].decode()
    return ""


def column_comments(schema: pa.Schema) -> dict[str, str]:
    """Return the column-comment mapping expected by a catalog table."""
    return {value.name: comment_of(value) for value in schema if comment_of(value)}


def sql_type(kind: pa.DataType) -> str:
    """Render an Arrow type as the DuckDB type name clients will see."""
    if pa.types.is_decimal(kind):
        return f"DECIMAL({kind.precision},{kind.scale})"
    if pa.types.is_timestamp(kind):
        return "TIMESTAMP WITH TIME ZONE" if kind.tz else "TIMESTAMP"
    if pa.types.is_date(kind):
        return "DATE"
    if pa.types.is_boolean(kind):
        return "BOOLEAN"
    if pa.types.is_int32(kind):
        return "INTEGER"
    if pa.types.is_int64(kind):
        return "BIGINT"
    if pa.types.is_float64(kind):
        return "DOUBLE"
    if pa.types.is_string(kind):
        return "VARCHAR"
    raise ValueError(f"Unsupported soccer result type: {kind}")


def result_columns_schema(schema: pa.Schema) -> str:
    """Render a static Arrow result schema as VGI discovery metadata."""
    return json.dumps(
        [
            {
                "name": value.name,
                "type": sql_type(value.type),
                "description": comment_of(value).removesuffix("."),
            }
            for value in schema
        ],
        separators=(",", ":"),
    )


def mapping(value: Any) -> Mapping[str, Any]:
    """Return ``value`` when it is a JSON object, otherwise an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def sequence(value: Any) -> list[Any]:
    """Return ``value`` when it is a JSON array, otherwise an empty list."""
    return value if isinstance(value, list) else []


def to_int(value: Any) -> int | None:
    """Parse an integer-like value (``"12"``, ``12.0``) without treating booleans as integers."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    try:
        return int(str(value).strip().lstrip("+"))
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = float(str(value))
        except (TypeError, ValueError, OverflowError):
            return None
        return int(parsed) if parsed.is_integer() else None


def to_decimal(value: Any, places: int = 1) -> Decimal | None:
    """Parse a finite decimal, quantized to ``places`` digits; display markers become null."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).strip().rstrip("%"))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite():
        return None
    return result.quantize(Decimal(1).scaleb(-places))


def to_float(value: Any) -> float | None:
    """Parse a finite float."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def to_bool(value: Any) -> bool | None:
    """Return a JSON boolean, or null for anything else."""
    return value if isinstance(value, bool) else None


def to_text(value: Any) -> str | None:
    """Return a non-empty stripped string, or null."""
    if value is None or isinstance(value, Mapping | list):
        return None
    text = str(value).strip()
    return text or None


def to_timestamp(value: Any) -> datetime | None:
    """Parse ESPN/OpenLigaDB ISO-8601 timestamps (``2026-11-08T14:00Z``) into UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def to_date(value: Any) -> date | None:
    """Parse the date part of an ISO-8601 date or timestamp string."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def ref_id(value: Any, segment: str) -> int | None:
    """Extract the numeric id following ``/segment/`` in an ESPN core ``$ref`` URL."""
    ref = mapping(value).get("$ref")
    if not isinstance(ref, str):
        return None
    marker = f"/{segment}/"
    if marker not in ref:
        return None
    return to_int(ref.split(marker, 1)[1].split("?", 1)[0].split("/", 1)[0])


def batch_from_rows(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> pa.RecordBatch:
    """Build a record batch in the declared (possibly projected) column order."""
    return pa.RecordBatch.from_arrays(
        [pa.array([row.get(value.name) for row in rows], type=value.type) for value in schema],
        schema=schema,
    )
