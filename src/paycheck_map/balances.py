from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Account,
    AccountBalancePoint,
    AccountTransaction,
    BalanceSnapshot,
    ImportArtifact,
    ImportBatch,
    Institution,
)
from .money import ZERO, money

CALCULATION_VERSION = "account-balance-history-v1"


class BalancePointValues(TypedDict):
    account_id: int
    anchor_snapshot_id: int
    balance_date: date
    kind: str
    amount: Decimal
    source_kind: str
    coverage_start: date
    coverage_end: date
    calculation_version: str
    fingerprint: str


def _month_end(value: date) -> date:
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def _next_month(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def _fingerprint(
    account_id: int,
    anchor: BalanceSnapshot,
    balance_date: date,
    kind: str,
    value: Decimal,
    coverage_start: date,
) -> str:
    payload = {
        "version": CALCULATION_VERSION,
        "account_id": account_id,
        "anchor_snapshot_id": anchor.id,
        "anchor_date": anchor.snapshot_date.isoformat(),
        "anchor_amount": f"{money(anchor.amount):.2f}",
        "balance_date": balance_date.isoformat(),
        "kind": kind,
        "amount": f"{money(value):.2f}",
        "coverage_start": coverage_start.isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def generate_account_balance_points(session: Session) -> dict[str, int]:
    """Reconstruct month boundaries backward from the latest observed bank balance."""

    desired: dict[tuple[int, date, str], BalancePointValues] = {}
    accounts = list(
        session.scalars(select(Account).join(Institution).where(Institution.kind == "bank"))
    )
    for account in accounts:
        anchor = session.scalar(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account.id)
            .order_by(BalanceSnapshot.snapshot_date.desc(), BalanceSnapshot.id.desc())
            .limit(1)
        )
        if anchor is None:
            continue
        transactions = list(
            session.scalars(
                select(AccountTransaction)
                .where(
                    AccountTransaction.account_id == account.id,
                    AccountTransaction.posted_date <= anchor.snapshot_date,
                )
                .order_by(AccountTransaction.posted_date, AccountTransaction.id)
            )
        )
        coverage_start = transactions[0].posted_date if transactions else anchor.snapshot_date
        points: list[tuple[date, str, Decimal]] = []
        if not transactions:
            points.append((anchor.snapshot_date, "observed", anchor.amount))
        else:
            month = coverage_start.replace(day=1)
            while month <= anchor.snapshot_date:
                close_date = min(_month_end(month), anchor.snapshot_date)
                activity_after = sum(
                    (
                        transaction.amount
                        for transaction in transactions
                        if close_date < transaction.posted_date <= anchor.snapshot_date
                    ),
                    ZERO,
                )
                closing = money(anchor.amount - activity_after)
                month_activity = sum(
                    (
                        transaction.amount
                        for transaction in transactions
                        if month <= transaction.posted_date <= close_date
                    ),
                    ZERO,
                )
                opening = money(closing - month_activity)
                open_date = max(month, coverage_start)
                points.append(
                    (open_date, "month_open" if open_date == month else "coverage_open", opening)
                )
                points.append(
                    (
                        close_date,
                        "observed" if close_date == anchor.snapshot_date else "month_close",
                        closing,
                    )
                )
                month = _next_month(month)
        for balance_date, kind, value in points:
            key = (account.id, balance_date, kind)
            desired[key] = {
                "account_id": account.id,
                "anchor_snapshot_id": anchor.id,
                "balance_date": balance_date,
                "kind": kind,
                "amount": value,
                "source_kind": "observed" if kind == "observed" else "calculated",
                "coverage_start": coverage_start,
                "coverage_end": anchor.snapshot_date,
                "calculation_version": CALCULATION_VERSION,
                "fingerprint": _fingerprint(
                    account.id, anchor, balance_date, kind, value, coverage_start
                ),
            }

    existing = {
        (point.account_id, point.balance_date, point.kind): point
        for point in session.scalars(select(AccountBalancePoint).order_by(AccountBalancePoint.id))
    }
    for key, point in existing.items():
        if key not in desired:
            session.delete(point)
    for key, values in desired.items():
        current_point = existing.get(key)
        if current_point is None:
            current_point = AccountBalancePoint(
                account_id=values["account_id"],
                anchor_snapshot_id=values["anchor_snapshot_id"],
                balance_date=values["balance_date"],
                kind=values["kind"],
                amount=values["amount"],
                source_kind=values["source_kind"],
                coverage_start=values["coverage_start"],
                coverage_end=values["coverage_end"],
                calculation_version=values["calculation_version"],
                fingerprint=values["fingerprint"],
            )
        else:
            for field_name, field_value in values.items():
                setattr(current_point, field_name, field_value)
        session.add(current_point)
    session.flush()
    return {
        "points": len(desired),
        "observed": sum(str(values["source_kind"]) == "observed" for values in desired.values()),
        "calculated": sum(
            str(values["source_kind"]) == "calculated" for values in desired.values()
        ),
    }


def add_manual_value_observation(
    session: Session,
    *,
    account_id: int,
    observation_date: date,
    value: Decimal,
    source_note: str,
) -> BalanceSnapshot:
    account = session.get(Account, account_id)
    if account is None:
        raise ValueError("Account was not found")
    normalized = money(value)
    digest = hashlib.sha256(
        f"manual-value:{account_id}:{observation_date}:{normalized:.2f}:{source_note}".encode()
    ).hexdigest()
    artifact = session.scalar(select(ImportArtifact).where(ImportArtifact.sha256 == digest))
    if artifact is None:
        batch = ImportBatch(
            status="complete",
            requested_source="manual_value",
            artifact_count=1,
            imported_count=1,
        )
        session.add(batch)
        session.flush()
        artifact = ImportArtifact(
            batch_id=batch.id,
            sha256=digest,
            original_filename=f"manual-account-value-{observation_date.isoformat()}.json",
            source_kind="manual_value",
            adapter="manual_account_value",
            parser_version=CALCULATION_VERSION,
        )
        session.add(artifact)
        session.flush()
    snapshot = session.scalar(
        select(BalanceSnapshot).where(
            BalanceSnapshot.account_id == account_id,
            BalanceSnapshot.snapshot_date == observation_date,
            BalanceSnapshot.kind == "manual",
        )
    )
    if snapshot is None:
        snapshot = BalanceSnapshot(
            account_id=account_id,
            artifact_id=artifact.id,
            snapshot_date=observation_date,
            kind="manual",
            amount=normalized,
        )
    else:
        snapshot.artifact_id = artifact.id
        snapshot.amount = normalized
    session.add(snapshot)
    session.flush()
    return snapshot
