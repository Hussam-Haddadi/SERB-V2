import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Globe from "react-globe.gl";
import { getSatelliteInfo } from "tle.js";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import axios from "axios";
import * as THREE from "three";
import serbLogo from "../../serb_logo-removebg-preview.png";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Stats = { payloads: number; debris: number; rockets: number; others: number; catalog_size: number; alerts: number };
type Alert = { id: number; primary_name: string; secondary_name: string; miss_distance_km: number; tca_hours: number; risk_score: number; impact_summary: string; is_urgent: boolean; created_at?: string };
type RiskFilter = "all" | "urgent" | "high" | "medium" | "low";
type OrbitalObject = { norad_id: number; name: string; object_type: "payload" | "debris" | "rocket" | "other"; country: string; tle_line1: string; tle_line2: string; epoch: string };
type LaunchReport = {
  risk_score: number; confidence: number; category: string; explanation: string;
  factors: { name: string; impact: number }[]; recommendations: string[];
  prediction_curve: { t_minus_min: number; risk: number }[]; danger_heatmap: number[][];
};
type LaunchResult = { id: number; mission_id: string; risk_score: number; confidence: number; category: string; explanation: string; created_at: string; report?: LaunchReport };
type GlobeMarker = { lat: number; lng: number; altitude: number; color: string; name: string; norad: number; size: number };
/** 3D text label tied to a green (payload) point — real catalog only (not synthetic swarm). */
type PayloadGlobeLabel = { lat: number; lng: number; altitude: number; text: string; norad: number };

const PAYLOAD_COLOR = "#39ff14";
const MAX_PAYLOAD_NAME_LABELS = 48;
type Operation = {
  id: number; alert_id: number | null; object_pair: string; strategy: string; status: "in_progress" | "completed";
  target_satellite: string; phase: string;
  risk_before: number; risk_after: number | null; delta_v_total_ms: number | null; fuel_used_kg: number | null;
  fuel_consumption_pct: number | null; duration_sec: number | null; new_tca_hours: number | null; miss_distance_km: number | null;
  summary: string; started_at: string; completed_at: string | null;
};

