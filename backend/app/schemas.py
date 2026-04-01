from datetime import datetime
from typing import Any, List

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SpaceObjectOut(BaseModel):
    norad_id: int
    name: str
    object_type: str
    altitude_km: float
    inclination_deg: float

    class Config:
        from_attributes = True


class CollisionAlertOut(BaseModel):
    id: int
    primary_name: str
    secondary_name: str
    miss_distance_km: float
    tca_hours: float
    risk_score: float
    impact_summary: str
    is_urgent: bool
    created_at: datetime


class ScreeningRequest(BaseModel):
    primary_norad_id: int
    secondary_count: int = 100
    horizon_hours: float = 24.0
    threshold_km: float = 5.0
    step_sec: int = 60


class ScreeningResult(BaseModel):
    run_id: int
    alerts_generated: int
    alerts: List[CollisionAlertOut]


class LaunchAssessmentRequest(BaseModel):
    mission_id: str
    vehicle: str
    site: str
    orbit: str
    azimuth_deg: float
    inclination_deg: float
    perigee_km: float
    apogee_km: float
    debris_density: float
    wind_kt: float
    precip: str
    lightning_10nm: bool
    range_conflicts: str = ""
    notes: str = ""


class LaunchAssessmentOut(BaseModel):
    id: int
    mission_id: str
    risk_score: float
    confidence: float
    category: str
    explanation: str
    report: dict[str, Any] | None = None
    created_at: datetime


class DashboardStats(BaseModel):
    payloads: int
    debris: int
    rockets: int
    others: int
    catalog_size: int
    alerts: int


class OrbitalObjectOut(BaseModel):
    norad_id: int
    name: str
    object_type: str
    country: str
    tle_line1: str
    tle_line2: str
    epoch: str
    updated_at: datetime

    class Config:
        from_attributes = True


class IngestResult(BaseModel):
    source: str
    ingested: int
    updated: int
    skipped: int


class ManeuverOut(BaseModel):
    id: int
    norad_id: int
    object_name: str
    delta_v_ms: float
    reason: str
    event_time: datetime
    notes: str

    class Config:
        from_attributes = True


class OperationStartRequest(BaseModel):
    alert_id: int
    strategy: str = "collision avoidance burn"


class OperationOut(BaseModel):
    id: int
    alert_id: int | None
    object_pair: str
    strategy: str
    status: str
    target_satellite: str
    phase: str
    risk_before: float
    risk_after: float | None
    delta_v_total_ms: float | None
    fuel_used_kg: float | None
    fuel_consumption_pct: float | None
    duration_sec: int | None
    new_tca_hours: float | None
    miss_distance_km: float | None
    summary: str
    started_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


class OperationCompleteResponse(BaseModel):
    operation: OperationOut
    outcome_summary: str


class SessionResetResponse(BaseModel):
    message: str
    preserved_operations: int
    preserved_maneuver_events: int


class ClearOperationHistoryResponse(BaseModel):
    message: str
    deleted: int
