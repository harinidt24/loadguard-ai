from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import shutil, sqlite3, uuid
from pathlib import Path
from pipeline import run_pipeline

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
EVIDENCE_DIR = Path("evidence")
UPLOAD_DIR.mkdir(exist_ok=True)
EVIDENCE_DIR.mkdir(exist_ok=True)

app.mount("/evidence", StaticFiles(directory="evidence"), name="evidence")

DB_PATH = "loadguard.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            timestamp_seconds REAL,
            behaviour_type TEXT,
            object_type TEXT,
            risk_score REAL,
            risk_level TEXT,
            confidence REAL,
            explanation TEXT,
            recommended_action TEXT,
            evidence_path TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


@app.get("/")
def read_root():
    return {"message": "LoadGuard AI backend is running"}


@app.post("/videos/upload")
def upload_video(file: UploadFile = File(...)):
    save_path = UPLOAD_DIR / file.filename
    with save_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Run the full pipeline right now (synchronous - simplest for a short demo clip)
    try:
        events = run_pipeline(str(save_path), EVIDENCE_DIR)
    except Exception as e:
        raise HTTPException(500, f"Pipeline failed: {e}")

    conn = get_db()
    for e in events:
        event_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO events (id, timestamp_seconds, behaviour_type, object_type, "
            "risk_score, risk_level, confidence, explanation, recommended_action, evidence_path) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (event_id, e["timestamp_seconds"], e["behaviour_type"], e["object_type"],
             e["risk_score"], e["risk_level"], e["confidence"], e["explanation"],
             e["recommended_action"], e["evidence_path"])
        )
    conn.commit()
    conn.close()

    return {"filename": file.filename, "events_found": len(events)}


@app.get("/events")
def list_events():
    conn = get_db()
    rows = conn.execute("SELECT * FROM events ORDER BY timestamp_seconds").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/dashboard/summary")
def dashboard_summary():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    by_risk = {r["risk_level"]: r["c"] for r in conn.execute(
        "SELECT risk_level, COUNT(*) c FROM events GROUP BY risk_level")}
    by_behaviour = {r["behaviour_type"]: r["c"] for r in conn.execute(
        "SELECT behaviour_type, COUNT(*) c FROM events GROUP BY behaviour_type")}
    conn.close()
    return {"total_events": total, "by_risk_level": by_risk, "by_behaviour": by_behaviour}
from fastapi import Body

@app.post("/assistant/query")
def assistant_query(payload: dict = Body(...)):
    question = payload.get("question", "").lower()

    conn = get_db()
    events = [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY risk_score DESC").fetchall()]
    conn.close()

    if not events:
        return {"answer": "No events have been recorded yet - upload and analyze a video first."}

    if "why" in question or "explain" in question:
        top = events[0]
        return {"answer": f"The highest-risk event was a {top['risk_level']} risk {top['behaviour_type']} "
                           f"involving a {top['object_type']} at {top['timestamp_seconds']:.1f}s (score {top['risk_score']}). "
                           f"{top['explanation']} Recommended action: {top['recommended_action']}"}

    if "common" in question or "most" in question:
        from collections import Counter
        counts = Counter(e["behaviour_type"] for e in events)
        top_behaviour, count = counts.most_common(1)[0]
        return {"answer": f"The most common behaviour was '{top_behaviour}', occurring {count} time(s) "
                           f"out of {len(events)} total events."}

    if "high" in question or "critical" in question:
        severe = [e for e in events if e["risk_level"] in ("high", "critical")]
        if not severe:
            return {"answer": "No high or critical risk events were detected in this footage."}
        lines = [f"- {e['risk_level'].upper()} {e['behaviour_type']} at {e['timestamp_seconds']:.1f}s: {e['explanation']}"
                 for e in severe[:5]]
        return {"answer": f"Found {len(severe)} high/critical event(s):\n" + "\n".join(lines)}

    if "action" in question or "recommend" in question or "corrective" in question:
        actions = list(set(e["recommended_action"] for e in events))
        return {"answer": "Recommended actions based on detected events: " + " | ".join(actions)}

    total = len(events)
    by_level = {}
    for e in events:
        by_level[e["risk_level"]] = by_level.get(e["risk_level"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in by_level.items())
    return {"answer": f"Detected {total} total event(s) this session: {summary}. "
                       f"Ask me about the most common behaviour, high-risk events, or recommended actions."}