function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [operationHistory, setOperationHistory] = useState<Operation[]>([]);
  const [objects, setObjects] = useState<OrbitalObject[]>([]);
  const [selectedObject, setSelectedObject] = useState<OrbitalObject | null>(null);
  const [markers, setMarkers] = useState<GlobeMarker[]>([]);
  const [payloadLabels, setPayloadLabels] = useState<PayloadGlobeLabel[]>([]);
  const globeWrapRef = useRef<HTMLDivElement | null>(null);
  const [globeSize, setGlobeSize] = useState({ width: 900, height: 520 });
  const [screening, setScreening] = useState({ primary_norad_id: 25544, secondary_count: 150, horizon_hours: 24, threshold_km: 5, step_sec: 60 });
  const [launchForm, setLaunchForm] = useState({
    mission_id: "M-2026-001", vehicle: "Falcon 9", site: "CCSFS SLC-40", orbit: "LEO",
    azimuth_deg: 90, inclination_deg: 53.2, perigee_km: 530, apogee_km: 560, debris_density: 42,
    wind_kt: 12, precip: "light", lightning_10nm: false, range_conflicts: "", notes: "",
  });
  const [launchResult, setLaunchResult] = useState<LaunchResult | null>(null);
  const [scenarioAResult, setScenarioAResult] = useState<LaunchResult | null>(null);
  const [scenarioBResult, setScenarioBResult] = useState<LaunchResult | null>(null);
  const [operationSummary, setOperationSummary] = useState<string>("");
  const [activeOperation, setActiveOperation] = useState<Operation | null>(null);
  const [selectedHistoryOpId, setSelectedHistoryOpId] = useState<number | null>(null);
  const [startingAlertId, setStartingAlertId] = useState<number | null>(null);
  const [startedAlertIds, setStartedAlertIds] = useState<Record<number, boolean>>({});
  const [livePhaseText, setLivePhaseText] = useState<string>("");
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("all");
  const [newAlertBanner, setNewAlertBanner] = useState<string | null>(null);
  const globeRef = useRef<any>(null);
  const motionOffsetRef = useRef<number>(0);
  const [showPanel, setShowPanel] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [lang, setLang] = useState<"en" | "ar">("en");
  const [page, setPage] = useState<"overview" | "operations" | "insights">("overview");
  const initializedRef = useRef(false);
  const sampledObjectsRef = useRef<OrbitalObject[]>([]);
  const spriteTextureRef = useRef<any>(null);
  const spriteMaterialCacheRef = useRef<Record<string, any>>({});

  const client = useMemo(() => axios.create({ baseURL: API_URL }), []);
  const activeOpsCount = useMemo(
    () => operationHistory.filter((op) => op.status === "in_progress").length,
    [operationHistory],
  );
  const criticalAlertsCount = useMemo(
    () => alerts.filter((a) => a.risk_score >= 75).length,
    [alerts],
  );
  const congestionScore = useMemo(() => {
    if (!stats) return 0;
    const base = stats.debris + stats.rockets + stats.payloads;
    if (base === 0) return 0;
    const ratio = Math.min(1, base / 25000);
    return Math.round(ratio * 100);
  }, [stats]);
  const recentActivity = useMemo(() => {
    const items: { label: string; ts: string }[] = [];
    operationHistory.slice(0, 5).forEach((op) => {
      const ts = op.completed_at || op.started_at;
      const label = lang === "ar"
        ? `مناورة بين ${op.object_pair} (${op.risk_before}% → ${op.risk_after ?? 0}%)`
        : `Maneuver for ${op.object_pair} (${op.risk_before}% → ${op.risk_after ?? 0}%)`;
      items.push({ label, ts });
    });
    return items;
  }, [operationHistory, lang]);
  const catalogBreakdown = useMemo(() => {
    if (!stats) return [];
    const rows = [
      { key: "payloads", label: "Satellites (payload)", value: stats.payloads, color: "#38bdf8", bar: "linear-gradient(90deg,#0ea5e9,#38bdf8)" },
      { key: "debris", label: "Debris", value: stats.debris, color: "#fb7185", bar: "linear-gradient(90deg,#e11d48,#fb7185)" },
      { key: "rockets", label: "Rocket bodies", value: stats.rockets, color: "#fbbf24", bar: "linear-gradient(90deg,#d97706,#fbbf24)" },
      { key: "others", label: "Other", value: stats.others, color: "#a78bfa", bar: "linear-gradient(90deg,#7c3aed,#a78bfa)" },
    ];
    const sum = rows.reduce((a, r) => a + r.value, 0);
    return rows.map((r) => ({
      ...r,
      pct: sum === 0 ? 0 : Math.min(100, Math.round((r.value / sum) * 1000) / 10),
    }));
  }, [stats]);

  function getSpriteTexture() {
    if (spriteTextureRef.current) return spriteTextureRef.current;
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      const fallback = new THREE.CanvasTexture(canvas);
      spriteTextureRef.current = fallback;
      return fallback;
    }
    const grad = ctx.createRadialGradient(32, 32, 4, 32, 32, 30);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.4, "rgba(255,255,255,0.95)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 64, 64);
    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    spriteTextureRef.current = texture;
    return texture;
  }

  function getSpriteMaterial(color: string) {
    const cached = spriteMaterialCacheRef.current[color];
    if (cached) return cached;
    const material = new THREE.SpriteMaterial({
      map: getSpriteTexture(),
      color,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    spriteMaterialCacheRef.current[color] = material;
    return material;
  }

  function altitudeFromHeightKm(heightKm: number): number {
    // Exaggerated but ordered visual bands to clearly show near/mid/far shells.
    const h = Math.max(120, Math.min(heightKm, 42000));
    if (h < 1200) return 0.06;   // dense LEO
    if (h < 2000) return 0.1;    // upper LEO
    if (h < 8000) return 0.18;   // MEO low
    if (h < 20000) return 0.28;  // MEO high
    if (h < 36000) return 0.38;  // GEO approach
    return 0.48;                 // GEO/HEO
  }

  function buildPayloadSwarm(angleDeg: number): GlobeMarker[] {
    const nearLayers = [
      { count: 84, altitude: 0.055, inclination: 22, phase: 0 },
      { count: 84, altitude: 0.085, inclination: 36, phase: 48 },
      { count: 84, altitude: 0.115, inclination: 54, phase: 96 },
    ];
    const farLayers = [
      { count: 16, altitude: 0.62, inclination: 18, phase: 18 },
      { count: 16, altitude: 0.69, inclination: 42, phase: 84 },
      { count: 16, altitude: 0.76, inclination: 64, phase: 162 },
    ];
    const layers = [...nearLayers, ...farLayers];
    const payloadMarkers: GlobeMarker[] = [];
    for (const layer of layers) {
      for (let i = 0; i < layer.count; i += 1) {
        const deg = angleDeg + layer.phase + (i * 360) / layer.count;
        const rad = deg * (Math.PI / 180);
        const lat = Math.max(-88, Math.min(88, layer.inclination * Math.sin(rad)));
        const lng = ((((deg % 360) + 360) % 360) - 180);
        payloadMarkers.push({
          lat,
          lng,
          altitude: layer.altitude,
          color: "#39ff14",
          name: "Payload Lane",
          norad: 900000 + payloadMarkers.length,
          size: 0.85,
        });
      }
    }
    return payloadMarkers;
  }

  const loadDashboard = useCallback(async () => {
    const [statsRes, alertsRes, objectsRes, opsRes] = await Promise.all([
      client.get("/dashboard/stats"),
      client.get("/alerts"),
      client.get("/orbital-objects?limit=20000"),
      client.get("/operations"),
    ]);
    setStats(statsRes.data);
    setAlerts(alertsRes.data);
    const completedOps = (opsRes.data || []).filter((op: Operation) => op.status === "completed").slice(0, 15);
    setOperationHistory(completedOps);
    setSelectedHistoryOpId(completedOps[0]?.id ?? null);
    const loadedObjects: OrbitalObject[] = objectsRes.data;
    if (loadedObjects.length < 700) {
      await client.post("/ingest/celestrak/latest?group=all&limit=2500");
      const refill = await client.get("/orbital-objects?limit=20000");
      setObjects(refill.data);
    } else {
      setObjects(loadedObjects);
    }
  }, [client]);

  async function clearMissionHistory() {
    try {
      await client.post("/operations/clear-history", {});
    } catch (e) {
      console.error(e);
      window.alert("Could not reach the API to clear history. Start the backend (port 8000) and try again.");
      return;
    }
    setOperationHistory([]);
    setSelectedHistoryOpId(null);
    setOperationSummary("");
    setActiveOperation(null);
    await loadDashboard();
  }

  async function startOperation(alertId: number) {
    setStartingAlertId(alertId);
    try {
      const started = await client.post("/operations/start", { alert_id: alertId, strategy: "collision avoidance burn" });
      const operationId: number | undefined = started.data?.id;
      if (started.data) {
        setActiveOperation(started.data);
      }
      setOperationSummary("");
      setLivePhaseText("Assessing maneuver capability...");

      await new Promise((resolve) => setTimeout(resolve, 1300));
      setLivePhaseText("Calculating optimal burn vector...");
      await new Promise((resolve) => setTimeout(resolve, 1400));
      setLivePhaseText("Executing autonomous maneuver...");
      await new Promise((resolve) => setTimeout(resolve, 1500));

      if (operationId) {
        const completed = await client.post(`/operations/${operationId}/complete`);
        setOperationSummary(completed.data?.outcome_summary || "Maneuver completed.");
        setActiveOperation(completed.data?.operation || null);
      }
      setLivePhaseText("");
      setStartedAlertIds((prev) => ({ ...prev, [alertId]: true }));
      await loadDashboard();
    } finally {
      setStartingAlertId(null);
    }
  }
  const latestOperation = activeOperation;

  function getRiskLevel(risk: number): { label: string; className: string } {
    if (risk >= 90) return { label: "URGENT", className: "urgent-chip urgent" };
    if (risk >= 75) return { label: "HIGH", className: "urgent-chip high" };
    if (risk >= 55) return { label: "MEDIUM", className: "urgent-chip medium" };
    return { label: "LOW", className: "urgent-chip low" };
  }

  function alertMatchesRiskFilter(risk: number, filter: RiskFilter): boolean {
    if (filter === "all") return true;
    if (filter === "urgent") return risk >= 90;
    if (filter === "high") return risk >= 75 && risk < 90;
    if (filter === "medium") return risk >= 55 && risk < 75;
    return risk < 55;
  }

  function buildAIManeuverExplanation(op: Operation | null, langCode: "en" | "ar"): string {
    if (!op) return "";
    const before = op.risk_before ?? 0;
    const after = op.risk_after ?? 0;
    const dv = op.delta_v_total_ms ?? 0;
    const tca = op.new_tca_hours ?? 0;
    const miss = op.miss_distance_km ?? 0;
    const fuel = op.fuel_consumption_pct ?? 0;
    if (langCode === "ar") {
      return `قام محرك الذكاء الاصطناعي باختيار مناورة من نوع "${op.strategy || "collision avoidance"}" لأن مستوى المخاطر كان ${before}٪ ومسافة الاقتراب ${miss.toFixed(1)} كم مع TCA يساوي +${tca.toFixed(1)} ساعة. النموذج قدّر أن حرقًا بقدر ΔV ≈ ${dv.toFixed(2)} m/s يوفر أفضل موازنة بين خفض المخاطر إلى ${after}٪ والحفاظ على استهلاك الوقود عند ${fuel.toFixed(2)}٪ تقريبًا.`;
    }
    return `The AI engine selected a "${op.strategy || "collision avoidance"}" maneuver because the initial risk was ${before}% with a miss distance of ${miss.toFixed(1)} km and TCA of +${tca.toFixed(1)} h. It estimated that a burn of roughly ΔV ≈ ${dv.toFixed(2)} m/s would best balance reducing risk down to ${after}% while keeping fuel usage around ${fuel.toFixed(2)}%.`;
  }

  const filteredAlerts = useMemo(() => alerts.filter((a) => alertMatchesRiskFilter(a.risk_score, riskFilter)), [alerts, riskFilter]);


  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    (async () => {
      await client.post("/session/reset");
      setStartedAlertIds({});
      setOperationSummary("");
      setActiveOperation(null);
      await loadDashboard();
    })().catch(() => undefined);
  }, [loadDashboard]);

  useEffect(() => {
    const tick = async () => {
      try {
        const res = await client.post<Alert>("/alerts/spawn-random");
        const a = res.data;
        setNewAlertBanner(`New maneuver alert: ${a.primary_name} ↔ ${a.secondary_name} (${Math.round(a.risk_score)}% risk)`);
        window.setTimeout(() => setNewAlertBanner(null), 8000);
        await loadDashboard();
      } catch {
        /* backend offline */
      }
    };
    const id = window.setInterval(tick, 30_000);
    return () => window.clearInterval(id);
  }, [loadDashboard]);

  useEffect(() => {
    const updateSize = () => {
      const el = globeWrapRef.current;
      if (!el) return;
      setGlobeSize({
        width: Math.max(320, Math.floor(el.clientWidth)),
        height: Math.max(360, Math.floor(el.clientHeight)),
      });
    };
    updateSize();
    window.addEventListener("resize", updateSize);
    return () => window.removeEventListener("resize", updateSize);
  }, []);

  useEffect(() => {
    const body = document.body;
    body.classList.remove("theme-dark", "theme-light");
    body.classList.add(theme === "light" ? "theme-light" : "theme-dark");
  }, [theme]);

  useEffect(() => {
    const timer = setTimeout(() => {
      const controls = globeRef.current?.controls?.();
      if (!controls) return;
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.2;
      controls.enableDamping = true;
      controls.dampingFactor = 0.18;
    }, 250);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!objects.length) {
      sampledObjectsRef.current = [];
      return;
    }
    // Keep a stable sampled subset to avoid heavy full-catalog propagation each tick.
    const maxPoints = 2800;
    const sample: OrbitalObject[] = [];
    const payloads = objects.filter((o) => o.object_type === "payload");
    const debris = objects.filter((o) => o.object_type === "debris");
    const rockets = objects.filter((o) => o.object_type === "rocket");
    const others = objects.filter((o) => o.object_type === "other");
    const takeEvenly = (arr: OrbitalObject[], cap: number) => {
      if (!arr.length || cap <= 0) return;
      const step = Math.max(1, Math.floor(arr.length / cap));
      for (let i = 0; i < arr.length && sample.length < maxPoints && cap > 0; i += step) {
        sample.push(arr[i]);
        cap -= 1;
      }
    };
    // Favor payload visibility near Earth while preserving all categories.
    takeEvenly(payloads, 1700);
    takeEvenly(debris, 800);
    takeEvenly(rockets, 220);
    takeEvenly(others, 80);
    sampledObjectsRef.current = sample;
  }, [objects]);

  useEffect(() => {
    if (!sampledObjectsRef.current.length) return;
    const timer = setInterval(() => {
      motionOffsetRef.current += 2600;
      const now = new Date(Date.now() + motionOffsetRef.current);
      const source = sampledObjectsRef.current;
      const nextMarkers: GlobeMarker[] = source.flatMap((obj) => {
        try {
          const sat = getSatelliteInfo([obj.tle_line1, obj.tle_line2], now.getTime());
          const lat = sat.lat;
          const lng = sat.lng;
          const seed = (obj.norad_id % 11) * 0.0022;
          const color = obj.object_type === "payload" ? PAYLOAD_COLOR : obj.object_type === "debris" ? "#ff4040" : obj.object_type === "rocket" ? "#ffd900" : "#ffffff";
          let baseAltitude = altitudeFromHeightKm(sat.height) + seed;
          // Keep some payloads in very far circular lanes for visual realism.
          if (obj.object_type === "payload" && obj.norad_id % 9 === 0) baseAltitude += 0.22;
          if (obj.object_type === "payload" && obj.norad_id % 21 === 0) baseAltitude += 0.3;
          if (obj.object_type === "payload" && obj.norad_id % 4 === 0) baseAltitude = Math.min(baseAltitude, 0.12);
          baseAltitude = Math.min(0.8, baseAltitude);
          return [
            {
              lat,
              lng,
              altitude: baseAltitude,
              color,
              name: obj.name,
              norad: obj.norad_id,
              size: sat.height > 20000 ? 0.68 : 0.82,
            },
          ];
        } catch {
          return [];
        }
      });
      const greenPayloads = nextMarkers.filter((m) => m.color === PAYLOAD_COLOR && m.norad < 900000);
      const stride = Math.max(1, Math.ceil(greenPayloads.length / MAX_PAYLOAD_NAME_LABELS));
      const labelItems: PayloadGlobeLabel[] = [];
      for (let i = 0; i < greenPayloads.length && labelItems.length < MAX_PAYLOAD_NAME_LABELS; i += stride) {
        const m = greenPayloads[i];
        const raw = (m.name || "").trim() || `NORAD ${m.norad}`;
        const text = raw.length > 28 ? `${raw.slice(0, 26)}…` : raw;
        labelItems.push({
          lat: m.lat,
          lng: m.lng,
          altitude: m.altitude + 0.004,
          text,
          norad: m.norad,
        });
      }
      const sharedOrbitAngle = (Date.now() * 0.018) % 360;
      const payloadSwarm = buildPayloadSwarm(sharedOrbitAngle);
      setMarkers([...nextMarkers, ...payloadSwarm]);
      setPayloadLabels(labelItems);
    }, 900);
    return () => clearInterval(timer);
  }, [objects]);

  return (
    <div className={`wrap ${showPanel ? "" : "globe-focus"} ${theme === "light" ? "theme-light" : "theme-dark"} ${lang === "ar" ? "lang-ar" : "lang-en"}`}>
      {newAlertBanner && (
        <div className="alert-toast-banner" role="status">
          <span className="alert-toast-pulse" />
          {newAlertBanner}
          <button type="button" className="alert-toast-dismiss" onClick={() => setNewAlertBanner(null)} aria-label="Dismiss">×</button>
        </div>
      )}
      <header>
        <h1 className="brand-mark">
          <img
            src={serbLogo}
            alt={lang === "ar" ? "شعار سيرب" : "Serb logo"}
          />
        </h1>
        <div className="header-actions">
          <div className="view-toggle" role="tablist" aria-label="View">
            <button
              type="button"
              className={`view-tab ${page === "overview" ? "active" : ""}`}
              onClick={() => setPage("overview")}
              role="tab"
              aria-selected={page === "overview"}
            >
              {lang === "ar" ? "نظرة عامة" : "Overview"}
            </button>
            <button
              type="button"
              className={`view-tab ${page === "operations" ? "active" : ""}`}
              onClick={() => setPage("operations")}
              role="tab"
              aria-selected={page === "operations"}
            >
              {lang === "ar" ? "العمليات" : "Operations"}
            </button>
            <button
              type="button"
              className={`view-tab ${page === "insights" ? "active" : ""}`}
              onClick={() => setPage("insights")}
              role="tab"
              aria-selected={page === "insights"}
            >
              {lang === "ar" ? "التحليلات" : "Insights"}
            </button>
          </div>
          <button
            type="button"
            className="theme-toggle"
            onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
            aria-label={theme === "dark"
              ? (lang === "ar" ? "التبديل إلى الوضع النهاري" : "Switch to day mode")
              : (lang === "ar" ? "التبديل إلى الوضع الليلي" : "Switch to night mode")}
          >
            {theme === "dark" ? "☀️" : "🌙"}
          </button>
          <select
            className="lang-toggle"
            value={lang}
            onChange={(e) => setLang(e.target.value as "en" | "ar")}
          >
            <option value="en">English</option>
            <option value="ar">العربية</option>
          </select>
        </div>
      </header>
      <section className="space-now-bar">
        <div className="space-pill danger">
          <span className="pill-label">
            {lang === "ar" ? "مخاطر اصطدام نشطة" : "Active collision risks"}
          </span>
          <span className="pill-value">{criticalAlertsCount}</span>
        </div>
        <div className="space-pill neutral">
          <span className="pill-label">
            {lang === "ar" ? "مناورات جارية" : "Active maneuvers"}
          </span>
          <span className="pill-value">{activeOpsCount}</span>
        </div>
        <div className="space-pill congestion">
          <span className="pill-label">
            {lang === "ar" ? "ازدحام المدارات" : "Orbital congestion"}
          </span>
          <div className="pill-meter">
            <div className="pill-meter-fill" style={{ width: `${congestionScore}%` }} />
          </div>
          <span className="pill-score">{congestionScore}%</span>
        </div>
      </section>
      {page === "overview" && showPanel && (
        <section className="grid4">
          <Card
            title={lang === "ar" ? "الأقمار الصناعية" : "Satellites"}
            value={stats?.payloads ?? 0}
            icon="🛰️"
            subtitle={lang === "ar" ? "أجسام نشطة يتم تتبعها" : "Active tracked objects"}
          />
          <Card
            title={lang === "ar" ? "الحطام" : "Debris"}
            value={stats?.debris ?? 0}
            icon="☄️"
            subtitle={lang === "ar" ? "شظايا وخردة مدارية" : "Orbital debris & fragments"}
          />
          <Card
            title={lang === "ar" ? "هياكل الصواريخ" : "Rockets"}
            value={stats?.rockets ?? 0}
            icon="🚀"
            subtitle={lang === "ar" ? "مراحل صاروخية في المدار" : "Rocket stages in orbit"}
          />
          <Card
            title={lang === "ar" ? "حجم الكتالوج" : "Catalog Size"}
            value={stats?.catalog_size ?? 0}
            icon="📚"
            subtitle={lang === "ar" ? "إجمالي الأجسام المسجَّلة" : "Total cataloged objects"}
          />
        </section>
      )}
      <section className="grid-main">
        <div className="panel">
          <div className="globe-overlay">
            <div className="legend">
              <h3>{lang === "ar" ? "متتبع الأقمار الصناعية" : "Satellite Tracker"}</h3>
              <p><span className="dot payload" />{lang === "ar" ? "أقمار صناعية" : "Payload"}: {stats?.payloads ?? 0}</p>
              <p><span className="dot rocket" />{lang === "ar" ? "صواريخ" : "Rocket"}: {stats?.rockets ?? 0}</p>
              <p><span className="dot debris" />{lang === "ar" ? "حطام" : "Debris"}: {stats?.debris ?? 0}</p>
              <p><span className="dot other" />{lang === "ar" ? "أخرى" : "Other"}: {stats?.others ?? 0}</p>
              <p className="legend-note">
                {lang === "ar"
                  ? `النقاط الخضراء: حتى ${MAX_PAYLOAD_NAME_LABELS} اسم قمر صناعي (عينات).`
                  : `Green dots: up to ${MAX_PAYLOAD_NAME_LABELS} satellite names shown (sample).`}
              </p>
            </div>
            <button className="panel-toggle" onClick={() => setShowPanel((v) => !v)}>
              {showPanel ? "Hide Panel" : "Show Panel"}
            </button>
          </div>
          <div ref={globeWrapRef} className="globe-shell">
            <Globe
              ref={globeRef}
              width={globeSize.width}
              height={globeSize.height}
              globeImageUrl="//unpkg.com/three-globe/example/img/earth-blue-marble.jpg"
              bumpImageUrl="//unpkg.com/three-globe/example/img/earth-topology.png"
              backgroundImageUrl="//unpkg.com/three-globe/example/img/night-sky.png"
              backgroundColor="#020617"
              showAtmosphere={true}
              atmosphereColor="#1d4ed8"
              atmosphereAltitude={0.12}
              showGraticules={false}
              labelsData={payloadLabels}
              labelLat="lat"
              labelLng="lng"
              labelAltitude="altitude"
              labelText="text"
              labelColor={() => "#b6ffc9"}
              labelSize={0.32}
              labelResolution={2}
              labelIncludeDot={false}
              labelsTransitionDuration={350}
              objectsData={markers}
              objectLat="lat"
              objectLng="lng"
              objectAltitude="altitude"
              objectThreeObject={(d: object) => {
                const m = d as GlobeMarker;
                const sprite = new THREE.Sprite(getSpriteMaterial(m.color));
                sprite.scale.set(m.size, m.size, 1);
                return sprite;
              }}
              animateIn={false}
              onGlobeReady={() => {
                const controls = globeRef.current?.controls?.();
                if (!controls) return;
                controls.autoRotate = true;
                controls.autoRotateSpeed = 0.2;
                controls.enableDamping = true;
                controls.dampingFactor = 0.18;
              }}
              onObjectClick={(p: unknown) => {
                const point = p as GlobeMarker;
                setSelectedObject(objects.find((o) => o.norad_id === point.norad) || null);
              }}
              onLabelClick={(label: unknown) => {
                const L = label as PayloadGlobeLabel;
                setSelectedObject(objects.find((o) => o.norad_id === L.norad) || null);
              }}
            />
          </div>
          {selectedObject && <p>Selected: <strong>{selectedObject.name}</strong> (NORAD {selectedObject.norad_id}) / {selectedObject.object_type.toUpperCase()} / {selectedObject.country}</p>}
        </div>
        {showPanel && (
          <div className="panel stats-catalog-panel">
              <div className="stats-catalog-head">
              <div>
                <h3>{lang === "ar" ? "تفصيل الكتالوج" : "Catalog breakdown"}</h3>
                <p className="sub">
                  {lang === "ar"
                    ? "الأعداد حسب نوع الجسم — نفس ألوان دليل الكرة الأرضية."
                    : "Counts by object class — same colors as the globe legend."}
                </p>
              </div>
              <div className="stats-catalog-total">
                <span className="stats-catalog-total-label">
                  {lang === "ar" ? "إجمالي الأجسام المتتبَّعة" : "Tracked total"}
                </span>
                <strong className="stats-catalog-total-value">{stats?.catalog_size?.toLocaleString() ?? "—"}</strong>
              </div>
            </div>
            {stats && catalogBreakdown.length > 0 && (
              <>
                <div className="stats-composition-strip" aria-hidden>
                  {catalogBreakdown.some((r) => r.value > 0) ? (
                    catalogBreakdown.map((row) => (
                      <div
                        key={row.key}
                        className="stats-composition-seg"
                        style={{ flex: Math.max(row.value, 0.0001), background: row.bar }}
                        title={`${row.label}: ${row.value}`}
                      />
                    ))
                  ) : (
                    <div className="stats-composition-empty" />
                  )}
                </div>
                <ul className="stats-breakdown-list">
                  {catalogBreakdown.map((row) => (
                    <li key={row.key} className="stats-breakdown-row">
                      <span className="stats-dot" style={{ background: row.color, boxShadow: `0 0 12px ${row.color}55` }} />
                      <div className="stats-breakdown-main">
                        <span className="stats-breakdown-label">
                          {lang === "ar"
                            ? row.key === "payloads"
                              ? "الأقمار الصناعية"
                              : row.key === "debris"
                              ? "الحطام"
                              : row.key === "rockets"
                              ? "هياكل الصواريخ"
                              : "أجسام أخرى"
                            : row.label}
                        </span>
                        <div className="stats-breakdown-bar-wrap">
                          <div className="stats-breakdown-bar" style={{ width: `${row.pct}%`, background: row.bar }} />
                        </div>
                      </div>
                      <div className="stats-breakdown-num">
                        <strong>{row.value.toLocaleString()}</strong>
                        <span className="stats-breakdown-pct">{row.pct}%</span>
                      </div>
                    </li>
                  ))}
                </ul>
                <p className="stats-footnote">
                  {lang === "ar"
                    ? "النِّسَب مئوية بالنسبة لمجموع الفئات الأربع الموضَّحة أعلاه."
                    : "Percentages are relative to the sum of the four categories shown above."}
                </p>
              </>
            )}
          </div>
        )}
      </section>
      {page === "operations" && showPanel && (
      <section className="grid2">
        <div className="dashboard-col">
        <div className="panel">
          <div className="alerts-section-head">
              <div className="alerts-section-title">
              <h3>{lang === "ar" ? "تنبيهات الاصطدام" : "Collision Alerts"}</h3>
              <p className="sub">
                {lang === "ar"
                  ? "أحداث تقارب المدارات — تنبيهات جديدة من المحاكي كل 30 ثانية بمستويات مخاطر مختلفة."
                  : "Conjunction events — new simulator alerts every 30s with varied risk."}
              </p>
            </div>
            <div className="risk-filter-wrap">
              <label className="risk-filter-label" htmlFor="risk-filter">
                {lang === "ar" ? "تصفية حسب مستوى الخطر" : "Filter by risk"}
              </label>
              <select
                id="risk-filter"
                className="risk-filter-select"
                value={riskFilter}
                onChange={(e) => setRiskFilter(e.target.value as RiskFilter)}
              >
                <option value="all">{lang === "ar" ? "كل المستويات" : "All levels"}</option>
                <option value="urgent">{lang === "ar" ? "حرِج (≥90%)" : "Urgent (≥90%)"}</option>
                <option value="high">{lang === "ar" ? "عالٍ (75–89%)" : "High (75–89%)"}</option>
                <option value="medium">{lang === "ar" ? "متوسط (55–74%)" : "Medium (55–74%)"}</option>
                <option value="low">{lang === "ar" ? "منخفض (&lt;55%)" : "Low (&lt;55%)"}</option>
              </select>
            </div>
          </div>
          <div className="alerts-stack">
            {filteredAlerts.length === 0 ? (
              <p className="sub">
                {lang === "ar"
                  ? "لا توجد تنبيهات تطابق هذه التصفية. جرّب اختيار \"كل المستويات\" أو انتظر تنبيهات جديدة."
                  : 'No alerts match this filter. Try "All levels" or wait for new events.'}
              </p>
            ) : (
              filteredAlerts.slice(0, 8).map((a) => {
                const level = getRiskLevel(a.risk_score);
                const badgeClass = level.label === "URGENT" ? "risk-badge" : level.label === "HIGH" ? "risk-badge risk-badge-high" : level.label === "MEDIUM" ? "risk-badge risk-badge-medium" : "risk-badge risk-badge-low";
                return (
                  <div className="alert-card" key={a.id}>
                    <div className="alert-main">
                      <h4>{a.primary_name} ↔ {a.secondary_name}</h4>
                      <p>
                        {lang === "ar"
                          ? `مسافة الاقتراب: ${a.miss_distance_km} كم • TCA: ${a.tca_hours} ساعة • الأثر: ${a.impact_summary}`
                          : `Miss: ${a.miss_distance_km} km • TCA: ${a.tca_hours}h • Impact: ${a.impact_summary}`}
                      </p>
                      <span className={badgeClass}>
                        {lang === "ar" ? `مخاطر ${Math.round(a.risk_score)}%` : `${Math.round(a.risk_score)}% Risk`}
                      </span>
                    </div>
                    <div className="alert-actions">
                      <span className={level.className}>{level.label}</span>
                      <button
                        disabled={startingAlertId === a.id || startedAlertIds[a.id]}
                        onClick={() => startOperation(a.id)}
                      >
                        {startingAlertId === a.id
                          ? lang === "ar"
                            ? "جاري البدء..."
                            : "Starting..."
                          : startedAlertIds[a.id]
                          ? lang === "ar"
                            ? "تم البدء ✓"
                            : "Started ✓"
                          : lang === "ar"
                          ? "بدء المناورة"
                          : "Start Maneuver"}
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
          <h4 style={{ marginTop: 16 }}>
            {lang === "ar" ? "نظرة عامة على المخاطر" : "Risk overview"}
          </h4>
          {filteredAlerts.length > 0 ? (
            <ResponsiveContainer width="100%" height={170}><BarChart data={filteredAlerts.slice(0, 12)}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="id" /><YAxis /><Tooltip /><Bar dataKey="risk_score" fill="#ef4444" /></BarChart></ResponsiveContainer>
          ) : (
            <p className="sub" style={{ marginTop: 8 }}>
              {lang === "ar" ? "لا توجد بيانات رسم بياني للتصفية الحالية." : "No chart data for current filter."}
            </p>
          )}
          <h4 style={{ marginTop: 20 }}>
            {lang === "ar" ? "معاملات الفحص" : "Screening Parameters"}
          </h4>
          <label title="Unique NORAD identifier for the primary tracked object">
            {lang === "ar" ? "معرّف NORAD الأساسي" : "Primary NORAD ID"}
          </label>
          <input type="number" value={screening.primary_norad_id} onChange={(e) => setScreening({ ...screening, primary_norad_id: Number(e.target.value) })} />
          <label title="How many nearby secondary objects to evaluate">
            {lang === "ar" ? "عدد الأجسام الثانوية" : "Secondary Object Count"}
          </label>
          <input type="number" value={screening.secondary_count} onChange={(e) => setScreening({ ...screening, secondary_count: Number(e.target.value) })} />
          <label title="Prediction horizon in hours for conjunction analysis">
            {lang === "ar" ? "أفق الفحص (ساعات)" : "Screening Horizon (hours)"}
          </label>
          <input type="number" value={screening.horizon_hours} onChange={(e) => setScreening({ ...screening, horizon_hours: Number(e.target.value) })} />
          <button onClick={async () => { await client.post("/screening/run", screening); await loadDashboard(); }}>
            {lang === "ar" ? "تشغيل الفحص" : "Run Screening"}
          </button>
        </div>
        <div className="panel avoidance-panel">
          <h3>{lang === "ar" ? "🛰️ شبكة تجنّب الاصطدام" : "🛰️ Avoidance Network"}</h3>
          <p className="sub">
            {lang === "ar"
              ? "محرك الذكاء الاصطناعي يقترح نوع المناورة المثالي لكل تنبيه (مثل حرق Prograde أو تغيير الميل)، ويوازن بين خفض المخاطر واستهلاك الوقود قبل تنفيذ الأمر."
              : "The AI engine recommends the optimal maneuver type for each alert (e.g., prograde burn or plane change), balancing risk reduction against fuel use before the command is executed."}
          </p>
          <div className="network-status">
            <span className="network-chip"><span className="red-dot" /> {lang === "ar" ? "فعّال" : "ACTIVE"}</span>
          </div>
          <div className="network-box">
            <p className="network-label">{lang === "ar" ? "القمر الصناعي المستهدف" : "Target Satellite"}</p>
            <h4 className="network-target">
              🎯 {latestOperation?.target_satellite || (lang === "ar" ? "في انتظار مناورة نشطة..." : "Awaiting active maneuver...")}
            </h4>
            <p className="network-label">{lang === "ar" ? "المرحلة الحالية" : "Current Phase"}</p>
            {latestOperation?.status === "completed" ? (
              <h4 className="phase-ok">{lang === "ar" ? "✅ التقييم مكتمل" : "✅ Assessment complete"}</h4>
            ) : latestOperation ? (
              <h4 className="phase-running">
                🔄 {livePhaseText || latestOperation.phase || (lang === "ar" ? "تقييم قدرة المناورة..." : "Assessing maneuver capability...")}
              </h4>
            ) : (
              <h4 className="phase-running">
                🔄 {lang === "ar" ? "في انتظار تفعيل المناورة..." : "Awaiting maneuver activation..."}
              </h4>
            )}
            {latestOperation?.status === "completed" && (
              <div className="result-box">
                <h4>{lang === "ar" ? "نتيجة التقييم" : "Assessment Result"}</h4>
                <p>{lang === "ar" ? "✅ المناورة ناجحة" : "✅ MANEUVER SUCCESSFUL"}</p>
                <ul>
                  <li>{lang === "ar" ? "دلتا-V" : "Delta-V"}: {latestOperation.delta_v_total_ms ?? 0} m/s</li>
                  <li>{lang === "ar" ? "مدة المناورة" : "Maneuver duration"}: {latestOperation.duration_sec ?? 0} s</li>
                  <li>{lang === "ar" ? "زمن الاقتراب الجديد (TCA)" : "New TCA"}: +{latestOperation.new_tca_hours ?? 0} h</li>
                  <li>{lang === "ar" ? "مسافة الاقتراب" : "Miss distance"}: {latestOperation.miss_distance_km ?? 0} km</li>
                  <li>{lang === "ar" ? "استهلاك الوقود" : "Fuel consumption"}: {latestOperation.fuel_consumption_pct ?? 0}%</li>
          </ul>
                <p>{lang === "ar" ? "جميع الأنظمة ضمن النطاق. تم تحييد التهديد." : "All systems nominal. Threat neutralized."}</p>
                <div className="ai-explainer">
                  <strong>{lang === "ar" ? "دور الذكاء الاصطناعي في هذه المناورة:" : "AI role in this maneuver:"}</strong>
                  <p>
                    {buildAIManeuverExplanation(latestOperation, lang)}
                  </p>
                </div>
              </div>
            )}
          </div>
          {operationSummary && (
            <div className="summary-box">
              <strong>{lang === "ar" ? "ملخص العملية:" : "Operation Summary:"}</strong>
              <p>{operationSummary}</p>
            </div>
          )}
        </div>
        </div>
        <div className="dashboard-col">
        <div className="panel launch-risk-panel">
          <h3>{lang === "ar" ? "تقرير ذكاء اصطناعي متقدم لمخاطر الإطلاق" : "Advanced Launch Risk AI Report"}</h3>
          <label title="Unique identifier for the launch mission">
            {lang === "ar" ? "معرّف المهمة" : "Mission ID"}
          </label>
          <input value={launchForm.mission_id} onChange={(e) => setLaunchForm({ ...launchForm, mission_id: e.target.value })} />
          <label title="Launch vehicle used for this mission">
            {lang === "ar" ? "نوع الصاروخ / المركبة" : "Rocket Type / Vehicle"}
          </label>
          <input value={launchForm.vehicle} onChange={(e) => setLaunchForm({ ...launchForm, vehicle: e.target.value })} />
          <label title="Target orbit class: LEO (low), MEO (medium), GEO (geostationary), HEO (highly elliptical), SSO (sun-synchronous)">
            {lang === "ar" ? "نوع المدار" : "Orbit Type"}
          </label>
          <select value={launchForm.orbit} onChange={(e) => setLaunchForm({ ...launchForm, orbit: e.target.value })}><option>LEO</option><option>MEO</option><option>GEO</option><option>HEO</option><option>SSO</option></select>
          <label title="Estimated local debris concentration score">
            {lang === "ar" ? "كثافة الحطام" : "Debris Density"}
          </label>
          <input type="number" value={launchForm.debris_density} onChange={(e) => setLaunchForm({ ...launchForm, debris_density: Number(e.target.value) })} />
          <label title="Forecast wind speed at launch site in knots">
            {lang === "ar" ? "سرعة الرياح (عقدة)" : "Wind Speed (kt)"}
          </label>
          <input type="number" value={launchForm.wind_kt} onChange={(e) => setLaunchForm({ ...launchForm, wind_kt: Number(e.target.value) })} />
          <label>{lang === "ar" ? "مستوى الهطول" : "Precipitation Level"}</label>
          <select value={launchForm.precip} onChange={(e) => setLaunchForm({ ...launchForm, precip: e.target.value })}>
            <option value="none">{lang === "ar" ? "لا يوجد" : "none"}</option>
            <option value="light">{lang === "ar" ? "خفيف" : "light"}</option>
            <option value="moderate">{lang === "ar" ? "متوسط" : "moderate"}</option>
            <option value="heavy">{lang === "ar" ? "غزير" : "heavy"}</option>
          </select>
          <button onClick={async () => { const res = await client.post("/launch/assess", launchForm); setLaunchResult(res.data); await loadDashboard(); }}>
            {lang === "ar" ? "تقييم مخاطر الإطلاق" : "Assess launch risk"}
          </button>
          {launchResult && (
            <p className="launch-risk-summary">
              <strong>{launchResult.category}</strong>{" "}
              {lang === "ar"
                ? `مخاطر: ${launchResult.risk_score}% (موثوقية ${Math.round(launchResult.confidence * 100)}%)`
                : `risk: ${launchResult.risk_score}% (confidence ${Math.round(launchResult.confidence * 100)}%)`}
            </p>
          )}
          {launchResult?.report?.factors && (
            <>
              <h4>{lang === "ar" ? "عوامل الخطر" : "Risk Factors"}</h4>
              <ul className="launch-risk-list">{launchResult.report.factors.map((f) => <li key={f.name}>{f.name}: {Math.round(f.impact * 100)}%</li>)}</ul>
              <h4>{lang === "ar" ? "منحنى التنبؤ" : "Prediction Curve"}</h4>
              <div className="launch-risk-chart">
                <ResponsiveContainer width="100%" height={150}><AreaChart data={launchResult.report.prediction_curve}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="t_minus_min" /><YAxis /><Tooltip /><Area type="monotone" dataKey="risk" stroke="#f97316" fill="#f97316" /></AreaChart></ResponsiveContainer>
              </div>
              <h4>{lang === "ar" ? "التوصيات" : "Recommendations"}</h4>
              <ul className="launch-risk-list">{launchResult.report.recommendations.map((r) => <li key={r}>{r}</li>)}</ul>
            </>
          )}
        </div>
        <div className="panel launch-compare-panel">
          <h3>{lang === "ar" ? "مقارنة سيناريوهات الإطلاق" : "Launch scenarios compare"}</h3>
          <p className="sub">
            {lang === "ar"
              ? "قيّم سيناريوهين مختلفين للإطلاق وقارن المخاطر والموثوقية."
              : "Evaluate two alternative launch scenarios and compare risk and confidence."}
          </p>
          <div className="launch-compare-grid">
            <div className="launch-scenario">
              <h4>{lang === "ar" ? "السيناريو A" : "Scenario A"}</h4>
              <button
                type="button"
                onClick={async () => {
                  const res = await client.post("/launch/assess", launchForm);
                  setScenarioAResult(res.data);
                }}
              >
                {lang === "ar" ? "استخدام القيم الحالية" : "Use current form"}
              </button>
              {scenarioAResult && (
                <div className="launch-scenario-summary">
                  <p>
                    <strong>{scenarioAResult.category}</strong>{" "}
                    {lang === "ar"
                      ? `مخاطر ${scenarioAResult.risk_score}% • موثوقية ${Math.round(scenarioAResult.confidence * 100)}%`
                      : `risk ${scenarioAResult.risk_score}% • confidence ${Math.round(scenarioAResult.confidence * 100)}%`}
                  </p>
                </div>
              )}
            </div>
            <div className="launch-scenario">
              <h4>{lang === "ar" ? "السيناريو B" : "Scenario B"}</h4>
              <button
                type="button"
                onClick={async () => {
                  const tweaked = { ...launchForm, debris_density: launchForm.debris_density + 10 };
                  const res = await client.post("/launch/assess", tweaked);
                  setScenarioBResult(res.data);
                }}
              >
                {lang === "ar" ? "محاكاة ازدحام أعلى" : "Simulate higher debris"}
              </button>
              {scenarioBResult && (
                <div className="launch-scenario-summary">
                  <p>
                    <strong>{scenarioBResult.category}</strong>{" "}
                    {lang === "ar"
                      ? `مخاطر ${scenarioBResult.risk_score}% • موثوقية ${Math.round(scenarioBResult.confidence * 100)}%`
                      : `risk ${scenarioBResult.risk_score}% • confidence ${Math.round(scenarioBResult.confidence * 100)}%`}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="panel mission-history-panel">
          <div className="history-header">
            <h3>{lang === "ar" ? "سجل تقييم المهام" : "Mission Assessment History"}</h3>
            <button
              type="button"
              className="history-clear-btn"
              disabled={operationHistory.length === 0}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                void clearMissionHistory();
              }}
            >
              {lang === "ar" ? "مسح السجل" : "Clear history"}
            </button>
          </div>
          {operationHistory.length ? (
            <div className="history-list">
              {operationHistory.map((op) => {
                const isOpen = selectedHistoryOpId === op.id;
                return (
                  <button
                    key={op.id}
                    className={`history-item ${isOpen ? "open" : ""}`}
                    onClick={() => setSelectedHistoryOpId((prev) => (prev === op.id ? null : op.id))}
                  >
                    <div className="history-title">
                      <div>
                        <strong>{op.object_pair}</strong>
                        <p>{new Date(op.completed_at || op.started_at).toLocaleString()}</p>
                      </div>
                      <span className="history-dv">{op.delta_v_total_ms ?? 0} m/s</span>
                    </div>
                    {isOpen && (
                      <div className="history-details">
                        <p>
                          <strong>{lang === "ar" ? "الملخص:" : "Summary:"}</strong>{" "}
                          {op.summary || (lang === "ar" ? "تمت المناورة بنجاح." : "Maneuver completed successfully.")}
                        </p>
                        <div className="history-metrics">
                          <span>
                            {lang === "ar" ? "المخاطر" : "Risk"}: {op.risk_before}% {"->"} {op.risk_after ?? 0}%
                          </span>
                          <span>
                            {lang === "ar" ? "TCA" : "TCA"}: +{op.new_tca_hours ?? 0}h
                          </span>
                          <span>
                            {lang === "ar" ? "مسافة الاقتراب" : "Miss"}: {op.miss_distance_km ?? 0} km
                          </span>
                          <span>
                            {lang === "ar" ? "الوقود" : "Fuel"}: {op.fuel_consumption_pct ?? 0}%
                          </span>
                        </div>
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="sub">
              {lang === "ar"
                ? "لا يوجد سجل لمناورات مكتملة حتى الآن. ابدأ مناورة من قسم تنبيهات الاصطدام."
                : "No completed maneuver history yet. Start a maneuver from Collision Alerts."}
            </p>
          )}
        </div>
        </div>
      </section>
      )}
      {page === "insights" && (
        <>
          <section className="panel constellation-panel">
            <h3>{lang === "ar" ? "صحة الكوكبة" : "Constellation health"}</h3>
            <p className="sub">
              {lang === "ar"
                ? "لمحة عن حالة الأقمار الصناعية والحطام من منظور السلامة."
                : "Snapshot of satellites and debris from a safety perspective."}
            </p>
            <div className="constellation-grid">
              <div className="constellation-card">
                <h4>{lang === "ar" ? "الأقمار النشطة" : "Active satellites"}</h4>
                <p className="constellation-num">{stats?.payloads?.toLocaleString() ?? "—"}</p>
                <p className="sub">
                  {lang === "ar"
                    ? "أقمار صناعية متتبَّعة حالياً في المدار."
                    : "Tracked payloads currently in orbit."}
                </p>
              </div>
              <div className="constellation-card">
                <h4>{lang === "ar" ? "ضغط الحطام" : "Debris pressure"}</h4>
                <p className="constellation-num">{stats?.debris?.toLocaleString() ?? "—"}</p>
                <p className="sub">
                  {lang === "ar"
                    ? "كلما زاد الرقم زادت احتمالية الاصطدامات."
                    : "Higher counts indicate a denser collision environment."}
                </p>
              </div>
              <div className="constellation-card">
                <h4>{lang === "ar" ? "مؤشر ازدحام المدارات" : "Orbital congestion index"}</h4>
                <div className="pill-meter">
                  <div className="pill-meter-fill" style={{ width: `${congestionScore}%` }} />
                </div>
                <p className="constellation-score">{congestionScore}%</p>
                <p className="sub">
                  {lang === "ar"
                    ? "مقياس تقريبي من 0 إلى 100 لمدى ازدحام المدارات."
                    : "Approximate 0–100 score for how crowded orbits are."}
                </p>
              </div>
            </div>
          </section>
          <section className="panel story-panel">
            <h3>{lang === "ar" ? "وضع القصص (عرض تنفيذي)" : "Story mode (executive view)"}</h3>
            <div className="story-grid">
              <div className="story-card">
                <h4>{lang === "ar" ? "اصطدامات محتملة تم تجنبها" : "Potential collisions avoided"}</h4>
                <p className="story-main">
                  {operationHistory.length.toLocaleString()}
                </p>
                <p className="sub">
                  {lang === "ar"
                    ? "عدد المناورات المكتملة في هذا النموذج – تمثل سيناريوهات اصطدام تم تجنبها."
                    : "Completed maneuvers in this demo – each representing an avoided collision scenario."}
                </p>
              </div>
              <div className="story-card">
                <h4>{lang === "ar" ? "تنبيهات عالية الخطورة" : "High‑risk alerts"}</h4>
                <p className="story-main">
                  {criticalAlertsCount.toLocaleString()}
                </p>
                <p className="sub">
                  {lang === "ar"
                    ? "عدد التنبيهات المصنّفة كحرجة أو عالية حالياً."
                    : "Number of alerts currently classified as high or urgent risk."}
                </p>
              </div>
              <div className="story-card">
                <h4>{lang === "ar" ? "مهمات تم تقييمها" : "Launch missions assessed"}</h4>
                <p className="story-main">
                  {launchResult ? 1 : 0}
                </p>
                <p className="sub">
                  {lang === "ar"
                    ? "هذا العدد يزيد كلما استخدمت نموذج تقييم مخاطر الإطلاق."
                    : "This count grows each time you run a launch risk assessment."}
                </p>
              </div>
            </div>
          </section>
        </>
      )}
      <section className="panel activity-panel">
        <h3>{lang === "ar" ? "خط النشاط الأخير" : "Recent activity"}</h3>
        {recentActivity.length === 0 ? (
          <p className="sub">
            {lang === "ar"
              ? "لا توجد عمليات مكتملة بعد لعرضها في الخط الزمني."
              : "No completed operations yet to show on the activity timeline."}
          </p>
        ) : (
          <ul className="activity-timeline">
            {recentActivity.map((item) => (
              <li key={item.ts} className="activity-item">
                <span className="activity-dot" />
                <div className="activity-main">
                  <p className="activity-label">{item.label}</p>
                  <p className="activity-time">{new Date(item.ts).toLocaleString()}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Card({ title, value, icon, subtitle }: { title: string; value: number; icon: string; subtitle: string }) {
  return (
    <div className="card metric-card">
      <div className="metric-header">
        <span className="metric-icon" aria-hidden>{icon}</span>
        <div>
          <p className="metric-title">{title}</p>
          <p className="metric-subtitle">{subtitle}</p>
        </div>
      </div>
      <div className="metric-value-row">
        <strong className="metric-value">{value.toLocaleString()}</strong>
        <span className="metric-trend positive">↑</span>
      </div>
    </div>
  );
}

export default App;
