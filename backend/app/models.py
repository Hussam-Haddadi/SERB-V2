from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    screenings = relationship("ScreeningRun", back_populates="user")
    launch_assessments = relationship("LaunchAssessment", back_populates="user")


class SpaceObject(Base):
    __tablename__ = "space_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    norad_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    object_type: Mapped[str] = mapped_column(String(40), index=True)
    altitude_km: Mapped[float] = mapped_column(Float, default=550.0)
    inclination_deg: Mapped[float] = mapped_column(Float, default=53.0)


class CollisionAlert(Base):
    __tablename__ = "collision_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    primary_object_id: Mapped[int] = mapped_column(Integer, ForeignKey("space_objects.id"))
    secondary_object_id: Mapped[int] = mapped_column(Integer, ForeignKey("space_objects.id"))
    miss_distance_km: Mapped[float] = mapped_column(Float)
    tca_hours: Mapped[float] = mapped_column(Float)
    risk_score: Mapped[float] = mapped_column(Float)
    impact_summary: Mapped[str] = mapped_column(String(255))
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    primary_object = relationship("SpaceObject", foreign_keys=[primary_object_id])
    secondary_object = relationship("SpaceObject", foreign_keys=[secondary_object_id])


class ScreeningRun(Base):
    __tablename__ = "screening_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    primary_norad_id: Mapped[int] = mapped_column(Integer)
    secondary_count: Mapped[int] = mapped_column(Integer)
    horizon_hours: Mapped[float] = mapped_column(Float)
    threshold_km: Mapped[float] = mapped_column(Float)
    step_sec: Mapped[int] = mapped_column(Integer)
    alerts_generated: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="screenings")


class LaunchAssessment(Base):
    __tablename__ = "launch_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    mission_id: Mapped[str] = mapped_column(String(120))
    vehicle: Mapped[str] = mapped_column(String(120))
    site: Mapped[str] = mapped_column(String(120))
    orbit: Mapped[str] = mapped_column(String(40))
    azimuth_deg: Mapped[float] = mapped_column(Float)
    inclination_deg: Mapped[float] = mapped_column(Float)
    perigee_km: Mapped[float] = mapped_column(Float)
    apogee_km: Mapped[float] = mapped_column(Float)
    debris_density: Mapped[float] = mapped_column(Float)
    wind_kt: Mapped[float] = mapped_column(Float)
    precip: Mapped[str] = mapped_column(String(20))
    lightning_10nm: Mapped[bool] = mapped_column(Boolean, default=False)
    range_conflicts: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    risk_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    report_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="launch_assessments")


class OrbitalObject(Base):
    __tablename__ = "orbital_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    norad_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    object_type: Mapped[str] = mapped_column(String(40), index=True)
    country: Mapped[str] = mapped_column(String(40), default="UNK")
    tle_line1: Mapped[str] = mapped_column(Text)
    tle_line2: Mapped[str] = mapped_column(Text)
    epoch: Mapped[str] = mapped_column(String(80), default="")
    source: Mapped[str] = mapped_column(String(60), default="CelesTrak")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ManeuverEvent(Base):
    __tablename__ = "maneuver_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    norad_id: Mapped[int] = mapped_column(Integer, index=True)
    object_name: Mapped[str] = mapped_column(String(180), index=True)
    delta_v_ms: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(120))
    event_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notes: Mapped[str] = mapped_column(Text, default="")


class ManeuverOperation(Base):
    __tablename__ = "maneuver_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    alert_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("collision_alerts.id"), nullable=True)
    object_pair: Mapped[str] = mapped_column(String(220))
    strategy: Mapped[str] = mapped_column(String(120), default="collision avoidance burn")
    status: Mapped[str] = mapped_column(String(30), default="in_progress")
    target_satellite: Mapped[str] = mapped_column(String(180), default="")
    phase: Mapped[str] = mapped_column(String(180), default="Assessing maneuver capability...")
    risk_before: Mapped[float] = mapped_column(Float)
    risk_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_v_total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    fuel_used_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    fuel_consumption_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_tca_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    miss_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
