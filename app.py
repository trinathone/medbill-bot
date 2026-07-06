import os
import logging
import httpx
import fitz
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.auth.transport.requests
import google.oauth2.id_token
from google.cloud import firestore
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("medbill-bot")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "hermez-fdff9")
FREE_LIMIT = int(os.environ.get("FREE_LIMIT", "5"))
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

app = FastAPI(title="MedBill Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Firestore client ────────────────────────────────────────
db = None
try:
    db = firestore.Client(project=FIREBASE_PROJECT_ID)
    logger.info("Firestore connected")
except Exception as e:
    logger.warning(f"Firestore unavailable: {e}")


# ── Auth helper ─────────────────────────────────────────────
def verify_firebase_token(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")
    token = auth_header.split(" ", 1)[1]
    try:
        decoded = google.oauth2.id_token.verify_firebase_token(
            token,
            google.auth.transport.requests.Request(),
            audience=FIREBASE_PROJECT_ID,
        )
        return decoded
    except Exception as e:
        logger.warning(f"Token verify failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Usage helpers ───────────────────────────────────────────
def get_month_key() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}-{now.month:02d}"


def check_and_increment_usage(uid: str) -> dict:
    """Returns {"count": N, "limit": FREE_LIMIT, "allowed": bool}"""
    if db is None:
        return {"count": 0, "limit": FREE_LIMIT, "allowed": True}
    month = get_month_key()
    ref = db.collection("usage").document(uid).collection("months").document(month)
    doc = ref.get()
    count = doc.to_dict().get("count", 0) if doc.exists else 0
    if count >= FREE_LIMIT:
        return {"count": count, "limit": FREE_LIMIT, "allowed": False}
    ref.set({"count": count + 1, "updated": datetime.now(timezone.utc)})
    return {"count": count + 1, "limit": FREE_LIMIT, "allowed": True}


def get_usage(uid: str) -> dict:
    if db is None:
        return {"count": 0, "limit": FREE_LIMIT}
    month = get_month_key()
    ref = db.collection("usage").document(uid).collection("months").document(month)
    doc = ref.get()
    count = doc.to_dict().get("count", 0) if doc.exists else 0
    return {"count": count, "limit": FREE_LIMIT}


# ── File extraction ───────────────────────────────────────────
def extract_pdf_text(data: bytes) -> str:
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF parse failed: {e}")

def extract_image_text(data: bytes) -> str:
    try:
        # Use pymupdf to open image and extract text via OCR
        with fitz.open(stream=data) as doc:
            text = "\n".join(page.get_text() for page in doc)
        if text.strip():
            return text
        # Fallback: send raw image bytes as base64 to Gemini vision
        return ""
    except Exception:
        return ""

def extract_text_from_file(data: bytes, filename: str, content_type: str) -> str:
    fname = filename.lower()
    if fname.endswith(".pdf") or content_type == "application/pdf":
        return extract_pdf_text(data)
    elif any(fname.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".heic", ".heif"]):
        # Return base64 for image — Gemini will do vision analysis
        import base64
        b64 = base64.b64encode(data).decode()
        mime = content_type if content_type and "image" in content_type else "image/jpeg"
        return f"__IMAGE_BASE64__{mime}::{b64}"
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload PDF, JPG, or PNG.")


# ── Gemini analysis ──────────────────────────────────────────
async def run_gemini(bill_text: str) -> dict:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")

    is_image = bill_text.startswith("__IMAGE_BASE64__")

    prompt_text = """You are a senior medical billing auditor with 20 years of experience. Analyze the medical bill and return ONLY a valid JSON object — no markdown, no explanation, no code fences.

JSON shape:
{
  "summary": {
    "total_billed": "$X,XXX",
    "potential_overcharge": "$X,XXX",
    "estimated_savings": "$X,XXX",
    "flags_count": N
  },
  "flags": [
    {
      "type": "overcharge|duplicate|verify|ok",
      "title": "Short issue title (max 8 words)",
      "description": "1-2 sentence plain-English explanation of the problem and why it matters.",
      "amount": "$XXX or null"
    }
  ],
  "dispute_letter": "Full formal dispute letter text, ready to mail or email. Include [YOUR NAME], [DATE], [PROVIDER NAME] placeholders where needed."
}

Types:
- overcharge: charge significantly above typical rates
- duplicate: same service billed twice
- verify: suspicious charge that needs clarification
- ok: charge appears reasonable (include 1-2 ok items for balance)
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    if is_image:
        # Vision mode — send image directly to Gemini
        _, rest = bill_text.split("__IMAGE_BASE64__", 1)
        mime, b64 = rest.split("::", 1)
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt_text + "\n\nAnalyze the medical bill shown in this image:"},
                    {"inline_data": {"mime_type": mime, "data": b64}}
                ]
            }],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096}
        }
    else:
        payload = {
            "contents": [{"parts": [{"text": prompt_text + "\n\nMedical bill to analyze:\n" + bill_text}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096}
        }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            logger.error(f"Gemini error {resp.status_code}: {resp.text[:300]}")
            raise HTTPException(status_code=502, detail="Gemini API error")
        data = resp.json()

    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    # strip markdown fences if model adds them
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0].strip()

    import json
    try:
        return json.loads(raw)
    except Exception:
        raise HTTPException(status_code=502, detail="Could not parse Gemini response")


# ── Routes ───────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 15MB)")
    text = extract_text_from_file(data, file.filename or "", file.content_type or "")
    return {"text": text, "chars": len(text)}


@app.get("/usage")
async def usage_endpoint(request: Request):
    user = verify_firebase_token(request)
    u = get_usage(user["uid"])
    return u


class AnalyzeRequest(BaseModel):
    bill_text: str


@app.post("/analyze")
async def analyze(body: AnalyzeRequest, request: Request):
    user = verify_firebase_token(request)
    uid = user["uid"]

    if not body.bill_text or len(body.bill_text.strip()) < 20:
        raise HTTPException(status_code=400, detail="Bill text too short")

    usage = check_and_increment_usage(uid)
    if not usage["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=f"Free limit reached ({usage['limit']} analyses/month). Upgrade for unlimited access."
        )

    result = await run_gemini(body.bill_text)
    result["usage"] = usage
    return result
