"""Shared read-only definition of complete observed cash months."""

from __future__ import annotations

import calendar
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, AccountBalancePoint, BalanceSnapshot, Institution


@dataclass(frozen=True)
class CompleteCashMonthEvidence:
    accounts: tuple[Account, ...]
    months: frozenset[tuple[int, int]]
    coverage_refs: tuple[str, ...]


def complete_observed_cash_months(session: Session) -> CompleteCashMonthEvidence:
    """Return months with both boundaries for every supported cash account."""

    with session.no_autoflush:
        cash_accounts = tuple(
            session.scalars(
                select(Account)
                .join(Institution)
                .where(
                    Institution.kind == "bank",
                    Account.account_type.in_(["checking", "savings"]),
                )
                .order_by(Account.id)
            )
        )
        complete_by_account: list[set[tuple[int, int]]] = []
        coverage_refs: list[str] = []
        for account in cash_accounts:
            snapshots = list(
                session.scalars(
                    select(BalanceSnapshot)
                    .where(BalanceSnapshot.account_id == account.id)
                    .order_by(BalanceSnapshot.id)
                )
            )
            snapshot_openings = {
                (row.snapshot_date.year, row.snapshot_date.month)
                for row in snapshots
                if row.kind == "opening" and row.snapshot_date.day == 1
            }
            snapshot_closings = {
                (row.snapshot_date.year, row.snapshot_date.month)
                for row in snapshots
                if row.kind in {"closing", "current"}
                and row.snapshot_date.day
                == calendar.monthrange(row.snapshot_date.year, row.snapshot_date.month)[1]
            }
            points = list(
                session.scalars(
                    select(AccountBalancePoint)
                    .where(AccountBalancePoint.account_id == account.id)
                    .order_by(AccountBalancePoint.id)
                )
            )
            point_openings = {
                (row.balance_date.year, row.balance_date.month)
                for row in points
                if row.kind == "month_open"
            }
            point_closings = {
                (row.balance_date.year, row.balance_date.month)
                for row in points
                if row.kind == "month_close"
                or (
                    row.source_kind == "observed"
                    and row.balance_date.day
                    == calendar.monthrange(row.balance_date.year, row.balance_date.month)[1]
                )
            }
            complete_by_account.append(
                (snapshot_openings & snapshot_closings) | (point_openings & point_closings)
            )
            coverage_refs.extend(f"balance_snapshot:{row.id}" for row in snapshots)
            coverage_refs.extend(f"balance_point:{row.id}:{row.fingerprint}" for row in points)

    complete_months = set.intersection(*complete_by_account) if complete_by_account else set()
    return CompleteCashMonthEvidence(
        accounts=cash_accounts,
        months=frozenset(complete_months),
        coverage_refs=tuple(coverage_refs),
    )
