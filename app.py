"""MedBill Bot - FastAPI backend. All application logic lives in this file."""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import boto3
import fitz  # PyMuPDF
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("medbill-bot")

MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
MAX_BILL_CHARS = 30_000  # keep prompt sizes sane / cost predictable

app = FastAPI(title="MedBill Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

_bedrock = None

def get_client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
    return _bedrock


ANALYSIS_TOOL = {
    "name": "submit_bill_analysis",
    "description": "Submit the structured analysis of a medical bill or EOB.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One paragraph, plain English summary a non-expert patient can understand.",
            },
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "charge": {"type": "string"},
                        "amount": {"type": "string"},
                        "explanation": {
                            "type": "string",
                            "description": "Plain English explanation of what this charge is for.",
                        },
                        "flag": {
                            "type": ["string", "null"],
                            "enum": ["OVERCHARGE", "DUPLICATE", "VERIFY", None],
                        },
                        "flag_reason": {
                            "type": ["string", "null"],
                            "description": "Why this item was flagged, or null if not flagged.",
                        },
                    },
                    "required": ["charge", "amount", "explanation", "flag", "flag_reason"],
                },
            },
            "total_charged": {"type": "string"},
            "estimated_fair_price": {"type": "string"},
            "potential_savings": {"type": "string"},
            "charity_care_eligible": {
                "type": ["boolean", "string"],
                "description": "true, false, or \"unknown\" if not enough information is provided.",
            },
            "dispute_letter": {
                "type": "string",
                "description": "Full, ready-to-send dispute letter text, copy-paste ready with placeholders like [Your Name] where patient-specific info is unknown.",
            },
            "action_items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete next steps the patient should take, in order.",
            },
        },
        "required": [
            "summary",
            "line_items",
            "total_charged",
            "estimated_fair_price",
            "potential_savings",
            "charity_care_eligible",
            "dispute_letter",
            "action_items",
        ],
    },
}

SYSTEM_PROMPT = """You are a meticulous medical billing advocate who helps patients understand and dispute confusing medical bills and Explanations of Benefits (EOBs).

For the bill text you are given:
1. Explain every distinct line item in plain, friendly English (no jargon).
2. Flag potential issues:
   - OVERCHARGE: the amount looks unusually high compared to typical fair market/Medicare-adjacent rates.
   - DUPLICATE: the same service appears to be billed more than once.
   - VERIFY: unclear or unbundled charges the patient should ask the provider to itemize/justify.
   - null: charge looks normal and correctly billed.
3. Estimate a "fair price" total based on typical reasonable rates, and calculate potential savings versus the charged total. If the bill doesn't include enough information to compute real dollar totals, make clearly-labeled reasonable estimates rather than refusing.
4. Assess charity care / financial assistance eligibility only from what's stated; if unknown, say "unknown".
5. Draft a complete, professional, copy-paste-ready dispute letter addressed to the billing department, referencing the specific flagged line items and requesting an itemized bill and review. Use placeholders like [Your Name], [Account Number], [Date] where patient-specific info wasn't provided.
6. Give a short, concrete, ordered list of action items the patient should take.

Always call the submit_bill_analysis tool with your findings. Be specific and cite the actual charges from the input. Never fabricate charges that are not present in the input."""


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


def run_analysis(bill_text: str) -> dict:
    bill_text = bill_text.strip()
    if not bill_text:
        raise HTTPException(status_code=400, detail="Please provide some bill text, description, or a PDF file to analyze.")

    if len(bill_text) > MAX_BILL_CHARS:
        bill_text = bill_text[:MAX_BILL_CHARS]
        logger.info("Truncated bill text to %d characters", MAX_BILL_CHARS)

    client = get_client()

    tool_config = {
        "tools": [{"toolSpec": {
            "name": ANALYSIS_TOOL["name"],
            "description": ANALYSIS_TOOL["description"],
            "inputSchema": {"json": ANALYSIS_TOOL["input_schema"]},
        }}],
        "toolChoice": {"tool": {"name": ANALYSIS_TOOL["name"]}},
    }

    try:
        response = client.converse(
            modelId=MODEL,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": f"Here is the medical bill / EOB to analyze:\n\n{bill_text}"}]}],
            toolConfig=tool_config,
            inferenceConfig={"maxTokens": 4096},
        )
    except Exception as e:
        logger.error("Bedrock API error: %s", e)
        raise HTTPException(status_code=502, detail="Our AI analysis service had a problem. Please try again shortly.")

    # Extract tool use result
    try:
        content = response["output"]["message"]["content"]
        tool_block = next((b for b in content if "toolUse" in b), None)
        if not tool_block:
            raise HTTPException(status_code=502, detail="We couldn't generate a structured analysis for this bill. Please try again.")
        result = tool_block["toolUse"]["input"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to parse Bedrock response: %s", e)
        raise HTTPException(status_code=502, detail="We couldn't parse the analysis response. Please try again.")

    if isinstance(result.get("charity_care_eligible"), str) and result["charity_care_eligible"].lower() in ("true", "false"):
        result["charity_care_eligible"] = result["charity_care_eligible"].lower() == "true"

    return result


@app.get("/")
def serve_index():
    return FileResponse("static/index.html")


@app.post("/analyze")
async def analyze(
    text: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
):
    try:
        if file is not None and file.filename:
            content_type = (file.content_type or "").lower()
            filename = file.filename.lower()
            data = await file.read()

            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail="That file is too large. Please upload a file under 15 MB.",
                )

            if filename.endswith(".pdf") or "pdf" in content_type:
                bill_text = extract_pdf_text(data)
            elif filename.endswith(".txt") or content_type.startswith("text/"):
                try:
                    bill_text = data.decode("utf-8", errors="ignore").strip()
                except Exception:
                    raise HTTPException(
                        status_code=400,
                        detail="We couldn't read that text file. Please try pasting the content instead.",
                    )
                if not bill_text:
                    raise HTTPException(status_code=400, detail="That file appears to be empty.")
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Please upload a PDF or plain text file, or paste your bill as text.",
                )
        elif text and text.strip():
            bill_text = text.strip()
        else:
            raise HTTPException(
                status_code=400,
                detail="Please paste your bill text or upload a PDF/text file to analyze.",
            )

        result = run_analysis(bill_text)
        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during analysis")
        raise HTTPException(
            status_code=500,
            detail="Something went wrong on our end while analyzing your bill. Please try again.",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
