# MedBill Bot — Redesign Task

## What to build

Two usage modes for the same app:

### Mode 1: Website with BYOK (Bring Your Own Key)
- Add an API key settings panel in the UI (top-right gear icon or banner)
- User pastes their Anthropic API key → store in localStorage ONLY, never sent to our server
- Move the AI analysis call to **client-side JavaScript** using fetch() to https://api.anthropic.com/v1/messages directly
- Backend (FastAPI) only handles PDF text extraction — returns raw text to frontend, frontend does the AI call
- Show a "🔑 Add your Anthropic API key to analyze bills" banner when no key is set
- Key input: password field, show/hide toggle, "Save Key" button, "Remove Key" link
- After key is saved, the analyze flow works entirely in browser

### Mode 2: MCP Server
- Create `mcp_server.py` — a proper MCP server using the `mcp` Python package
- Expose one tool: `analyze_medical_bill(bill_text: str) -> dict`
- The MCP server uses the user's ANTHROPIC_API_KEY env var
- Add to README: how to add to Claude Desktop config (claude_desktop_config.json)
- Add to README: how to use with Claude Code (`claude mcp add`)

## Files to create/modify

### `static/index.html` — full rewrite
- Keep the same dark medical UI design
- Add gear icon top-right → opens API key modal
- Banner at top: "No API key set — add yours to get started" (dismisses when key saved)
- Upload/paste flow unchanged
- Analysis now done via fetch() to Anthropic API from browser JS
- Show model used: claude-haiku-4-5-20251001 (cheapest, fast)
- Key stored as localStorage.getItem('anthropic_api_key')

### `app.py` — simplify
- Remove all Bedrock/boto3 AI calls
- Keep only: POST /extract — accepts file upload, returns {text: "...extracted bill text..."}
- Keep: GET / — serves index.html
- Remove /analyze endpoint (AI moved to browser)

### `mcp_server.py` — new file
```python
# MCP server exposing analyze_medical_bill tool
# Uses anthropic Python SDK + ANTHROPIC_API_KEY env var
# Run with: python mcp_server.py
# Add to Claude Desktop: {"mcpServers": {"medbill": {"command": "python", "args": ["/path/to/mcp_server.py"]}}}
```

### `requirements.txt` — update
- Remove boto3, anthropic (server-side)
- Add: mcp>=1.0.0, anthropic>=0.40.0 (for mcp_server.py only)
- FastAPI backend only needs: fastapi, uvicorn, pymupdf, python-multipart

### `README.md` — rewrite with two sections:
1. Website usage (paste key, analyze bill)
2. MCP usage — Claude Desktop + Claude Code setup instructions with exact config snippets

## Design for the key input modal
```
┌─────────────────────────────────────┐
│  🔑 Your Anthropic API Key          │
│  ─────────────────────────────────  │
│  [sk-ant-...            ] [👁]      │
│  Stored locally only. Never sent    │
│  to our servers.                    │
│  [Save Key]           [Cancel]      │
│                                     │
│  Get a key: console.anthropic.com   │
└─────────────────────────────────────┘
```

## Important
- The Anthropic API key NEVER leaves the browser. Only the extracted PDF text goes to Anthropic's API directly from the user's browser.
- Use claude-haiku-4-5-20251001 as the model (cheapest for users)
- The system prompt and JSON schema for analysis stays exactly the same as the current /analyze endpoint
- After building, test by starting uvicorn, opening browser, verify the modal and banner render correctly
- Update Railway env vars: remove AWS credentials (no longer needed), keep PORT
- Push all changes to git when done
- Deploy: railway up --service medbill-bot --detach
