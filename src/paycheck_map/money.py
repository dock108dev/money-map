from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Numeric
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal | str | int) -> Decimal:
    """Return a two-place Decimal without ever passing through binary float."""

    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class Money(TypeDecorator[Decimal]):
    """Exact database money type."""

    impl = Numeric(20, 2, asdecimal=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Decimal | None:
        del dialect
        if value is None:
            return None
        return money(str(value))

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        del dialect
        if value is None:
            return None
        return money(str(value))
