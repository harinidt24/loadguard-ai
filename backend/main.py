from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import shutil, sqlite3, uuid, datetime
from pathlib import Path
from pipeline import run_pipeline
from google import genai

import os

def load_gemini_client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:
            key = Path("gemini_key.txt").read_text().strip()
        except FileNotFoundError:
            return None
    if not key:
        return None
    return genai.Client(api_key=key)

gemini_client = load_gemini_client()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173","https://loadguard-ai-1.onrender.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
EVIDENCE_DIR = Path("evidence")
UPLOAD_DIR.mkdir(exist_ok=True)
EVIDENCE_DIR.mkdir(exist_ok=True)

app.mount("/evidence", StaticFiles(directory="evidence"), name="evidence")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

DB_PATH = "loadguard.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            filename TEXT,
            uploaded_at TEXT,
            event_count INTEGER,
            safety_score REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            video_id TEXT,
            created_at TEXT,
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


def compute_safety_score(events):
    """Starts at 100, subtracts more for higher-risk events. Simple and explainable."""
    score = 100.0
    for e in events:
        score -= e["risk_score"] / 8
    return max(0, round(score, 1))


@app.get("/")
def read_root():
    return {"message": "LoadGuard AI backend is running"}


@app.post("/videos/upload")
def upload_video(file: UploadFile = File(...)):
    save_path = UPLOAD_DIR / file.filename
    with save_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        events = run_pipeline(str(save_path), EVIDENCE_DIR)
    except Exception as e:
        raise HTTPException(500, f"Pipeline failed: {e}")

    video_id = str(uuid.uuid4())
    uploaded_at = datetime.datetime.now().isoformat()
    safety_score = compute_safety_score(events)

    conn = get_db()
    conn.execute(
        "INSERT INTO videos (id, filename, uploaded_at, event_count, safety_score) VALUES (?,?,?,?,?)",
        (video_id, file.filename, uploaded_at, len(events), safety_score)
    )
    for e in events:
        event_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO events (id, video_id, created_at, timestamp_seconds, behaviour_type, object_type, "
            "risk_score, risk_level, confidence, explanation, recommended_action, evidence_path) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, video_id, uploaded_at, e["timestamp_seconds"], e["behaviour_type"], e["object_type"],
             e["risk_score"], e["risk_level"], e["confidence"], e["explanation"],
             e["recommended_action"], e["evidence_path"])
        )
    conn.commit()
    conn.close()

    return {"filename": file.filename, "video_id": video_id, "events_found": len(events), "safety_score": safety_score}


@app.get("/events")
def list_events(video_id: str = None):
    conn = get_db()
    if video_id:
        rows = conn.execute("SELECT * FROM events WHERE video_id=? ORDER BY timestamp_seconds", (video_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM events ORDER BY created_at DESC, timestamp_seconds").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/videos")
def list_videos():
    conn = get_db()
    rows = conn.execute("SELECT * FROM videos ORDER BY uploaded_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/dashboard/summary")
def dashboard_summary(video_id: str = None):
    conn = get_db()
    if video_id:
        events = conn.execute("SELECT * FROM events WHERE video_id=?", (video_id,)).fetchall()
    else:
        events = conn.execute("SELECT * FROM events").fetchall()
    total = len(events)
    by_risk = {}
    by_behaviour = {}
    for e in events:
        by_risk[e["risk_level"]] = by_risk.get(e["risk_level"], 0) + 1
        by_behaviour[e["behaviour_type"]] = by_behaviour.get(e["behaviour_type"], 0) + 1
    conn.close()
    return {"total_events": total, "by_risk_level": by_risk, "by_behaviour": by_behaviour}


@app.post("/assistant/query")
def assistant_query(payload: dict = Body(...)):
    question = payload.get("question", "")
    video_id = payload.get("video_id")

    conn = get_db()
    if video_id:
        events = [dict(r) for r in conn.execute(
            "SELECT * FROM events WHERE video_id=? ORDER BY risk_score DESC", (video_id,)).fetchall()]
    else:
        events = [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY risk_score DESC").fetchall()]
    conn.close()

    if not events:
        return {"answer": "No events have been recorded yet - upload and analyze a video first."}

    if gemini_client:
        try:
            import json
            context = json.dumps(events[:30], indent=2, default=str)
            prompt = f"""You are LoadGuard AI's warehouse supervisor assistant.
Answer ONLY using the real incident data below. Never invent details.
Never claim a product was definitely damaged - only report observed behaviour and risk level.
Be concise and operational.

Incident data:
{context}

Supervisor question: {question}"""

            response = gemini_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
            )
            return {"answer": response.text}
        except Exception as e:
            print(f"Gemini call failed, using fallback: {e}")
            # falls through to rule-based fallback below

    return {"answer": fallback_answer(question.lower(), events)}


def fallback_answer(question, events):
    if "why" in question or "explain" in question:
        top = events[0]
        return (f"The highest-risk event was a {top['risk_level']} risk {top['behaviour_type']} "
                f"involving a {top['object_type']} at {top['timestamp_seconds']:.1f}s (score {top['risk_score']}). "
                f"{top['explanation']} Recommended action: {top['recommended_action']}")

    if "common" in question or "most" in question:
        from collections import Counter
        counts = Counter(e["behaviour_type"] for e in events)
        top_behaviour, count = counts.most_common(1)[0]
        return f"The most common behaviour was '{top_behaviour}', occurring {count} time(s) out of {len(events)} total events."

    if "high" in question or "critical" in question:
        severe = [e for e in events if e["risk_level"] in ("high", "critical")]
        if not severe:
            return "No high or critical risk events were detected in this footage."
        lines = [f"- {e['risk_level'].upper()} {e['behaviour_type']} at {e['timestamp_seconds']:.1f}s: {e['explanation']}"
                 for e in severe[:5]]
        return f"Found {len(severe)} high/critical event(s):\n" + "\n".join(lines)

    if "action" in question or "recommend" in question or "corrective" in question:
        actions = list(set(e["recommended_action"] for e in events))
        return "Recommended actions based on detected events: " + " | ".join(actions)

    total = len(events)
    by_level = {}
    for e in events:
        by_level[e["risk_level"]] = by_level.get(e["risk_level"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in by_level.items())
    return (f"Detected {total} total event(s) this session: {summary}. "
            f"Ask me about the most common behaviour, high-risk events, or recommended actions.")