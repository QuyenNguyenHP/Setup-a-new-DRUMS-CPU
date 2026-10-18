from __future__ import annotations

import random
from collections.abc import Callable


REGISTER_MIN = 0
REGISTER_MAX = 65535


def parse_register_range(text: str) -> tuple[int, int]:
    """Parse an inclusive Modbus register range in ``min;max`` format."""
    parts = [part.strip() for part in text.split(";")]
    if len(parts) != 2 or not all(parts):
        raise ValueError("Range must contain two numbers separated by ';' (example: 10;100)")

    try:
        parsed = []
        for part in parts:
            try:
                parsed.append(int(part, 0))
            except ValueError:
                parsed.append(int(part, 10))
        minimum, maximum = parsed
    except ValueError as exc:
        raise ValueError("Range values must be whole numbers") from exc

    if not REGISTER_MIN <= minimum <= REGISTER_MAX or not REGISTER_MIN <= maximum <= REGISTER_MAX:
        raise ValueError(f"Range values must be between {REGISTER_MIN} and {REGISTER_MAX}")
    if minimum > maximum:
        raise ValueError("The first range value must not be greater than the second")
    return minimum, maximum


def format_register_range(value_range: tuple[int, int] | None) -> str:
    if value_range is None:
        return ""
    return f"{value_range[0]};{value_range[1]}"


def random_register_value(
    value_range: tuple[int, int],
    randint: Callable[[int, int], int] = random.randint,
) -> int:
    """Return an integer from an inclusive register range."""
    return randint(*value_range)
