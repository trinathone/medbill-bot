# MedBill Bot — AI Medical Bill Analyzer

## What We're Building
A web app where patients upload/paste their medical bill or EOB (Explanation of Benefits) and AI:
1. Explains every line item in plain English
2. Flags potential overcharges, duplicate billing, unbundling fraud
3. Checks if charity care / financial assistance applies
4. Drafts a dispute letter instantly

## Stack
- **Backend:** Python + FastAPI
- **Frontend:** Single HTML file with Tailwind CSS (no build step)
- **AI:** Anthropic Claude API (claude-3-5-haiku for speed/cost)
- **PDF parsing:** PyMuPDF (fitz)
- **Deploy:** Single `python app.py` command

## Project Structure
```
medbill-bot/
├── app.py              # FastAPI backend (ALL logic here)
├── static/
│   └── index.html      # Single-page frontend
├── requirements.txt
└── .env.example
```

## Key Rules
- NO database needed — stateless, each analysis is independent
- NO auth needed — MVP is fully open
- Mobile-first UI — patients use phones
- Response must be structured: sections for each finding
- Must handle: uploaded PDF, pasted text, or typed bill description
- Error messages must be human-friendly (no stack traces to users)
- The dispute letter must be copy-paste ready

## API Endpoints
- `POST /analyze` — accepts text or file, returns JSON analysis
- `GET /` — serves the frontend

## Analysis Output Structure
```json
{
  "summary": "One paragraph plain English summary",
  "line_items": [
    {
      "charge": "Room & Board",
      "amount": "$2,400",
      "explanation": "Daily rate for hospital room",
      "flag": null | "OVERCHARGE" | "DUPLICATE" | "VERIFY",
      "flag_reason": "..."
    }
  ],
  "total_charged": "$8,400",
  "estimated_fair_price": "$3,200",
  "potential_savings": "$5,200",
  "charity_care_eligible": true | false | "unknown",
  "dispute_letter": "Full letter text ready to copy-paste",
  "action_items": ["Call billing at 1-800-XXX", "Request itemized bill", ...]
}
```

## Environment
- ANTHROPIC_API_KEY required
- Run: uvicorn app:app --reload --port 8000
