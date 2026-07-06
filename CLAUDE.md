# BillClear — Medical Bill Analyzer

## Stack
- **Frontend:** Static HTML/JS on Firebase Hosting (`billclear.web.app`)
- **Backend:** FastAPI on Railway (`medbill-bot-production.up.railway.app`)
- **Auth:** Firebase Auth (Google Sign-in via signInWithPopup)
- **AI:** Gemini 1.5 Flash (vision + text)
- **DB:** Firestore (usage tracking)

## Deploy
- Frontend: `npx firebase-tools deploy --only hosting --token $FIREBASE_TOKEN`
- Backend: `railway up --detach` OR `git push origin main` (Railway auto-deploys)
- FIREBASE_TOKEN: set in env, do not commit
- Git SSH: `GIT_SSH_COMMAND='ssh -i ~/.ssh/github_trinathone'`

## Key Files
- `static/index.html` — entire frontend (single file)
- `app.py` — FastAPI backend
- `firebase.json` — deploys to `billclear` site

## Rules (Ponytail)
- Laziest solution that works. No bloat.
- Every request/response MUST be logged with `logger.info()` — include endpoint, uid, status, timing
- Log errors with `logger.error()` + full exception
- Frontend errors must show human-readable message (not "Failed to fetch")
- No new dependencies unless absolutely necessary

## Known Issues to Fix
1. Sign-in works (signInWithPopup) but user must be signed in to analyze
2. `/analyze-file` endpoint — image upload + Gemini vision
3. `/analyze` endpoint — text/PDF analysis
4. Firebase token `uid` comes from `sub` field in decoded JWT
5. Frontend on `billclear.web.app`, backend on Railway — all fetch() calls must use absolute Railway URL

## Logging Standard
Every endpoint must log:
```python
logger.info(f"[/endpoint] uid={uid} status=ok duration={elapsed:.2f}s")
logger.error(f"[/endpoint] uid={uid} error={e}")
```
