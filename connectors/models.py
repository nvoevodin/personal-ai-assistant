"""Typed Pydantic data models for life-stream events and connector feeds."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class LifeStreamType(str, Enum):
    """Categorical streams monitored by the assistant."""

    FINANCE = "finance"
    EMAIL = "email"
    TELEMATICS = "telematics"
    GENERAL = "general"


class StreamEvent(BaseModel):
    """Normalized life-stream event consumed by the agent context builder."""

    id: str = Field(description="Unique event identifier")
    stream_type: LifeStreamType = Field(description="Origin stream type")
    source: str = Field(description="Connector identifier (e.g. monarch, gmail, tesla)")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Event creation or ingest timestamp (UTC)",
    )
    title: str = Field(description="Short human-readable headline")
    summary: str = Field(description="Sanitized summary description")
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured sanitized payload specific to the connector",
    )
    is_urgent: bool = Field(default=False, description="Flag indicating urgent notification priority")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary connector metadata")


class MonarchTransaction(BaseModel):
    """Structured representation of a Monarch Money transaction."""

    transaction_id: str
    merchant: str
    amount: float
    category: str
    account_name: str
    account_mask: str = Field(description="Masked account identifier (e.g. ****1234)")
    timestamp: datetime
    pending: bool = False
    notes: str | None = None


class MonarchAccount(BaseModel):
    """Snapshot of a financial account balance."""

    account_id: str
    name: str
    type: str  # checking, savings, credit, investment
    balance: float
    mask: str
    updated_at: datetime


class GmailAlert(BaseModel):
    """Structured representation of a Gmail message or alert."""

    message_id: str
    sender: str
    subject: str
    snippet: str
    received_at: datetime
    category: str = "general"  # receipt, security, travel, delivery, alert
    is_starred: bool = False


class TelematicsPing(BaseModel):
    """Structured vehicle status update."""

    vehicle_id: str
    battery_level_pct: float | None = None
    fuel_level_pct: float | None = None
    odometer_miles: float
    is_locked: bool
    tire_pressure_ok: bool
    location_summary: str
    active_alerts: list[str] = Field(default_factory=list)
    recorded_at: datetime
