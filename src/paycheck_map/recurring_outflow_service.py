"""Conservative read-only repeated external-outflow detection."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.orm import Session

from .cash_flow_service import CashFlowClassification, classify_bank_transaction
from .cash_months import complete_observed_cash_months
from .models import Account, AccountTransaction, ImportArtifact, TransferMatch
from .money import ZERO, money
from .v2_contracts import EvidenceClass
from .v21_contracts import (
    RecurringOutflowAmountRange,
    RecurringOutflowCadence,
    RecurringOutflowCandidate,
    RecurringOutflowCandidateList,
    V21EvidencedMoney,
    V21MoneyDerivation,
)


def recurring_outflow_candidates(
    session: Session, *, observed_on: date
) -> RecurringOutflowCandidateList:
    """Return only high-confidence candidates from complete cash months."""

    with session.no_autoflush:
        coverage = complete_observed_cash_months(session)
        if not coverage.accounts:
            return RecurringOutflowCandidateList(
                state="unavailable",
                observed_on=observed_on,
                reason="No supported checking or savings accounts establish coverage",
            )
        if not coverage.months:
            return RecurringOutflowCandidateList(
                state="unavailable",
                observed_on=observed_on,
                reason="No complete observed cash months establish candidate evidence",
            )
        if len(coverage.months) < 3:
            return RecurringOutflowCandidateList(state="empty", observed_on=observed_on)

        account_ids = [account.id for account in coverage.accounts]
        matched_ids: set[int] = set()
        for match in session.scalars(select(TransferMatch)):
            matched_ids.update((match.left_transaction_id, match.right_transaction_id))
        transactions = list(
            session.scalars(
                select(AccountTransaction)
                .where(
                    AccountTransaction.account_id.in_(account_ids),
                    AccountTransaction.amount < ZERO,
                )
                .order_by(
                    AccountTransaction.posted_date,
                    AccountTransaction.id,
                )
            )
        )
        artifact_ids = {row.artifact_id for row in transactions}
        artifact_hashes = {
            artifact_id: sha256
            for artifact_id, sha256 in session.execute(
                select(ImportArtifact.id, ImportArtifact.sha256).where(
                    ImportArtifact.id.in_(artifact_ids)
                )
            ).tuples()
        }

    safe_labels = _safe_account_labels(coverage.accounts)
    grouped: dict[tuple[int, str], list[AccountTransaction]] = defaultdict(list)
    for row in transactions:
        month = (row.posted_date.year, row.posted_date.month)
        if month not in coverage.months:
            continue
        classified = classify_bank_transaction(row, matched_transaction_ids=matched_ids)
        if classified.classification is not CashFlowClassification.EXTERNAL_OUTFLOW:
            continue
        normalized = _normalize_description(row.original_description)
        if not normalized:
            continue
        grouped[(row.account_id, normalized)].append(row)

    candidates: list[RecurringOutflowCandidate] = []
    for (account_id, normalized), rows in sorted(grouped.items()):
        cadence = _supported_cadence(rows)
        if cadence is None:
            continue
        occurrence_months = tuple(sorted({row.posted_date.strftime("%Y-%m") for row in rows}))
        if len(occurrence_months) < 3:
            continue
        amounts = [money(abs(row.amount)) for row in rows]
        median = _median_money(amounts)
        tolerance = max(Decimal("2.00"), median * Decimal("0.10"))
        if any(abs(amount - median) > tolerance for amount in amounts):
            continue
        refs = tuple(
            sorted(
                f"account_transaction:{row.id}:artifact:{artifact_hashes[row.artifact_id]}"
                for row in rows
            )
        )
        typical = _typical_monthly(median, cadence)
        label = safe_labels[account_id]
        identifier = _candidate_id(
            safe_account_label=label,
            normalized_description=normalized,
            cadence=cadence,
            rows=rows,
            amounts=amounts,
        )
        candidates.append(
            RecurringOutflowCandidate(
                candidate_id=identifier,
                observed_description=_display_description(rows[0].original_description),
                safe_account_label=label,
                cadence=cadence,
                occurrence_count=len(rows),
                first_observed_date=rows[0].posted_date,
                last_observed_date=rows[-1].posted_date,
                median_observed_amount=_derived_candidate_money(
                    median,
                    V21MoneyDerivation.RECURRING_OUTFLOW_MEDIAN,
                    refs,
                ),
                typical_monthly_amount=_derived_candidate_money(
                    typical,
                    V21MoneyDerivation.RECURRING_OUTFLOW_TYPICAL_MONTHLY,
                    refs,
                ),
                amount_range=RecurringOutflowAmountRange(
                    minimum=_observed_candidate_money(min(amounts), refs),
                    maximum=_observed_candidate_money(max(amounts), refs),
                ),
                source_refs=refs,
                coverage_months=occurrence_months,
            )
        )

    return RecurringOutflowCandidateList(
        state="available" if candidates else "empty",
        observed_on=observed_on,
        candidates=tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.safe_account_label,
                    item.observed_description.casefold(),
                    item.candidate_id,
                ),
            )
        ),
    )


def _normalize_description(value: str) -> str:
    return " ".join(value.split()).casefold()


def _display_description(value: str) -> str:
    return " ".join(value.split())


def _safe_account_labels(accounts: tuple[Account, ...]) -> dict[int, str]:
    counts: dict[str, int] = defaultdict(int)
    labels: dict[int, str] = {}
    for account in accounts:
        account_type = account.account_type.casefold()
        counts[account_type] += 1
        labels[account.id] = (
            f"{account_type.replace('_', ' ').title()} account {counts[account_type]}"
        )
    return labels


def _supported_cadence(
    rows: list[AccountTransaction],
) -> RecurringOutflowCadence | None:
    dates = [row.posted_date for row in rows]
    intervals = [(right - left).days for left, right in pairwise(dates)]
    rules = (
        (RecurringOutflowCadence.MONTHLY, 3, 25, 35),
        (RecurringOutflowCadence.BIWEEKLY, 5, 12, 16),
        (RecurringOutflowCadence.WEEKLY, 8, 6, 8),
    )
    for cadence, minimum, low, high in rules:
        if len(rows) >= minimum and intervals and all(low <= value <= high for value in intervals):
            return cadence
    return None


def _median_money(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    raw = (
        ordered[midpoint]
        if len(ordered) % 2
        else (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")
    )
    return money(raw)


def _typical_monthly(median: Decimal, cadence: RecurringOutflowCadence) -> Decimal:
    multiplier = {
        RecurringOutflowCadence.MONTHLY: Decimal("1"),
        RecurringOutflowCadence.BIWEEKLY: Decimal("26") / Decimal("12"),
        RecurringOutflowCadence.WEEKLY: Decimal("52") / Decimal("12"),
    }[cadence]
    return money(median * multiplier)


def _candidate_id(
    *,
    safe_account_label: str,
    normalized_description: str,
    cadence: RecurringOutflowCadence,
    rows: list[AccountTransaction],
    amounts: list[Decimal],
) -> str:
    payload = {
        "safe_account_label": safe_account_label,
        "normalized_description": normalized_description,
        "cadence": cadence.value,
        "occurrences": [
            {"date": row.posted_date.isoformat(), "amount": format(amount, ".2f")}
            for row, amount in zip(rows, amounts, strict=True)
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return f"candidate_{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"


def _derived_candidate_money(
    amount: Decimal,
    derivation: V21MoneyDerivation,
    refs: tuple[str, ...],
) -> V21EvidencedMoney:
    return V21EvidencedMoney(
        amount=amount,
        evidence=EvidenceClass.DERIVED,
        source_refs=refs,
        derivation=derivation,
    )


def _observed_candidate_money(amount: Decimal, refs: tuple[str, ...]) -> V21EvidencedMoney:
    return V21EvidencedMoney(
        amount=amount,
        evidence=EvidenceClass.OBSERVED,
        source_refs=refs,
    )
