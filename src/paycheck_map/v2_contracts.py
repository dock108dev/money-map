"""Executable Money Map v2 contracts; no v2 persistence or runtime service lives here."""

from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from .money import ZERO, money

CONTRACT_VERSION: Final = "money-map-v2-contract-v1"
GOAL_CALCULATION_VERSION: Final = "goal-arithmetic-v1"
FINGERPRINT_VERSION: Final = "goal-source-fingerprint-v1"
MONTH_FRACTION: Final = Decimal("0.000000000001")


class ContractModel(BaseModel):
    """Strict, immutable base for values crossing a future v2 boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceClass(StrEnum):
    OBSERVED = "observed"
    DERIVED = "derived"
    USER_ENTERED = "user_entered"
    ASSUMED = "assumed"
    UNAVAILABLE = "unavailable"


class MoneyDerivation(StrEnum):
    ACCESSIBLE_NOW = "accessible_now"
    AVAILABLE_ABOVE_FLOOR = "available_above_floor"
    REMAINING_TARGET = "remaining_target"
    REQUIRED_FUNDING_PACE = "required_funding_pace"
    EFFECTIVE_RECURRING_TAKE_HOME = "effective_recurring_take_home"
    RECURRING_CASH_FLOW_GAP = "recurring_cash_flow_gap"
    COMPARISON_DELTA = "comparison_delta"
    UNEXPLAINED_RESIDUAL = "unexplained_residual"
    MILESTONE_AMOUNT = "milestone_amount"
    RETIREMENT_GOAL_SNAPSHOT = "retirement_goal_snapshot"


class EvidencedMoney(ContractModel):
    """An exact monetary value that cannot be separated from its evidence class."""

    amount: Decimal | None
    evidence: EvidenceClass
    source_refs: tuple[str, ...] = ()
    derivation: MoneyDerivation | None = None
    unavailable_reason: str | None = Field(default=None, min_length=1, max_length=240)

    @field_validator("amount", mode="before")
    @classmethod
    def parse_exact_money(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, (float, bool)):
            raise ValueError("Money must not pass through binary float or bool")
        return money(Decimal(str(value)))

    @field_validator("source_refs")
    @classmethod
    def stable_unique_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value):
            raise ValueError("Source references must be non-empty")
        if len(set(value)) != len(value):
            raise ValueError("Source references must be unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.evidence is EvidenceClass.UNAVAILABLE:
            if self.amount is not None:
                raise ValueError("Unavailable money cannot carry an amount")
            if self.derivation is not None:
                raise ValueError("Unavailable money cannot claim a derivation")
            if self.unavailable_reason is None:
                raise ValueError("Unavailable money requires a reason")
            return self
        if self.amount is None:
            raise ValueError("Available evidence classes require an exact amount")
        if self.unavailable_reason is not None:
            raise ValueError("Available money cannot carry an unavailable reason")
        if not self.source_refs:
            raise ValueError("Every available monetary value requires source references")
        if self.evidence is EvidenceClass.DERIVED and self.derivation is None:
            raise ValueError("Derived money requires a supported derivation")
        if self.evidence is not EvidenceClass.DERIVED and self.derivation is not None:
            raise ValueError("Only derived money can declare a derivation")
        return self

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, ".2f")


class PrimaryGoalProgram(ContractModel):
    goal_program_id: str = Field(pattern=r"^goal_[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=120)
    target_date: date
    target_amount: EvidencedMoney
    protected_cash_floor: EvidencedMoney
    reserved_for_goal: EvidencedMoney
    primary: Literal[True] = True
    reservation_policy: Literal["exclusive_primary_goal"] = "exclusive_primary_goal"
    source_life_goal_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_owner_configuration(self) -> Self:
        _require_evidence(self.target_amount, EvidenceClass.USER_ENTERED, "target_amount")
        _require_evidence(
            self.protected_cash_floor, EvidenceClass.USER_ENTERED, "protected_cash_floor"
        )
        _require_evidence(self.reserved_for_goal, EvidenceClass.USER_ENTERED, "reserved_for_goal")
        target = _required_amount(self.target_amount, "target_amount")
        floor = _required_amount(self.protected_cash_floor, "protected_cash_floor")
        reserved = _required_amount(self.reserved_for_goal, "reserved_for_goal")
        if min(target, floor, reserved) < ZERO:
            raise ValueError("Goal configuration money cannot be negative")
        if reserved > target:
            raise ValueError("Reserved money cannot exceed the goal target")
        return self


class PaceStatus(StrEnum):
    ACTIVE = "active"
    COMPLETE = "complete"
    EXPIRED = "expired"


class GoalPosition(ContractModel):
    goal_program_id: str = Field(pattern=r"^goal_[a-z0-9_]+$")
    observed_on: date
    target_date: date
    accessible_cash: EvidencedMoney
    accessible_investments: EvidencedMoney
    retirement_assets_excluded: EvidencedMoney
    tracked_debt: EvidencedMoney
    accessible_now: EvidencedMoney
    protected_cash_floor: EvidencedMoney
    available_above_floor: EvidencedMoney
    reserved_for_goal: EvidencedMoney
    goal_target: EvidencedMoney
    remaining_target: EvidencedMoney
    effective_recurring_take_home: EvidencedMoney
    observed_recurring_outflow: EvidencedMoney
    recurring_cash_flow_gap: EvidencedMoney
    funding_months: Decimal
    pace_status: PaceStatus
    required_funding_pace: EvidencedMoney
    calculation_version: Literal["goal-arithmetic-v1"] = GOAL_CALCULATION_VERSION

    @field_validator("funding_months", mode="before")
    @classmethod
    def parse_funding_months(cls, value: object) -> Decimal:
        if isinstance(value, (float, bool)):
            raise ValueError("Funding months must not pass through binary float or bool")
        return Decimal(str(value)).quantize(MONTH_FRACTION, rounding=ROUND_HALF_UP)

    @field_serializer("funding_months")
    def serialize_funding_months(self, value: Decimal) -> str:
        return format(value, ".12f")

    @model_validator(mode="after")
    def validate_arithmetic(self) -> Self:
        for name, value in (
            ("accessible_cash", self.accessible_cash),
            ("accessible_investments", self.accessible_investments),
            ("retirement_assets_excluded", self.retirement_assets_excluded),
            ("tracked_debt", self.tracked_debt),
            ("observed_recurring_outflow", self.observed_recurring_outflow),
        ):
            _require_evidence_or_unavailable(value, EvidenceClass.OBSERVED, name)
        _require_evidence_or_unavailable(
            self.effective_recurring_take_home,
            EvidenceClass.DERIVED,
            "effective_recurring_take_home",
        )
        if self.effective_recurring_take_home.amount is not None:
            _require_derivation(
                self.effective_recurring_take_home,
                MoneyDerivation.EFFECTIVE_RECURRING_TAKE_HOME,
                "effective_recurring_take_home",
            )
        _require_evidence(self.goal_target, EvidenceClass.USER_ENTERED, "goal_target")
        _require_evidence(
            self.protected_cash_floor, EvidenceClass.USER_ENTERED, "protected_cash_floor"
        )
        _require_evidence(self.reserved_for_goal, EvidenceClass.USER_ENTERED, "reserved_for_goal")
        target = _required_amount(self.goal_target, "goal_target")
        floor = _required_amount(self.protected_cash_floor, "protected_cash_floor")
        reserved = _required_amount(self.reserved_for_goal, "reserved_for_goal")
        if min(target, floor, reserved) < ZERO:
            raise ValueError("Goal target, floor, and reservation cannot be negative")
        if reserved > target:
            raise ValueError("Reserved money cannot exceed the goal target")

        _validate_sum(
            self.accessible_now,
            self.accessible_cash,
            self.accessible_investments,
            MoneyDerivation.ACCESSIBLE_NOW,
            "accessible_now",
        )
        _validate_available_above_floor(
            self.accessible_now, self.protected_cash_floor, self.available_above_floor
        )
        _validate_difference_to_zero(
            self.goal_target,
            self.reserved_for_goal,
            self.remaining_target,
            MoneyDerivation.REMAINING_TARGET,
            "remaining_target",
        )
        _validate_difference_to_zero(
            self.observed_recurring_outflow,
            self.effective_recurring_take_home,
            self.recurring_cash_flow_gap,
            MoneyDerivation.RECURRING_CASH_FLOW_GAP,
            "recurring_cash_flow_gap",
        )
        _validate_pace(self)
        return self


class GoalCheckIn(ContractModel):
    check_in_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    goal_program_id: str = Field(pattern=r"^goal_[a-z0-9_]+$")
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_observation_date: date
    position: GoalPosition
    created_at: datetime
    contract_version: Literal["money-map-v2-contract-v1"] = CONTRACT_VERSION

    @model_validator(mode="after")
    def validate_deterministic_identity(self) -> Self:
        expected = check_in_identity(self.goal_program_id, self.source_fingerprint)
        if self.check_in_id != expected:
            raise ValueError("Check-in identity must be deterministic from goal and source")
        if self.position.goal_program_id != self.goal_program_id:
            raise ValueError("Check-in position must belong to the same goal")
        if self.position.observed_on != self.effective_observation_date:
            raise ValueError("Check-in effective date must equal the position observation date")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Check-in creation time must be timezone-aware")
        return self


class GoalCheckInHistory(ContractModel):
    check_ins: tuple[GoalCheckIn, ...]

    @model_validator(mode="after")
    def reject_source_equivalent_duplicates(self) -> Self:
        identities = [(item.goal_program_id, item.source_fingerprint) for item in self.check_ins]
        if len(identities) != len(set(identities)):
            raise ValueError("Source-equivalent check-ins are duplicates")
        return self


class ComparisonComponentKind(StrEnum):
    ACCESSIBLE_NOW = "accessible_now"
    ACCESSIBLE_CASH = "accessible_cash"
    ACCESSIBLE_INVESTMENTS = "accessible_investments"
    TRACKED_DEBT = "tracked_debt"
    GOAL_TARGET = "goal_target"
    PROTECTED_CASH_FLOOR = "protected_cash_floor"
    RESERVED_FOR_GOAL = "reserved_for_goal"
    SUPPORTED_PAYROLL = "supported_payroll"
    SUPPORTED_TRANSFER = "supported_transfer"
    SUPPORTED_MARKET_MOVEMENT = "supported_market_movement"
    UNEXPLAINED_RESIDUAL = "unexplained_residual"


SUPPORTED_EVENT_COMPONENTS = {
    ComparisonComponentKind.SUPPORTED_PAYROLL,
    ComparisonComponentKind.SUPPORTED_TRANSFER,
    ComparisonComponentKind.SUPPORTED_MARKET_MOVEMENT,
}


class GoalComparisonComponent(ContractModel):
    component: ComparisonComponentKind
    change: EvidencedMoney
    interpretation: Literal["arithmetic_only", "evidence_supported_event"] = "arithmetic_only"
    supporting_evidence_refs: tuple[str, ...] = ()

    @field_validator("supporting_evidence_refs")
    @classmethod
    def unique_supporting_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value) or len(value) != len(set(value)):
            raise ValueError("Supporting evidence references must be non-empty and unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def limit_claim_to_supported_arithmetic(self) -> Self:
        derivation = (
            MoneyDerivation.UNEXPLAINED_RESIDUAL
            if self.component is ComparisonComponentKind.UNEXPLAINED_RESIDUAL
            else MoneyDerivation.COMPARISON_DELTA
        )
        _require_derivation(self.change, derivation, self.component.value)
        if self.component in SUPPORTED_EVENT_COMPONENTS:
            if self.interpretation != "evidence_supported_event":
                raise ValueError("Event components must be explicitly evidence-supported")
            if not self.supporting_evidence_refs:
                raise ValueError("Event components require supporting evidence references")
        elif self.interpretation != "arithmetic_only" or self.supporting_evidence_refs:
            raise ValueError("Arithmetic components cannot claim event evidence")
        return self


class GoalComparison(ContractModel):
    goal_program_id: str = Field(pattern=r"^goal_[a-z0-9_]+$")
    previous_check_in_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_check_in_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_observation_date: date
    current_observation_date: date
    components: tuple[GoalComparisonComponent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_distinct_ordered_check_ins(self) -> Self:
        if self.previous_check_in_id == self.current_check_in_id:
            raise ValueError("A check-in cannot be compared with itself")
        if self.previous_source_fingerprint == self.current_source_fingerprint:
            raise ValueError("Comparison requires distinct source fingerprints")
        if self.previous_observation_date > self.current_observation_date:
            raise ValueError("Comparison observations must be chronological")
        kinds = [item.component for item in self.components]
        if len(kinds) != len(set(kinds)):
            raise ValueError("Comparison component kinds must be unique")
        if ComparisonComponentKind.ACCESSIBLE_NOW not in kinds:
            raise ValueError("Comparison must contain the accessible-now arithmetic delta")
        if ComparisonComponentKind.UNEXPLAINED_RESIDUAL not in kinds:
            raise ValueError("Comparison must retain an unexplained residual")
        by_kind = {item.component: item for item in self.components}
        accessible_delta = _required_amount(
            by_kind[ComparisonComponentKind.ACCESSIBLE_NOW].change, "accessible_now change"
        )
        supported_events = sum(
            (
                _required_amount(by_kind[kind].change, f"{kind.value} change")
                for kind in SUPPORTED_EVENT_COMPONENTS
                if kind in by_kind
            ),
            ZERO,
        )
        residual = _required_amount(
            by_kind[ComparisonComponentKind.UNEXPLAINED_RESIDUAL].change,
            "unexplained_residual",
        )
        if residual != money(accessible_delta - supported_events):
            raise ValueError(
                "Unexplained residual must reconcile accessible change less supported events"
            )
        return self


class GoalMilestoneKind(StrEnum):
    DATA_UNAVAILABLE = "data_unavailable"
    RESTORE_FLOOR = "restore_floor"
    CLOSE_RECURRING_GAP = "close_recurring_gap"
    FUND_GOAL = "fund_goal"
    GOAL_COMPLETE = "goal_complete"


MILESTONE_RANK: dict[GoalMilestoneKind, int] = {
    GoalMilestoneKind.DATA_UNAVAILABLE: 0,
    GoalMilestoneKind.RESTORE_FLOOR: 1,
    GoalMilestoneKind.CLOSE_RECURRING_GAP: 2,
    GoalMilestoneKind.FUND_GOAL: 3,
    GoalMilestoneKind.GOAL_COMPLETE: 4,
}


class GoalMilestone(ContractModel):
    goal_program_id: str = Field(pattern=r"^goal_[a-z0-9_]+$")
    kind: GoalMilestoneKind
    sequence_rank: int = Field(ge=0, le=4)
    amount: EvidencedMoney
    position_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_sequence(self) -> Self:
        if self.sequence_rank != MILESTONE_RANK[self.kind]:
            raise ValueError("Milestone rank must match the deterministic sequence")
        if self.kind is GoalMilestoneKind.DATA_UNAVAILABLE:
            _require_evidence(self.amount, EvidenceClass.UNAVAILABLE, "milestone amount")
        else:
            _require_derivation(self.amount, MoneyDerivation.MILESTONE_AMOUNT, "milestone amount")
            if _required_amount(self.amount, "milestone amount") < ZERO:
                raise ValueError("Milestone amount cannot be negative")
        return self


def contract_milestone(position: GoalPosition, position_fingerprint: str) -> GoalMilestone:
    """Build the expected milestone vector; Slice 2 will own runtime selection."""

    source_ref = f"position:{position_fingerprint}"
    if position.accessible_cash.amount is None:
        return _unavailable_milestone(
            position, position_fingerprint, "Accessible cash evidence is unavailable"
        )
    floor = _required_amount(position.protected_cash_floor, "protected_cash_floor")
    floor_gap = money(max(floor - position.accessible_cash.amount, ZERO))
    if floor_gap > ZERO:
        return GoalMilestone(
            goal_program_id=position.goal_program_id,
            kind=GoalMilestoneKind.RESTORE_FLOOR,
            sequence_rank=1,
            amount=_milestone_money(floor_gap, source_ref),
            position_fingerprint=position_fingerprint,
        )
    if position.recurring_cash_flow_gap.amount is None:
        return _unavailable_milestone(
            position, position_fingerprint, "Recurring cash-flow evidence is unavailable"
        )
    if position.recurring_cash_flow_gap.amount > ZERO:
        return GoalMilestone(
            goal_program_id=position.goal_program_id,
            kind=GoalMilestoneKind.CLOSE_RECURRING_GAP,
            sequence_rank=2,
            amount=_milestone_money(position.recurring_cash_flow_gap.amount, source_ref),
            position_fingerprint=position_fingerprint,
        )
    remaining = _required_amount(position.remaining_target, "remaining_target")
    if remaining == ZERO:
        return GoalMilestone(
            goal_program_id=position.goal_program_id,
            kind=GoalMilestoneKind.GOAL_COMPLETE,
            sequence_rank=4,
            amount=_milestone_money(ZERO, source_ref),
            position_fingerprint=position_fingerprint,
        )
    if position.required_funding_pace.amount is None:
        return _unavailable_milestone(
            position, position_fingerprint, "Required pace is unavailable for an expired target"
        )
    return GoalMilestone(
        goal_program_id=position.goal_program_id,
        kind=GoalMilestoneKind.FUND_GOAL,
        sequence_rank=3,
        amount=_milestone_money(position.required_funding_pace.amount, source_ref),
        position_fingerprint=position_fingerprint,
    )


class RetirementGoalInclusion(ContractModel):
    goal_program_id: str = Field(pattern=r"^goal_[a-z0-9_]+$")
    goal_source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_amount: EvidencedMoney
    reserved_for_goal: EvidencedMoney
    remaining_target: EvidencedMoney
    selection: Literal["explicit"] = "explicit"

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        _require_evidence(self.target_amount, EvidenceClass.USER_ENTERED, "target_amount")
        _require_evidence(self.reserved_for_goal, EvidenceClass.USER_ENTERED, "reserved_for_goal")
        _require_derivation(
            self.remaining_target, MoneyDerivation.RETIREMENT_GOAL_SNAPSHOT, "remaining_target"
        )
        target = _required_amount(self.target_amount, "target_amount")
        reserved = _required_amount(self.reserved_for_goal, "reserved_for_goal")
        remaining = _required_amount(self.remaining_target, "remaining_target")
        if remaining != money(max(target - reserved, ZERO)):
            raise ValueError("Retirement goal inclusion must carry an exact copied snapshot")
        return self


class RetirementRunSelection(ContractModel):
    run_selection_id: str = Field(pattern=r"^retirement_[a-z0-9_]+$")
    include_operational_goal: bool = False
    included_goal: RetirementGoalInclusion | None = None
    goal_default_policy: Literal["excluded"] = "excluded"
    operational_goal_mutation: Literal[False] = False

    @model_validator(mode="after")
    def require_explicit_goal_inclusion(self) -> Self:
        if self.include_operational_goal != (self.included_goal is not None):
            raise ValueError("Goal inclusion flag and explicit goal snapshot must agree")
        return self


class LabExperimentSeedKind(StrEnum):
    BLANK = "blank"
    CURRENT_GOAL = "current_goal"
    RETIREMENT_RESULT = "retirement_result"


class LifeLabExperimentSeed(ContractModel):
    experiment_id: str = Field(pattern=r"^lab_[a-z0-9_]+$")
    seed_kind: LabExperimentSeedKind
    source_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    seeded_money: dict[str, EvidencedMoney] = Field(default_factory=dict)
    edit_scope: Literal["isolated_draft"] = "isolated_draft"
    goal_mutation: Literal[False] = False
    retirement_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_seed_origin(self) -> Self:
        if self.seed_kind is LabExperimentSeedKind.BLANK:
            if self.source_fingerprint is not None or self.seeded_money:
                raise ValueError("A blank experiment cannot claim copied source values")
        elif self.source_fingerprint is None or not self.seeded_money:
            raise ValueError("A sourced experiment requires a fingerprint and copied values")
        return self


class PromotionTarget(StrEnum):
    GOALS = "goals"
    RETIREMENT = "retirement"


class PromotionField(StrEnum):
    GOAL_TARGET = "goal_target"
    RESERVED_FOR_GOAL = "reserved_for_goal"
    PROTECTED_CASH_FLOOR = "protected_cash_floor"
    RETIREMENT_MONTHLY_SPEND = "retirement_monthly_spend"


class LifeLabPromotionChange(ContractModel):
    field: PromotionField
    before: EvidencedMoney
    after: EvidencedMoney

    @model_validator(mode="after")
    def require_visible_change(self) -> Self:
        if self.before.amount == self.after.amount:
            raise ValueError("Promotion preview changes must show a real before/after difference")
        return self


class LifeLabPromotionPreview(ContractModel):
    experiment_id: str = Field(pattern=r"^lab_[a-z0-9_]+$")
    experiment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_surface: PromotionTarget
    changes: tuple[LifeLabPromotionChange, ...] = Field(min_length=1)
    state: Literal["preview_only"] = "preview_only"
    requires_explicit_confirmation: Literal[True] = True
    applied: Literal[False] = False

    @model_validator(mode="after")
    def validate_supported_target_fields(self) -> Self:
        fields = [item.field for item in self.changes]
        if len(fields) != len(set(fields)):
            raise ValueError("Promotion preview fields must be unique")
        goal_fields = {
            PromotionField.GOAL_TARGET,
            PromotionField.RESERVED_FOR_GOAL,
            PromotionField.PROTECTED_CASH_FLOOR,
        }
        if self.target_surface is PromotionTarget.GOALS and not set(fields) <= goal_fields:
            raise ValueError("Goal promotion preview contains an unsupported field")
        if self.target_surface is PromotionTarget.RETIREMENT and fields != [
            PromotionField.RETIREMENT_MONTHLY_SPEND
        ]:
            raise ValueError("Retirement promotion preview contains an unsupported field")
        return self


class SourceRecordKind(StrEnum):
    BALANCE = "balance"
    INVESTMENT_ACCESS = "investment_access"
    PAYROLL = "payroll"
    RECURRING_OUTFLOW = "recurring_outflow"
    GOAL_CONFIGURATION = "goal_configuration"


class SourceMoneyFact(ContractModel):
    field: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    amount: Decimal
    evidence: Literal[
        EvidenceClass.OBSERVED,
        EvidenceClass.DERIVED,
        EvidenceClass.USER_ENTERED,
        EvidenceClass.ASSUMED,
    ]

    @field_validator("amount", mode="before")
    @classmethod
    def parse_source_money(cls, value: object) -> Decimal:
        if isinstance(value, (float, bool)):
            raise ValueError("Source money must not pass through binary float or bool")
        return money(Decimal(str(value)))

    @field_serializer("amount")
    def serialize_source_money(self, value: Decimal) -> str:
        return format(value, ".2f")


class FingerprintSourceRecord(ContractModel):
    kind: SourceRecordKind
    record_identity: str = Field(min_length=1, max_length=160)
    record_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    effective_date: date
    money_facts: tuple[SourceMoneyFact, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_fact_names(self) -> Self:
        names = [fact.field for fact in self.money_facts]
        if len(names) != len(set(names)):
            raise ValueError("Source record monetary fact names must be unique")
        return self


class FingerprintGoalConfiguration(ContractModel):
    goal_program_id: str = Field(pattern=r"^goal_[a-z0-9_]+$")
    target_date: date
    target_amount: EvidencedMoney
    protected_cash_floor: EvidencedMoney
    reserved_for_goal: EvidencedMoney

    @model_validator(mode="after")
    def validate_configuration_evidence(self) -> Self:
        _require_evidence(self.target_amount, EvidenceClass.USER_ENTERED, "target_amount")
        _require_evidence(
            self.protected_cash_floor, EvidenceClass.USER_ENTERED, "protected_cash_floor"
        )
        _require_evidence(self.reserved_for_goal, EvidenceClass.USER_ENTERED, "reserved_for_goal")
        return self


class SourceFingerprintMaterial(ContractModel):
    fingerprint_version: Literal["goal-source-fingerprint-v1"] = FINGERPRINT_VERSION
    calculation_version: Literal["goal-arithmetic-v1"] = GOAL_CALCULATION_VERSION
    goal_configuration: FingerprintGoalConfiguration
    source_records: tuple[FingerprintSourceRecord, ...] = Field(min_length=1)

    def canonical_payload(self) -> dict[str, object]:
        configuration = self.goal_configuration
        return {
            "fingerprint_version": self.fingerprint_version,
            "calculation_version": self.calculation_version,
            "goal_configuration": {
                "goal_program_id": configuration.goal_program_id,
                "target_date": configuration.target_date.isoformat(),
                "target_amount": _canonical_evidenced_money(configuration.target_amount),
                "protected_cash_floor": _canonical_evidenced_money(
                    configuration.protected_cash_floor
                ),
                "reserved_for_goal": _canonical_evidenced_money(configuration.reserved_for_goal),
            },
            "source_records": [
                {
                    "kind": record.kind.value,
                    "record_identity": record.record_identity,
                    "record_hash": record.record_hash,
                    "effective_date": record.effective_date.isoformat(),
                    "money_facts": [
                        {
                            "field": fact.field,
                            "amount": format(fact.amount, ".2f"),
                            "evidence": fact.evidence.value,
                        }
                        for fact in sorted(
                            record.money_facts,
                            key=lambda item: (item.field, item.evidence.value, item.amount),
                        )
                    ],
                }
                for record in sorted(
                    self.source_records,
                    key=lambda item: (
                        item.kind.value,
                        item.effective_date.isoformat(),
                        item.record_identity,
                        item.record_hash or "",
                    ),
                )
            ],
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.canonical_payload(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def check_in_identity(goal_program_id: str, source_fingerprint: str) -> str:
    """Return the one deterministic check-in identity for a goal/source pair."""

    material = f"{CONTRACT_VERSION}|{goal_program_id}|{source_fingerprint}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def remaining_funding_months(observed_on: date, target_date: date) -> Decimal:
    """Return actual-calendar partial months, inclusive of observation and target dates."""

    if target_date < observed_on:
        return Decimal("0").quantize(MONTH_FRACTION)
    with localcontext() as context:
        context.prec = 40
        if (observed_on.year, observed_on.month) == (target_date.year, target_date.month):
            days = Decimal(monthrange(observed_on.year, observed_on.month)[1])
            result = Decimal(target_date.day - observed_on.day + 1) / days
        else:
            observation_days = monthrange(observed_on.year, observed_on.month)[1]
            first_fraction = Decimal(observation_days - observed_on.day + 1) / Decimal(
                observation_days
            )
            target_days = monthrange(target_date.year, target_date.month)[1]
            last_fraction = Decimal(target_date.day) / Decimal(target_days)
            full_months = _whole_months_between(observed_on, target_date)
            result = first_fraction + Decimal(full_months) + last_fraction
    return result.quantize(MONTH_FRACTION, rounding=ROUND_HALF_UP)


def required_funding_pace(
    remaining_target: Decimal, observed_on: date, target_date: date
) -> Decimal | None:
    """Return the cent-rounded monthly pace, or None when an unfinished target expired."""

    remaining = money(remaining_target)
    if remaining <= ZERO:
        return ZERO
    months = remaining_funding_months(observed_on, target_date)
    if months == ZERO:
        return None
    return money(remaining / months)


def _whole_months_between(observed_on: date, target_date: date) -> int:
    distance = (target_date.year - observed_on.year) * 12 + target_date.month - observed_on.month
    return max(distance - 1, 0)


def _milestone_money(value: Decimal, source_ref: str) -> EvidencedMoney:
    return EvidencedMoney(
        amount=value,
        evidence=EvidenceClass.DERIVED,
        source_refs=(source_ref,),
        derivation=MoneyDerivation.MILESTONE_AMOUNT,
    )


def _unavailable_milestone(
    position: GoalPosition, position_fingerprint: str, reason: str
) -> GoalMilestone:
    return GoalMilestone(
        goal_program_id=position.goal_program_id,
        kind=GoalMilestoneKind.DATA_UNAVAILABLE,
        sequence_rank=0,
        amount=EvidencedMoney(
            amount=None,
            evidence=EvidenceClass.UNAVAILABLE,
            unavailable_reason=reason,
        ),
        position_fingerprint=position_fingerprint,
    )


def _required_amount(value: EvidencedMoney, name: str) -> Decimal:
    if value.amount is None:
        raise ValueError(f"{name} must be available")
    return value.amount


def _require_evidence(value: EvidencedMoney, evidence: EvidenceClass, name: str) -> None:
    if value.evidence is not evidence:
        raise ValueError(f"{name} must use {evidence.value} evidence")


def _require_evidence_or_unavailable(
    value: EvidencedMoney, evidence: EvidenceClass, name: str
) -> None:
    if value.evidence not in {evidence, EvidenceClass.UNAVAILABLE}:
        raise ValueError(f"{name} must use {evidence.value} or unavailable evidence")


def _require_derivation(value: EvidencedMoney, derivation: MoneyDerivation, name: str) -> None:
    _require_evidence(value, EvidenceClass.DERIVED, name)
    if value.derivation is not derivation:
        raise ValueError(f"{name} must use the {derivation.value} derivation")


def _validate_sum(
    result: EvidencedMoney,
    left: EvidencedMoney,
    right: EvidencedMoney,
    derivation: MoneyDerivation,
    name: str,
) -> None:
    if left.amount is None or right.amount is None:
        _require_evidence(result, EvidenceClass.UNAVAILABLE, name)
        return
    _require_derivation(result, derivation, name)
    if _required_amount(result, name) != money(left.amount + right.amount):
        raise ValueError(f"{name} does not equal its exact component sum")


def _validate_available_above_floor(
    accessible: EvidencedMoney, floor: EvidencedMoney, result: EvidencedMoney
) -> None:
    if accessible.amount is None:
        _require_evidence(result, EvidenceClass.UNAVAILABLE, "available_above_floor")
        return
    _require_derivation(result, MoneyDerivation.AVAILABLE_ABOVE_FLOOR, "available_above_floor")
    expected = money(max(accessible.amount - _required_amount(floor, "protected_cash_floor"), ZERO))
    if _required_amount(result, "available_above_floor") != expected:
        raise ValueError("available_above_floor must be capacity above the protected floor")


def _validate_difference_to_zero(
    minuend: EvidencedMoney,
    subtrahend: EvidencedMoney,
    result: EvidencedMoney,
    derivation: MoneyDerivation,
    name: str,
) -> None:
    if minuend.amount is None or subtrahend.amount is None:
        _require_evidence(result, EvidenceClass.UNAVAILABLE, name)
        return
    _require_derivation(result, derivation, name)
    expected = money(max(minuend.amount - subtrahend.amount, ZERO))
    if _required_amount(result, name) != expected:
        raise ValueError(f"{name} does not match the documented max-to-zero formula")


def _validate_pace(position: GoalPosition) -> None:
    remaining = _required_amount(position.remaining_target, "remaining_target")
    expected_months = remaining_funding_months(position.observed_on, position.target_date)
    if position.funding_months != expected_months:
        raise ValueError("funding_months does not match the calendar convention")
    expected_pace = required_funding_pace(remaining, position.observed_on, position.target_date)
    if remaining == ZERO:
        if position.pace_status is not PaceStatus.COMPLETE:
            raise ValueError("A funded goal must have complete pace status")
        _require_derivation(
            position.required_funding_pace,
            MoneyDerivation.REQUIRED_FUNDING_PACE,
            "required_funding_pace",
        )
    elif expected_pace is None:
        if position.pace_status is not PaceStatus.EXPIRED:
            raise ValueError("An unfinished expired goal must have expired pace status")
        _require_evidence(
            position.required_funding_pace, EvidenceClass.UNAVAILABLE, "required_funding_pace"
        )
        return
    else:
        if position.pace_status is not PaceStatus.ACTIVE:
            raise ValueError("A live unfinished goal must have active pace status")
        _require_derivation(
            position.required_funding_pace,
            MoneyDerivation.REQUIRED_FUNDING_PACE,
            "required_funding_pace",
        )
    if _required_amount(position.required_funding_pace, "required_funding_pace") != expected_pace:
        raise ValueError("required_funding_pace does not match remaining target and months")


def _canonical_evidenced_money(value: EvidencedMoney) -> dict[str, object]:
    return {
        "amount": None if value.amount is None else format(value.amount, ".2f"),
        "evidence": value.evidence.value,
        "source_refs": list(value.source_refs),
        "derivation": value.derivation.value if value.derivation is not None else None,
        "unavailable_reason": value.unavailable_reason,
    }
