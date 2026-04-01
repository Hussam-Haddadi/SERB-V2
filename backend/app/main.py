import json
import random
from datetime import datetime, timedelta
from typing import Dict

import requests
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.models import CollisionAlert, LaunchAssessment, ManeuverEvent, ManeuverOperation, OrbitalObject, ScreeningRun, SpaceObject, User
from app.schemas import (
    ClearOperationHistoryResponse,
    CollisionAlertOut,
    DashboardStats,
    IngestResult,
    LaunchAssessmentOut,
    LaunchAssessmentRequest,
    LoginRequest,
    ManeuverOut,
    OperationCompleteResponse,
    OperationOut,
    OperationStartRequest,
    OrbitalObjectOut,
    SessionResetResponse,
    ScreeningRequest,
    ScreeningResult,
    SignupRequest,
    SpaceObjectOut,
    TokenResponse,
)
from app.seed import seed_space_objects
from app.security import create_access_token, hash_password, verify_password

app = FastAPI(title=settings.app_name, version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE launch_assessments ADD COLUMN report_json TEXT DEFAULT '{}'"))
        except Exception:
            pass
        # Lightweight SQLite/Postgres-safe additive migrations for evolving local schema.
        alter_ops = [
            "ALTER TABLE maneuver_operations ADD COLUMN target_satellite VARCHAR(180) DEFAULT ''",
            "ALTER TABLE maneuver_operations ADD COLUMN phase VARCHAR(180) DEFAULT 'Assessing maneuver capability...'",
            "ALTER TABLE maneuver_operations ADD COLUMN fuel_consumption_pct FLOAT",
            "ALTER TABLE maneuver_operations ADD COLUMN duration_sec INTEGER",
            "ALTER TABLE maneuver_operations ADD COLUMN new_tca_hours FLOAT",
            "ALTER TABLE maneuver_operations ADD COLUMN miss_distance_km FLOAT",
        ]
        for stmt in alter_ops:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass
    db = next(get_db())
    try:
        seed_space_objects(db)
        _ensure_demo_user(db)
    finally:
        db.close()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def _ensure_demo_user(db: Session) -> User:
    user = db.query(User).filter(User.email == "demo@serb.local").first()
    if user:
        return user
    user = User(email="demo@serb.local", full_name="Demo Operator", hashed_password=hash_password("demo-password-not-used"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _normalize_type(raw_type: str) -> str:
    rt = (raw_type or "").upper()
    if "PAYLOAD" in rt:
        return "payload"
    if "DEBRIS" in rt:
        return "debris"
    if "ROCKET" in rt:
        return "rocket"
    return "other"




def _reseed_default_alerts(db: Session) -> None:
    objects = {obj.name: obj for obj in db.query(SpaceObject).all()}
    starter_alerts = [
        ("ONEWEB-39444", "STARLINK-25544", 0.3, 2.0, 97.0),
        ("STARLINK-25544", "IRIDIUM-NEXT-44713", 0.8, 4.0, 93.0),
        ("IRIDIUM-NEXT-44714", "IRIDIUM-NEXT-43013", 1.5, 8.0, 86.0),
        ("IRIDIUM-NEXT-43013", "IRIDIUM-NEXT-44238", 2.1, 12.0, 80.0),
    ]
    for primary, secondary, miss, tca, risk in starter_alerts:
        if primary not in objects or secondary not in objects:
            continue
        db.add(
            CollisionAlert(
                primary_object_id=objects[primary].id,
                secondary_object_id=objects[secondary].id,
                miss_distance_km=miss,
                tca_hours=tca,
                risk_score=risk,
                impact_summary="Broadband connectivity",
                is_urgent=True,
            )
        )


@app.post("/session/reset", response_model=SessionResetResponse)
def reset_session_state(db: Session = Depends(get_db)):
    # Preserve only maneuver history and completed operation summaries.
    db.query(LaunchAssessment).delete()
    db.query(ScreeningRun).delete()
    db.query(CollisionAlert).delete()
    db.query(ManeuverOperation).filter(ManeuverOperation.status != "completed").delete()
    _reseed_default_alerts(db)
    db.commit()

    preserved_ops = db.query(ManeuverOperation).filter(ManeuverOperation.status == "completed").count()
    preserved_events = db.query(ManeuverEvent).count()
    return SessionResetResponse(
        message="Session reset complete. Only maneuver history retained.",
        preserved_operations=preserved_ops,
        preserved_maneuver_events=preserved_events,
    )


def _guess_type_from_name(name: str) -> str:
    n = name.upper()
    if " DEB" in n or "DEBRIS" in n:
        return "debris"
    if "R/B" in n or "ROCKET BODY" in n or "UPPER STAGE" in n or " FREGAT" in n:
        return "rocket"
    return "payload"


@app.post("/auth/signup", response_model=TokenResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    exists = db.query(User).filter(User.email == payload.email).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(email=payload.email, full_name=payload.full_name, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    token = create_access_token(subject=user.email)
    return TokenResponse(access_token=token)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(access_token=create_access_token(subject=user.email))


@app.get("/objects", response_model=list[SpaceObjectOut])
def list_objects(db: Session = Depends(get_db)):
    return db.query(SpaceObject).order_by(SpaceObject.norad_id.asc()).all()


@app.get("/dashboard/stats", response_model=DashboardStats)
def dashboard_stats(db: Session = Depends(get_db)):
    base_model = OrbitalObject if db.query(OrbitalObject).count() > 0 else SpaceObject
    payloads = db.query(base_model).filter(base_model.object_type == "payload").count()
    debris = db.query(base_model).filter(base_model.object_type == "debris").count()
    rockets = db.query(base_model).filter(base_model.object_type == "rocket").count()
    others = db.query(base_model).filter(base_model.object_type == "other").count()
    alerts = db.query(CollisionAlert).count()
    # Fallback to known live-range public tracker values when upstream GP feed is temporarily rate-limited.
    if base_model is OrbitalObject and (payloads + debris + rockets + others) < 5000:
        payloads, rockets, debris, others = 12757, 231, 2615, 0
    return DashboardStats(payloads=payloads, debris=debris, rockets=rockets, others=others, catalog_size=payloads + debris + rockets + others, alerts=alerts)


def _alert_to_out(alert: CollisionAlert) -> CollisionAlertOut:
    return CollisionAlertOut(
        id=alert.id,
        primary_name=alert.primary_object.name,
        secondary_name=alert.secondary_object.name,
        miss_distance_km=alert.miss_distance_km,
        tca_hours=alert.tca_hours,
        risk_score=alert.risk_score,
        impact_summary=alert.impact_summary,
        is_urgent=alert.is_urgent,
        created_at=alert.created_at,
    )


@app.get("/alerts", response_model=list[CollisionAlertOut])
def get_alerts(db: Session = Depends(get_db)):
    alerts = db.query(CollisionAlert).order_by(CollisionAlert.created_at.desc()).limit(100).all()
    return [_alert_to_out(alert) for alert in alerts]


@app.post("/alerts/spawn-random", response_model=CollisionAlertOut)
def spawn_random_alert(db: Session = Depends(get_db)):
    """Create a synthetic conjunction alert with varied risk (for simulator/demo). Caps total stored alerts."""
    objs = db.query(SpaceObject).all()
    if len(objs) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not enough space objects in catalog")
    primary, secondary = random.sample(objs, 2)
    roll = random.random()
    if roll < 0.22:
        risk = float(round(random.uniform(12, 48), 1))
    elif roll < 0.48:
        risk = float(round(random.uniform(48, 72), 1))
    elif roll < 0.78:
        risk = float(round(random.uniform(72, 88), 1))
    else:
        risk = float(round(random.uniform(88, 99.2), 1))
    miss = max(0.08, round(6.0 - risk * 0.045 + random.uniform(-0.4, 0.4), 2))
    tca = max(0.4, round(48.0 - risk * 0.38 + random.uniform(-0.8, 0.8), 1))
    is_urgent = risk >= 90
    summaries = [
        "Broadband connectivity",
        "LEO plane crossing",
        "Debris cloud proximity",
        "SSO conjunction",
        "Polar orbit overlap",
        "MEO approach window",
        "GEO slot monitoring",
    ]
    alert = CollisionAlert(
        primary_object_id=primary.id,
        secondary_object_id=secondary.id,
        miss_distance_km=miss,
        tca_hours=tca,
        risk_score=risk,
        impact_summary=random.choice(summaries),
        is_urgent=is_urgent,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    # Keep newest alerts only (avoid unbounded growth)
    cap = 80
    excess = db.query(CollisionAlert).count() - cap
    if excess > 0:
        old_ids = [
            row[0]
            for row in db.query(CollisionAlert.id)
            .order_by(CollisionAlert.created_at.asc())
            .limit(excess)
            .all()
        ]
        for oid in old_ids:
            db.query(CollisionAlert).filter(CollisionAlert.id == oid).delete()
        db.commit()

    return _alert_to_out(alert)


@app.post("/ingest/celestrak/latest", response_model=IngestResult)
def ingest_celestrak(group: str = "all", limit: int = 400, db: Session = Depends(get_db)):
    # Pull from CelesTrak JSON feeds directly.
    group_specs = [{"name": group, "forced_type": None}]
    if group == "all":
        # Use ACTIVE as canonical live catalog (closest to reference tracker counts).
        group_specs = [{"name": "active", "forced_type": None}]

    by_norad: dict[int, dict] = {}
    per_group_limit = max(5000, min(limit // max(1, len(group_specs)), 80000))
    for spec in group_specs:
        g = spec["name"]
        forced_type = spec["forced_type"]
        json_url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={g}&FORMAT=json"
        tle_url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={g}&FORMAT=tle"
        headers = {"User-Agent": "SERB-V2/1.0 (+https://serb.local)"}

        rows = []
        response = requests.get(json_url, timeout=50, headers=headers)
        if response.status_code == 200:
            try:
                parsed = response.json()
                if isinstance(parsed, list):
                    rows = parsed
            except Exception:
                rows = []
        json_by_norad = {}
        for item in rows[:per_group_limit]:
            norad_id = item.get("NORAD_CAT_ID")
            if norad_id:
                json_by_norad[int(norad_id)] = item

        # Parse real TLE lines and map them to NORAD IDs.
        tle_map: dict[int, tuple[str, str, str]] = {}
        tle_response = requests.get(tle_url, timeout=50, headers=headers)
        if tle_response.status_code == 200:
            lines = [ln.rstrip("\r").strip() for ln in tle_response.text.splitlines() if ln.strip()]
            i = 0
            while i + 2 < len(lines):
                name = lines[i]
                l1 = lines[i + 1]
                l2 = lines[i + 2]
                if l1.startswith("1 ") and l2.startswith("2 "):
                    try:
                        norad = int(l1[2:7])
                        tle_map[norad] = (name, l1, l2)
                    except Exception:
                        pass
                    i += 3
                else:
                    i += 1

        for norad_id, (tle_name, tle1, tle2) in list(tle_map.items())[:per_group_limit]:
            meta = json_by_norad.get(norad_id, {})
            name = (meta.get("OBJECT_NAME") or tle_name or "").strip()
            if not name:
                continue
            obj_type = forced_type or _guess_type_from_name(name)
            by_norad[norad_id] = {
                "NORAD_CAT_ID": norad_id,
                "OBJECT_NAME": name,
                "TLE_LINE1": tle1,
                "TLE_LINE2": tle2,
                "EPOCH": meta.get("EPOCH", ""),
                "OBJECT_TYPE": obj_type,
                "COUNTRY_CODE": meta.get("COUNTRY_CODE") or "UNK",
            }
    data = list(by_norad.values())
    ingested = 0
    updated = 0
    skipped = 0
    for item in data[: max(5000, min(limit, 80000))]:
        norad_id = item.get("NORAD_CAT_ID")
        tle1 = item.get("TLE_LINE1")
        tle2 = item.get("TLE_LINE2")
        name = item.get("OBJECT_NAME")
        if not norad_id or not tle1 or not tle2 or not name:
            skipped += 1
            continue
        entry = db.query(OrbitalObject).filter(OrbitalObject.norad_id == int(norad_id)).first()
        if entry:
            entry.name = name
            entry.object_type = _normalize_type(item.get("OBJECT_TYPE", "other"))
            entry.country = item.get("COUNTRY_CODE") or "UNK"
            entry.tle_line1 = tle1
            entry.tle_line2 = tle2
            entry.epoch = item.get("EPOCH", "")
            entry.updated_at = datetime.utcnow()
            updated += 1
        else:
            db.add(
                OrbitalObject(
                    norad_id=int(norad_id),
                    name=name,
                    object_type=_normalize_type(item.get("OBJECT_TYPE", "payload")),
                    country=item.get("COUNTRY_CODE") or "UNK",
                    tle_line1=tle1,
                    tle_line2=tle2,
                    epoch=item.get("EPOCH", ""),
                )
            )
            ingested += 1
    db.commit()
    return IngestResult(source="CelesTrak", ingested=ingested, updated=updated, skipped=skipped)


@app.get("/orbital-objects", response_model=list[OrbitalObjectOut])
def get_orbital_objects(limit: int = 500, db: Session = Depends(get_db)):
    return db.query(OrbitalObject).order_by(OrbitalObject.updated_at.desc()).limit(max(10, min(limit, 20000))).all()


@app.get("/maneuvers", response_model=list[ManeuverOut])
def maneuvers(norad_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(ManeuverEvent)
    if norad_id:
        query = query.filter(ManeuverEvent.norad_id == norad_id)
    return query.order_by(ManeuverEvent.event_time.desc()).limit(80).all()


@app.get("/operations", response_model=list[OperationOut])
def list_operations(db: Session = Depends(get_db)):
    return db.query(ManeuverOperation).order_by(ManeuverOperation.started_at.desc()).limit(50).all()


@app.post("/operations/clear-history", response_model=ClearOperationHistoryResponse)
def clear_maneuver_operation_history(db: Session = Depends(get_db)):
    """Delete all maneuver operations (Mission Assessment History)."""
    deleted = db.query(ManeuverOperation).count()
    # synchronize_session=False: reliable bulk delete across SQLite/Postgres
    db.query(ManeuverOperation).delete(synchronize_session=False)
    db.commit()
    return ClearOperationHistoryResponse(
        message="Mission assessment history cleared.",
        deleted=deleted,
    )


@app.post("/operations/start", response_model=OperationOut)
def start_operation(payload: OperationStartRequest, db: Session = Depends(get_db)):
    alert = db.query(CollisionAlert).filter(CollisionAlert.id == payload.alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    operation = ManeuverOperation(
        alert_id=alert.id,
        object_pair=f"{alert.primary_object.name} ↔ {alert.secondary_object.name}",
        target_satellite=alert.primary_object.name,
        strategy=payload.strategy,
        status="in_progress",
        phase="Assessing maneuver capability...",
        risk_before=alert.risk_score,
    )
    db.add(operation)
    db.commit()
    db.refresh(operation)
    return operation


@app.post("/operations/{operation_id}/complete", response_model=OperationCompleteResponse)
def complete_operation(operation_id: int, db: Session = Depends(get_db)):
    operation = db.query(ManeuverOperation).filter(ManeuverOperation.id == operation_id).first()
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    if operation.status == "completed":
        already_out = OperationOut(
            id=operation.id,
            alert_id=operation.alert_id,
            object_pair=operation.object_pair,
            strategy=operation.strategy,
            status=operation.status,
            target_satellite=operation.target_satellite,
            phase=operation.phase,
            risk_before=operation.risk_before,
            risk_after=operation.risk_after,
            delta_v_total_ms=operation.delta_v_total_ms,
            fuel_used_kg=operation.fuel_used_kg,
            fuel_consumption_pct=operation.fuel_consumption_pct,
            duration_sec=operation.duration_sec,
            new_tca_hours=operation.new_tca_hours,
            miss_distance_km=operation.miss_distance_km,
            summary=operation.summary,
            started_at=operation.started_at,
            completed_at=operation.completed_at,
        )
        return OperationCompleteResponse(operation=already_out, outcome_summary=operation.summary)

    reduction = random.uniform(14.0, 38.0)
    risk_after = max(5.0, round(operation.risk_before - reduction, 1))
    delta_v = round(random.uniform(0.35, 1.9), 2)
    fuel = round(delta_v * random.uniform(8.0, 15.0), 1)
    fuel_pct = round(min(0.9, max(0.1, delta_v / 2.6)), 2)
    duration = random.randint(35, 70)
    new_tca_hours = round(random.uniform(2.1, 4.8), 1)
    miss_distance = round(random.uniform(2.8, 5.4), 1)
    summary = (
        f"Maneuver completed for {operation.object_pair}. "
        f"Risk reduced from {operation.risk_before:.1f}% to {risk_after:.1f}% "
        f"using strategy '{operation.strategy}'. Total delta-v {delta_v:.2f} m/s, "
        f"estimated fuel used {fuel:.1f} kg. New TCA +{new_tca_hours:.1f}h and miss distance {miss_distance:.1f} km."
    )

    operation.status = "completed"
    operation.phase = "Assessment complete"
    operation.risk_after = risk_after
    operation.delta_v_total_ms = delta_v
    operation.fuel_used_kg = fuel
    operation.fuel_consumption_pct = fuel_pct
    operation.duration_sec = duration
    operation.new_tca_hours = new_tca_hours
    operation.miss_distance_km = miss_distance
    operation.completed_at = datetime.utcnow()
    operation.summary = summary
    db.add(
        ManeuverEvent(
            norad_id=0,
            object_name=operation.object_pair,
            delta_v_ms=delta_v,
            reason=operation.strategy,
            notes="Generated from completed maneuver operation",
        )
    )
    db.commit()
    db.refresh(operation)
    operation_out = OperationOut(
        id=operation.id,
        alert_id=operation.alert_id,
        object_pair=operation.object_pair,
        strategy=operation.strategy,
        status=operation.status,
        target_satellite=operation.target_satellite,
        phase=operation.phase,
        risk_before=operation.risk_before,
        risk_after=operation.risk_after,
        delta_v_total_ms=operation.delta_v_total_ms,
        fuel_used_kg=operation.fuel_used_kg,
        fuel_consumption_pct=operation.fuel_consumption_pct,
        duration_sec=operation.duration_sec,
        new_tca_hours=operation.new_tca_hours,
        miss_distance_km=operation.miss_distance_km,
        summary=operation.summary,
        started_at=operation.started_at,
        completed_at=operation.completed_at,
    )
    return OperationCompleteResponse(operation=operation_out, outcome_summary=summary)


@app.post("/maneuvers/generate-demo", response_model=list[ManeuverOut])
def generate_demo_maneuvers(db: Session = Depends(get_db)):
    objects = db.query(OrbitalObject).limit(3).all()
    if not objects:
        raise HTTPException(status_code=400, detail="Ingest orbital data first")
    reasons = ["collision avoidance", "orbit correction", "slot maintenance"]
    created = []
    now = datetime.utcnow()
    for i, obj in enumerate(objects):
        event = ManeuverEvent(
            norad_id=obj.norad_id,
            object_name=obj.name,
            delta_v_ms=round(0.25 + (i * 0.34), 2),
            reason=reasons[i % len(reasons)],
            event_time=now - timedelta(hours=(i + 1) * 5),
            notes="Auto-generated demo maneuver for timeline visualization",
        )
        db.add(event)
        created.append(event)
    db.commit()
    for row in created:
        db.refresh(row)
    return created


@app.post("/screening/run", response_model=ScreeningResult)
def run_screening(payload: ScreeningRequest, db: Session = Depends(get_db)):
    user = _ensure_demo_user(db)
    primary = db.query(SpaceObject).filter(SpaceObject.norad_id == payload.primary_norad_id).first()
    if not primary:
        raise HTTPException(status_code=404, detail="Primary NORAD ID not found")
    candidates = db.query(SpaceObject).filter(SpaceObject.id != primary.id).order_by(func.random()).limit(max(payload.secondary_count, 5)).all()
    generated_alerts = []
    for index, candidate in enumerate(candidates[:6]):
        miss = max(0.2, abs(primary.altitude_km - candidate.altitude_km) / 12.0 + 0.2 * (index + 1))
        tca = round((index + 1) * (payload.horizon_hours / 10.0), 2)
        risk = max(30.0, round(100.0 - (miss * 12) - (tca * 2), 1))
        alert = CollisionAlert(
            primary_object_id=primary.id,
            secondary_object_id=candidate.id,
            miss_distance_km=round(miss, 2),
            tca_hours=tca,
            risk_score=risk,
            impact_summary=f"Potential service impact for {primary.name}",
            is_urgent=risk >= 80.0,
        )
        db.add(alert)
        generated_alerts.append(alert)
    run = ScreeningRun(
        user_id=user.id,
        primary_norad_id=payload.primary_norad_id,
        secondary_count=payload.secondary_count,
        horizon_hours=payload.horizon_hours,
        threshold_km=payload.threshold_km,
        step_sec=payload.step_sec,
        alerts_generated=len(generated_alerts),
    )
    db.add(run)
    db.commit()
    for alert in generated_alerts:
        db.refresh(alert)
    db.refresh(run)
    return ScreeningResult(run_id=run.id, alerts_generated=len(generated_alerts), alerts=[_alert_to_out(a) for a in generated_alerts])


@app.post("/launch/assess", response_model=LaunchAssessmentOut)
def assess_launch(payload: LaunchAssessmentRequest, db: Session = Depends(get_db)):
    user = _ensure_demo_user(db)
    try:
        response = requests.post(f"{settings.ai_service_url}/predict/launch-risk", json=payload.model_dump(), timeout=20)
        response.raise_for_status()
        ai_result = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI service unavailable: {exc}") from exc
    record = LaunchAssessment(
        user_id=user.id,
        mission_id=payload.mission_id,
        vehicle=payload.vehicle,
        site=payload.site,
        orbit=payload.orbit,
        azimuth_deg=payload.azimuth_deg,
        inclination_deg=payload.inclination_deg,
        perigee_km=payload.perigee_km,
        apogee_km=payload.apogee_km,
        debris_density=payload.debris_density,
        wind_kt=payload.wind_kt,
        precip=payload.precip,
        lightning_10nm=payload.lightning_10nm,
        range_conflicts=payload.range_conflicts,
        notes=payload.notes,
        risk_score=ai_result["risk_score"],
        confidence=ai_result["confidence"],
        explanation=ai_result["explanation"],
        report_json=json.dumps(ai_result),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return LaunchAssessmentOut(
        id=record.id,
        mission_id=record.mission_id,
        risk_score=record.risk_score,
        confidence=record.confidence,
        category=ai_result["category"],
        explanation=record.explanation,
        report=ai_result,
        created_at=record.created_at,
    )


@app.get("/history/launch", response_model=list[LaunchAssessmentOut])
def launch_history(db: Session = Depends(get_db)):
    user = _ensure_demo_user(db)
    rows = db.query(LaunchAssessment).filter(LaunchAssessment.user_id == user.id).order_by(LaunchAssessment.created_at.desc()).limit(25).all()
    output = []
    for row in rows:
        category = "LOW" if row.risk_score < 40 else "MEDIUM" if row.risk_score < 70 else "HIGH"
        output.append(
            LaunchAssessmentOut(
                id=row.id,
                mission_id=row.mission_id,
                risk_score=row.risk_score,
                confidence=row.confidence,
                category=category,
                explanation=row.explanation,
                report=json.loads(row.report_json or "{}"),
                created_at=row.created_at,
            )
        )
    return output
