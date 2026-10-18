from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import TextIO

from .random_values import parse_register_range


REFERENCE_BASES = {
    "Coils": 1,
    "Discrete Inputs": 10001,
    "Input Registers": 30001,
    "Holding Registers": 40001,
}
DATA_TYPES = set(REFERENCE_BASES)
ONE_BASED_OFFSET_LIMITS = {
    "Coils": 10000,
    "Discrete Inputs": REFERENCE_BASES["Discrete Inputs"],
}


@dataclass(frozen=True)
class CsvRecord:
    data_type: str
    address: int
    label: str
    value: int
    value_range: tuple[int, int] | None = None


def normalize_address(data_type: str, address: int) -> int:
    """Convert legacy Modbus references such as 40001 to zero-based offsets."""
    base = REFERENCE_BASES.get(data_type)
    # Coil references overlap ordinary zero-based offsets, so only unambiguous
    # register/input reference ranges are normalized automatically during import.
    if data_type != "Coils" and base is not None and base <= address < base + 10000:
        return address - base
    return address


def format_reference_address(data_type: str, address: int) -> str:
    if data_type not in REFERENCE_BASES:
        raise ValueError("Invalid data type")
    return f"{REFERENCE_BASES[data_type] + address:05d}"


def reference_to_offset(data_type: str, reference: str | int) -> int:
    if data_type not in REFERENCE_BASES:
        raise ValueError("Invalid data type")
    return int(reference) - REFERENCE_BASES[data_type]


def parse_csv_int(raw_value: str) -> int:
    text = raw_value.strip()
    try:
        return int(text, 0)
    except ValueError:
        return int(text, 10)


def parse_csv_address(data_type: str, raw_value: str, one_based_offsets: bool = False) -> int:
    text = raw_value.strip()
    address = parse_csv_int(text)
    if one_based_offsets and 0 < address < ONE_BASED_OFFSET_LIMITS[data_type]:
        return address - 1
    if data_type == "Coils" and len(text) >= 5 and text.startswith("0"):
        return address - REFERENCE_BASES["Coils"]
    return normalize_address(data_type, address)


def detect_one_based_types(rows: list[dict[str | None, str | None]], current_type: str) -> set[str]:
    addresses: dict[str, list[int]] = {"Coils": [], "Discrete Inputs": []}
    for row in rows:
        normalized = {(key or "").strip().lower(): (value or "") for key, value in row.items()}
        data_type = normalized.get("data_type", "").strip() or current_type
        if data_type not in addresses:
            continue
        try:
            address = parse_csv_int(normalized["address"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= address < ONE_BASED_OFFSET_LIMITS[data_type]:
            addresses[data_type].append(address)

    return {
        data_type
        for data_type, values in addresses.items()
        if values and min(values) == 1 and 0 not in values
    }


def parse_csv(stream: TextIO, current_type: str) -> tuple[list[CsvRecord], int]:
    sample = stream.read(4096)
    stream.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(stream, dialect=dialect)
    fields = {name.strip().lower() for name in (reader.fieldnames or [])}
    if not {"address", "value"}.issubset(fields):
        raise ValueError("CSV must contain at least the address and value columns")

    raw_rows = list(reader)
    one_based_types = detect_one_based_types(raw_rows, current_type)
    records: list[CsvRecord] = []
    skipped = 0
    for row in raw_rows:
        normalized = {(key or "").strip().lower(): (value or "") for key, value in row.items()}
        try:
            data_type = normalized.get("data_type", "").strip() or current_type
            if data_type not in DATA_TYPES:
                raise ValueError("Invalid data type")
            address = parse_csv_address(
                data_type,
                normalized["address"],
                one_based_offsets=data_type in one_based_types,
            )
            value = parse_csv_int(normalized["value"])
            if not 0 <= address <= 65535:
                raise ValueError("Address is outside the supported range")
            if data_type in {"Coils", "Discrete Inputs"}:
                if value not in {0, 1}:
                    raise ValueError("Bit values must be 0 or 1")
            elif not 0 <= value <= 65535:
                raise ValueError("Register values must be between 0 and 65535")
            range_text = normalized.get("range", "").strip()
            value_range = None
            if range_text:
                if data_type != "Holding Registers":
                    raise ValueError("Ranges are only supported for Holding Registers")
                value_range = parse_register_range(range_text)
            records.append(
                CsvRecord(
                    data_type=data_type,
                    address=address,
                    label=normalized.get("label", "").strip(),
                    value=value,
                    value_range=value_range,
                )
            )
        except (KeyError, TypeError, ValueError):
            skipped += 1
    return records, skipped
