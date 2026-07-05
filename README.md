# MedBill Bot — AI Medical Bill Analyzer

Paste or upload a medical bill / EOB and get: a plain-English explanation of every
line item, flags for likely overcharges/duplicates, an estimated fair price and
savings, a charity-care eligibility check, and a ready-to-send dispute letter.

There are two ways to use it, both powered by your own Anthropic API key —
your key never touches our server.

## 1. Website (bring your own key)

The website only uses your Anthropic API key from your browser — it's stored in
`localStorage` and sent directly from your browser to `api.anthropic.com`. The
backend never sees it; it only extracts text from uploaded PDFs.

1. Open the site and click the ⚙️ gear icon (or the "add your key" banner).
2. Paste your Anthropic API key (get one at [console.anthropic.com](https://console.anthropic.com)) and click **Save Key**.
3. Paste your bill text or upload a PDF/TXT file, then click **Analyze My Bill**.

Analysis runs with `claude-haiku-4-5-20251001` (fast and cheap) directly from
your browser. Click **Remove Key** in the settings modal to clear it from
`localStorage` at any time.

### Running it yourself

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

Then open http://localhost:8000.

## 2. MCP Server

`mcp_server.py` exposes a single tool, `analyze_medical_bill(bill_text: str) -> dict`,
that any MCP-compatible client (Claude Desktop, Claude Code, etc.) can call. It
uses the `anthropic` Python SDK and reads your key from the `ANTHROPIC_API_KEY`
environment variable.

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python mcp_server.py
```

### Add to Claude Desktop

Add this to your `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "medbill": {
      "command": "python",
      "args": ["/absolute/path/to/mcp_server.py"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

Restart Claude Desktop, then ask it to analyze a bill — it will call the
`analyze_medical_bill` tool.

### Add to Claude Code

```bash
claude mcp add medbill -e ANTHROPIC_API_KEY=sk-ant-... -- python /absolute/path/to/mcp_server.py
```

Then, in a Claude Code session, ask it to analyze a bill's text using the
`medbill` MCP server.

## Project structure

```
medbill-bot/
├── app.py              # FastAPI backend — PDF/text extraction only (/extract)
├── mcp_server.py        # MCP server exposing analyze_medical_bill
├── static/
│   └── index.html       # Single-page frontend, does the AI call client-side
├── requirements.txt
└── .env.example
```
