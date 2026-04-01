from pathlib import Path
from typing import Literal

import os
from openai import OpenAI

client = OpenAI(api_key=os.environ[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])

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

from pydantic import BaseModel

class ManeuverAdviceRequest(BaseModel):
    risk_score: float
    miss_distance_km: float
    tca_hours: float
    orbit: str | None = None
    fuel_budget_pct: float | None = None

class ManeuverAdviceResponse(BaseModel):
    maneuver_type: str
    expected_risk_after: float
    reason: str

class ManeuverDebriefRequest(BaseModel):
    strategy: str
    risk_before: float
    risk_after: float
    delta_v_total_ms: float
    new_tca_hours: float
    miss_distance_km: float
    fuel_consumption_pct: float

class ManeuverDebriefResponse(BaseModel):
    summary_text: str


from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


from fastapi import HTTPException

@app.post("/ai/maneuver-advice", response_model=ManeuverAdviceResponse)
async def ai_maneuver_advice(body: ManeuverAdviceRequest):
    if not client.api_key:
        raise HTTPException(status_code=500, detail="AI not configured")

    prompt = f"""
You are an orbital safety AI. Suggest ONE maneuver strategy to reduce collision risk.

Inputs:
- Risk score: {body.risk_score} %
- Miss distance: {body.miss_distance_km} km
- Time to closest approach (TCA): {body.tca_hours} hours
- Orbit type: {body.orbit or "unknown"}
- Fuel budget (approx): {body.fuel_budget_pct or "unknown"} %

Respond as compact JSON with keys:
- maneuver_type
- expected_risk_after
- reason
"""

    chat = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "You are an orbital dynamics assistant for collision-avoidance planning."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    import json
    try:
        data = json.loads(chat.choices[0].message.content)
        return ManeuverAdviceResponse(
            maneuver_type=data.get("maneuver_type", "collision_avoidance_burn"),
            expected_risk_after=float(data.get("expected_risk_after", body.risk_score)),
            reason=data.get("reason", "AI-generated recommendation."),
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to parse AI response")


@app.post("/ai/maneuver-debrief", response_model=ManeuverDebriefResponse)
async def ai_maneuver_debrief(body: ManeuverDebriefRequest):
    if not client.api_key:
        raise HTTPException(status_code=500, detail="AI not configured")

    prompt = f"""
You are an orbital safety AI. Write a short debrief (2–3 sentences) explaining the impact of a completed collision-avoidance maneuver.

Data:
- Maneuver strategy: {body.strategy}
- Risk before: {body.risk_before} %
- Risk after: {body.risk_after} %
- Total delta-V: {body.delta_v_total_ms} m/s
- New TCA: +{body.new_tca_hours} hours
- Miss distance: {body.miss_distance_km} km
- Fuel consumption: {body.fuel_consumption_pct} %

Write in clear professional English for mission operators.
"""

    chat = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "You are an orbital safety analyst writing concise maneuver debriefs."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        max_tokens=220,
    )

    text = chat.choices[0].message.content.strip()
    return ManeuverDebriefResponse(summary_text=text)
    
MODEL_PATH = Path("artifacts/launch_risk_model.joblib")


class LaunchRiskInput(BaseModel):
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
    precip: Literal["none", "light", "moderate", "heavy"]
    lightning_10nm: bool
    range_conflicts: str = ""
    notes: str = ""


class LaunchRiskOutput(BaseModel):
    risk_score: float
    confidence: float
    category: str
    explanation: str
    factors: list[dict]
    recommendations: list[str]
    prediction_curve: list[dict]
    danger_heatmap: list[list[float]]


def generate_training_data(size: int = 1000) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    orbit_values = rng.choice(["LEO", "MEO", "GEO", "HEO", "SSO"], size=size)
    precip_values = rng.choice(["none", "light", "moderate", "heavy"], size=size, p=[0.4, 0.3, 0.2, 0.1])
    wind = rng.uniform(0, 35, size=size)
    debris = rng.uniform(0, 100, size=size)
    inclination = rng.uniform(0, 110, size=size)
    apogee = rng.uniform(200, 36000, size=size)
    perigee = np.clip(apogee - rng.uniform(20, 2000, size=size), 150, None)
    lightning = rng.choice([0, 1], size=size, p=[0.85, 0.15])
    azimuth = rng.uniform(40, 140, size=size)

    base_risk = (
        0.45 * debris
        + 0.8 * wind
        + 8.0 * lightning
        + np.where(precip_values == "heavy", 18, np.where(precip_values == "moderate", 10, np.where(precip_values == "light", 4, 0)))
        + np.where(orbit_values == "LEO", 10, np.where(orbit_values == "SSO", 12, np.where(orbit_values == "MEO", 7, 5)))
        + np.maximum(0, (inclination - 85) * 0.4)
        + np.maximum(0, (700 - perigee) * 0.03)
        + rng.normal(0, 4, size=size)
    )
    risk = np.clip(base_risk, 1, 99)
    return pd.DataFrame(
        {
            "orbit": orbit_values,
            "precip": precip_values,
            "azimuth_deg": azimuth,
            "inclination_deg": inclination,
            "perigee_km": perigee,
            "apogee_km": apogee,
            "debris_density": debris,
            "wind_kt": wind,
            "lightning_10nm": lightning,
            "target_risk": risk,
        }
    )


