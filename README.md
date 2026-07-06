# BillClear — AI Medical Bill Analyzer

> Upload any medical bill (PDF, photo, image) and instantly get a plain-English breakdown of what you're being charged, what looks off, and what to dispute.

**Live → [billclear.web.app](https://billclear.web.app)**

---

## What it does

Medical bills are intentionally confusing. BillClear uses Gemini 2.5 Flash vision AI to:

- **Break down every charge** in plain English
- **Flag potential errors** — duplicate charges, upcoding, unbundling
- **Estimate fair prices** based on typical rates
- **Tell you exactly what to dispute** and how

Upload a photo of your bill. Get answers in seconds.

---

## Stack

| Layer | Tech |
|-------|------|
| Frontend | Vanilla HTML/JS — Firebase Hosting |
| Backend | FastAPI — Railway |
| Auth | Firebase Auth (Google Sign-in) |
| AI | Gemini 2.5 Flash (vision + text) |
| Usage tracking | Firestore |

---

## Free Tier

- **5 analyses/month** free per account
- No credit card required
- Powered by Gemini API free tier (1,500 req/day)

---

## Run locally

```bash
git clone https://github.com/trinathone/medbill-bot
cd medbill-bot
pip install -r requirements.txt

# Set env vars
export GEMINI_API_KEY=your_key_from_aistudio.google.com
export FIREBASE_PROJECT_ID=your_firebase_project

uvicorn app:app --reload
```

Open `static/index.html` or visit `http://localhost:8000`

---

## Deploy

**Backend (Railway)**
```bash
railway up
```

**Frontend (Firebase Hosting)**
```bash
npx firebase-tools deploy --only hosting
```

---

## Observability

Every request is logged with uid, duration, and status:
```
[/analyze-file] uid=abc123 status=ok dur=2.3s
[/analyze-file] uid=abc123 error=Gemini API error
```

Health check: `GET /health`

---

## License

MIT
