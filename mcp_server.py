"""MedBill Bot MCP server — exposes analyze_medical_bill as an MCP tool.

Uses the anthropic Python SDK + ANTHROPIC_API_KEY env var.

Run with: python mcp_server.py

Add to Claude Desktop (claude_desktop_config.json):
  {"mcpServers": {"medbill": {"command": "python", "args": ["/path/to/mcp_server.py"],
                               "env": {"ANTHROPIC_API_KEY": "sk-ant-..."}}}}

Add with Claude Code:
  claude mcp add medbill -e ANTHROPIC_API_KEY=sk-ant-... -- python /path/to/mcp_server.py
"""
from __future__ import annotations

import os

import anthropic
from mcp.server.fastmcp import FastMCP

MODEL = "claude-haiku-4-5-20251001"
MAX_BILL_CHARS = 30_000

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

mcp = FastMCP("medbill")
_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


@mcp.tool()
def analyze_medical_bill(bill_text: str) -> dict:
    """Analyze a medical bill or EOB: explain charges, flag overcharges/duplicates,
    estimate fair pricing and savings, check charity care eligibility, and draft a
    dispute letter.

    Args:
        bill_text: The raw text of the medical bill or Explanation of Benefits (EOB).
    """
    bill_text = bill_text.strip()
    if not bill_text:
        raise ValueError("bill_text must not be empty.")
    if len(bill_text) > MAX_BILL_CHARS:
        bill_text = bill_text[:MAX_BILL_CHARS]

    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "submit_bill_analysis"},
        messages=[
            {"role": "user", "content": f"Here is the medical bill / EOB to analyze:\n\n{bill_text}"}
        ],
    )

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_block:
        raise RuntimeError("Claude did not return a structured analysis for this bill.")

    result = tool_block.input
    if isinstance(result.get("charity_care_eligible"), str) and result["charity_care_eligible"].lower() in ("true", "false"):
        result["charity_care_eligible"] = result["charity_care_eligible"].lower() == "true"

    return result


if __name__ == "__main__":
    mcp.run()