def train_or_load_model() -> Pipeline:
    if MODEL_PATH.exists():
        return joblib.load(MODEL_PATH)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    df = generate_training_data()
    feature_cols = [
        "orbit",
        "precip",
        "azimuth_deg",
        "inclination_deg",
        "perigee_km",
        "apogee_km",
        "debris_density",
        "wind_kt",
        "lightning_10nm",
    ]
    x = df[feature_cols]
    y = df["target_risk"]
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), ["orbit", "precip"]),
            (
                "num",
                StandardScaler(),
                ["azimuth_deg", "inclination_deg", "perigee_km", "apogee_km", "debris_density", "wind_kt", "lightning_10nm"],
            ),
        ]
    )
    model = Pipeline(
        steps=[
            ("preprocess", preprocessor),
            ("regressor", RandomForestRegressor(n_estimators=180, random_state=42, min_samples_leaf=2)),
        ]
    )
    model.fit(x, y)
    joblib.dump(model, MODEL_PATH)
    return model


app = FastAPI(title="Serb v2 AI Service", version="2.0.0")
pipeline = train_or_load_model()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/predict/launch-risk", response_model=LaunchRiskOutput)
def predict_launch_risk(payload: LaunchRiskInput):
    row = pd.DataFrame(
        [
            {
                "orbit": payload.orbit,
                "precip": payload.precip,
                "azimuth_deg": payload.azimuth_deg,
                "inclination_deg": payload.inclination_deg,
                "perigee_km": payload.perigee_km,
                "apogee_km": payload.apogee_km,
                "debris_density": payload.debris_density,
                "wind_kt": payload.wind_kt,
                "lightning_10nm": int(payload.lightning_10nm),
            }
        ]
    )
    prediction = float(np.clip(pipeline.predict(row)[0], 1.0, 99.0))
    confidence = float(np.clip(0.9 - (abs(50 - prediction) / 120.0), 0.55, 0.95))
    category = "LOW" if prediction < 40 else "MEDIUM" if prediction < 70 else "HIGH"
    factors = [
        {"name": "Debris density", "impact": round(min(payload.debris_density / 100.0, 1.0), 2)},
        {"name": "Orbital congestion", "impact": round(min((payload.inclination_deg / 120.0) + (payload.apogee_km / 42000.0), 1.0), 2)},
        {"name": "Weather stress", "impact": round(min((payload.wind_kt / 50.0) + (0.25 if payload.precip in ["moderate", "heavy"] else 0.0), 1.0), 2)},
        {"name": "Lightning proximity", "impact": 0.6 if payload.lightning_10nm else 0.1},
    ]
    factors = sorted(factors, key=lambda x: x["impact"], reverse=True)
    recommendations = [
        "Shift launch window away from local high-congestion epoch (+/- 30 min).",
        "Reduce ascent corridor crossing dense debris shell where possible.",
        "Require stricter weather gate if wind exceeds 18 kt or lightning is true.",
    ]
    prediction_curve = [{"t_minus_min": t, "risk": round(max(1.0, min(99.0, prediction + (np.sin(t / 12.0) * 4.2))), 2)} for t in range(-60, 61, 10)]
    danger_heatmap = [[round(float(np.clip((i * 9 + j * 6 + prediction * 0.22) / 18.0, 0, 10)), 2) for j in range(8)] for i in range(8)]
    explanation = (
        f"Predicted risk is {prediction:.1f} driven mainly by debris density ({payload.debris_density:.1f}), "
        f"wind ({payload.wind_kt:.1f} kt), precipitation ({payload.precip}), and orbit profile ({payload.orbit})."
    )
    return LaunchRiskOutput(
        risk_score=round(prediction, 2),
        confidence=round(confidence, 2),
        category=category,
        explanation=explanation,
        factors=factors,
        recommendations=recommendations,
        prediction_curve=prediction_curve,
        danger_heatmap=danger_heatmap,
    )
