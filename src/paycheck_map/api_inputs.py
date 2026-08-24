"""Request bodies used by the primary FastAPI router."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class CorrectionInput(BaseModel):
    entity_type: str
    entity_id: int
    field_name: str
    new_value: Decimal
    reason: str = Field(min_length=3, max_length=500)


class PlaidConfigurationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["sandbox", "production"]


class PlaidLinkInput(BaseModel):
    environment: Literal["sandbox", "production"] = "sandbox"
    target: Literal["sofi", "fidelity"]


class PlaidExchangeInput(BaseModel):
    session_id: str
    public_token: SecretStr


class ManualValueInput(BaseModel):
    observation_date: date
    value: Decimal = Field(ge=0)
    source_note: str = Field(min_length=3, max_length=200)


class PlaidSyncAllInput(BaseModel):
    automatic: bool = False


class AutoRefreshPreferenceInput(BaseModel):
    enabled: bool
