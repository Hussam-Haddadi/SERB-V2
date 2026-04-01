# Serb v2 (Next-Gen)

Production-grade upgrade with:
- Real orbital data ingestion from CelesTrak (`TLE` feed)
- Interactive 3D Earth orbital visualization (`react-globe.gl` + real-time TLE propagation)
- FastAPI backend with maneuver tracking + launch risk reporting APIs
- Separate AI service with expanded explainable risk report outputs
- SQLAlchemy data layer (PostgreSQL/PostGIS-ready, SQLite fallback for local)

## Reference product analysis (serb.surge.sh)

The reference app is a mission-operations dashboard focused on conjunction safety:
- **Dashboard shell**: "Serb Dashboard", panel toggles, object counters by type.
- **Satellite Control**: real-time monitoring posture, network status, catalog size, object statistics.
- **Avoidance Network**: standby/ready state and context text guiding operator action.
- **Screening Parameters**: operator inputs (primary NORAD, secondary count, horizon, threshold, step) and trigger action.
- **Collision Alerts**: risk-ranked conjunction cards with miss distance, TCA, impact summary, urgency labels.
- **Launch Risk AI**: full mission form (vehicle/site/orbit/time window/geometry/weather/conflicts/notes) and a model-driven assessment call-to-action.

## Upgrades implemented

- Real data ingest endpoint:
  - `POST /ingest/celestrak/latest`
- Orbital catalog endpoint:
  - `GET /orbital-objects`
- Maneuver tracking endpoints:
  - `GET /maneuvers`
  - `POST /maneuvers/generate-demo`
- Advanced launch AI report output now includes:
  - Factor contributions
  - Recommendations
  - Prediction curve
  - Danger-zone heatmap matrix
- 3D globe with object categories:
  - Satellites (blue), Debris (red), Rockets (yellow)
- Clear field labels and explanatory UI hints across mission forms

## Architecture

```text
web (React + Vite)
  -> backend (FastAPI REST + JWT + SQLAlchemy)
      -> PostgreSQL
      -> ai-service (FastAPI ML inference)
```

### Backend modules
- `backend/app/main.py`: API routes, startup initialization, integration with AI service
- `backend/app/models.py`: SQLAlchemy models
- `backend/app/security.py`: password hashing + JWT
- `backend/app/seed.py`: starter catalog + alerts (matching reference behavior)

### AI modules
- `ai-service/app/main.py`: training data generation, preprocessing pipeline, model train/load, inference endpoint

### Frontend modules
- `web/src/App.tsx`: complete app shell (auth + dashboard + screening + launch risk + history)
- `web/src/index.css`: responsive dashboard styling

## Setup and run

## 1) Start PostgreSQL

Create DB `serbv2` and ensure credentials match `backend/.env`.

Default expected URL:
`postgresql+psycopg2://postgres:postgres@localhost:5432/serbv2`

## 2) Run AI service

```bash
cd ai-service
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8001
```

## 3) Run backend

```bash
cd backend
copy .env.example .env
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Swagger docs: `http://localhost:8000/docs`

## 4) Run frontend

```bash
cd web
copy .env.example .env
npm install
npm run dev
```

Open: `http://localhost:5173`

## Key API endpoints

- `POST /auth/signup`
- `POST /auth/login`
- `GET /dashboard/stats`
- `GET /alerts`
- `POST /screening/run`
- `POST /launch/assess`
- `GET /history/launch`
- `POST /ingest/celestrak/latest`
- `GET /orbital-objects`
- `GET /maneuvers`
- `POST /maneuvers/generate-demo`

## Future improvements

- Add Alembic migrations + CI migration checks.
- Add Redis caching + async task queue for heavy screening jobs.
- Add WebSocket push for near real-time alert streaming.
- Move from synthetic training to real orbital and weather datasets.
- Add role-based access control and audit logs.
- Split frontend into route modules and reusable feature components.
