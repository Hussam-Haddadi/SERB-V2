from pathlib import Path
from typing import Literal

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

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
