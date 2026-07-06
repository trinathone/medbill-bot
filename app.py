import os, time, base64, json, logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx, fitz
import google.auth.transport.requests, google.oauth2.id_token
from google.cloud import firestore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("billclear")

GEMINI_KEY    = os.environ.get("GEMINI_API_KEY", "")
FB_PROJECT    = os.environ.get("FIREBASE_PROJECT_ID", "hermez-fdff9")
FREE_LIMIT    = int(os.environ.get("FREE_LIMIT", "5"))
MAX_BYTES     = 15 * 1024 * 1024
GEMINI_URL    = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"

app = FastAPI(title="BillClear")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

# ponytail: lazy firestore init — None = disabled gracefully
db = None
try:
    db = firestore.Client(project=FB_PROJECT)
    log.info("Firestore connected")
except Exception as e:
    log.warning(f"Firestore unavailable: {e}")


# ── Auth ─────────────────────────────────────────────────────
def auth(request: Request) -> str:
    hdr = request.headers.get("Authorization", "")
    if not hdr.startswith("Bearer "):
        raise HTTPException(401, "Missing auth token")
    try:
        d = google.oauth2.id_token.verify_firebase_token(
            hdr[7:], google.auth.transport.requests.Request(), audience=FB_PROJECT)
        return d.get("uid") or d.get("sub", "")
    except Exception as e:
        log.warning(f"Auth failed: {e}")
        raise HTTPException(401, "Invalid token")


# ── Usage ────────────────────────────────────────────────────
def _usage_ref(uid: str):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return db.collection("usage").document(uid).collection("months").document(month)

def get_usage(uid: str) -> dict:
    if db is None: return {"count": 0, "limit": FREE_LIMIT}
    doc = _usage_ref(uid).get()
    return {"count": (doc.to_dict() or {}).get("count", 0), "limit": FREE_LIMIT}

def consume_usage(uid: str) -> dict:
    if db is None: return {"count": 1, "limit": FREE_LIMIT, "allowed": True}
    ref = _usage_ref(uid)
    doc = ref.get()
    count = (doc.to_dict() or {}).get("count", 0)
    if count >= FREE_LIMIT:
        return {"count": count, "limit": FREE_LIMIT, "allowed": False}
    ref.set({"count": count + 1, "updated": datetime.now(timezone.utc)})
    return {"count": count + 1, "limit": FREE_LIMIT, "allowed": True}


# ── Gemini ───────────────────────────────────────────────────
PROMPT = """You are a senior medical billing auditor. Analyze the bill and return ONLY valid JSON — no markdown, no fences, no extra text.

Shape:
{
  "summary": {"total_billed":"$X","potential_overcharge":"$X","estimated_savings":"$X","flags_count":N},
  "flags": [{"type":"overcharge|duplicate|verify|ok","title":"short title max 6 words","description":"1 sentence only","amount":"$X or null"}],
  "dispute_letter": "Formal dispute letter under 400 words. Use [YOUR NAME], [DATE], [PROVIDER NAME] placeholders."
}
Types: overcharge=above typical rates, duplicate=billed twice, verify=needs clarification, ok=reasonable (1-2 items)."""

async def gemini(bill_text: str) -> dict:
    if not GEMINI_KEY:
        raise HTTPException(500, "Gemini API key not configured")

    if bill_text.startswith("__IMG__"):
        _, mime, b64 = bill_text.split("::", 2)
        parts = [{"text": PROMPT + "\n\nAnalyze the medical bill in this image:"},
                 {"inline_data": {"mime_type": mime, "data": b64}}]
    else:
        parts = [{"text": PROMPT + "\n\nBill:\n" + bill_text}]

    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(GEMINI_URL, json={
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192}
        })
    if r.status_code != 200:
        log.error(f"Gemini {r.status_code}: {r.text[:200]}")
        raise HTTPException(502, "Gemini API error")

    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    if raw.startswith("```"):  # strip fences if model adds them
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except Exception:
        raise HTTPException(502, "Could not parse Gemini response")


# ── Routes ───────────────────────────────────────────────────
@app.get("/")
async def root(): return FileResponse("static/index.html")

@app.get("/health")
async def health():
    return {"status": "ok", "gemini_key_set": bool(GEMINI_KEY),
            "firebase_project": FB_PROJECT, "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/usage")
async def usage_endpoint(request: Request):
    t = time.time()
    uid = auth(request)
    u = get_usage(uid)
    log.info(f"[/usage] uid={uid} dur={time.time()-t:.2f}s")
    return u

@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 15MB)")
    fname = (file.filename or "").lower()
    if fname.endswith(".pdf") or file.content_type == "application/pdf":
        with fitz.open(stream=data, filetype="pdf") as doc:
            return {"text": "\n".join(p.get_text() for p in doc)}
    mime = file.content_type or "image/jpeg"
    return {"text": f"__IMG__::{mime}::{base64.b64encode(data).decode()}"}

class AnalyzeReq(BaseModel):
    bill_text: str

# ponytail: one analyze endpoint handles both text+image via bill_text sentinel
@app.post("/analyze")
async def analyze(body: AnalyzeReq, request: Request):
    t = time.time()
    uid = auth(request)
    if not body.bill_text or len(body.bill_text.strip()) < 20:
        raise HTTPException(400, "Bill text too short")
    usage = consume_usage(uid)
    if not usage["allowed"]:
        raise HTTPException(429, f"Free limit reached ({FREE_LIMIT}/month). Upgrade for unlimited.")
    result = await gemini(body.bill_text)
    result["usage"] = usage
    log.info(f"[/analyze] uid={uid} dur={time.time()-t:.2f}s")
    return result

@app.post("/analyze-file")
async def analyze_file(request: Request, file: UploadFile = File(...)):
    t = time.time()
    uid = auth(request)
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 15MB)")
    mime = file.content_type or "image/jpeg"
    bill_text = f"__IMG__::{mime}::{base64.b64encode(data).decode()}"
    usage = consume_usage(uid)
    if not usage["allowed"]:
        raise HTTPException(429, f"Free limit reached ({FREE_LIMIT}/month). Upgrade for unlimited.")
    result = await gemini(bill_text)
    result["usage"] = usage
    log.info(f"[/analyze-file] uid={uid} dur={time.time()-t:.2f}s")
    return result
