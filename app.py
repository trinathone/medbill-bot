"""MedBill Bot - FastAPI backend. Extracts text from uploaded bills; AI analysis runs client-side."""
from __future__ import annotations

import logging

import fitz  # PyMuPDF
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("medbill-bot")

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB

app = FastAPI(title="MedBill Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


def extract_pdf_text(data: bytes) -> str:
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            text = "\n".join(page.get_text() for page in doc)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="We couldn't read that PDF. It may be corrupted, password-protected, or a scanned image without selectable text. Try pasting the bill text instead.",
        )
    text = text.strip()
    if not text:
        raise HTTPException(
            status_code=400,
            detail="That PDF doesn't seem to contain any readable text (it may be a scanned image). Try pasting the bill details as text instead.",
        )
    return text


@app.get("/")
def serve_index():
    return FileResponse("static/index.html")


@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    try:
        content_type = (file.content_type or "").lower()
        filename = file.filename.lower() if file.filename else ""
        data = await file.read()

        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail="That file is too large. Please upload a file under 15 MB.",
            )

        if filename.endswith(".pdf") or "pdf" in content_type:
            text = extract_pdf_text(data)
        elif filename.endswith(".txt") or content_type.startswith("text/"):
            text = data.decode("utf-8", errors="ignore").strip()
            if not text:
                raise HTTPException(status_code=400, detail="That file appears to be empty.")
        else:
            raise HTTPException(
                status_code=400,
                detail="Please upload a PDF or plain text file, or paste your bill as text.",
            )

        return JSONResponse(content={"text": text})

    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during extraction")
        raise HTTPException(
            status_code=500,
            detail="Something went wrong on our end while reading your file. Please try again.",
        )


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
