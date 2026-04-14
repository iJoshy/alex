"""Agent instructions and context-engineering helpers for Alex Researcher."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional


DEFAULT_RESEARCH_PROMPT = (
    "Please research a current, interesting investment topic from today's financial news. "
    "Pick something trending or significant happening in the markets right now."
)


@dataclass(frozen=True)
class ResearchBrief:
    """Normalized brief fed to the researcher."""

    topic: str
    generated_at: str
    objective: str
    max_sources: int
    required_sections: tuple[str, ...]
    quality_checks: tuple[str, ...]


def build_research_brief(topic: Optional[str]) -> ResearchBrief:
    """Create a scoped brief so the agent starts with clear constraints."""
    cleaned_topic = (topic or "").strip()
    if not cleaned_topic:
        cleaned_topic = "a market-moving investment topic from today's financial news"

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    return ResearchBrief(
        topic=cleaned_topic,
        generated_at=generated_at,
        objective=(
            "Produce a concise, evidence-backed investment note with one clear recommendation "
            "and store it in the Alex knowledge base."
        ),
        max_sources=2,
        required_sections=(
            "Executive Summary",
            "What Happened",
            "Evidence and Numbers",
            "Recommendation and Risks",
        ),
        quality_checks=(
            "Use 1-2 reputable sources",
            "Include concrete numbers (price moves, valuation, earnings, guidance, or macro data)",
            "State at least 2 key risks or uncertainty factors",
            "Store the final analysis with ingest_financial_document",
        ),
    )


def render_research_task(brief: ResearchBrief) -> str:
    """Render a compact task payload for the model input."""
    sections = "\n".join(f"- {section}" for section in brief.required_sections)
    checks = "\n".join(f"- {check}" for check in brief.quality_checks)
    return (
        f"Research Topic: {brief.topic}\n"
        f"Timestamp (UTC): {brief.generated_at}\n\n"
        f"Objective:\n{brief.objective}\n\n"
        f"Scope Guardrails:\n"
        f"- Maximum web sources: {brief.max_sources}\n"
        "- Prefer primary or highly credible financial sources\n"
        "- If source coverage is weak, explicitly say so\n\n"
        f"Required Output Sections:\n{sections}\n\n"
        f"Quality Checks:\n{checks}\n"
    )


def get_agent_instructions() -> str:
    """Return the standing researcher operating instructions."""
    today = datetime.now(UTC).strftime("%B %d, %Y")
    return f"""You are Alex, an investment research agent. Today is {today}.

Operating protocol:
1. Plan first: create a short checklist using `add_todo_item` (at least 3 tasks).
2. Research: browse targeted pages with Playwright MCP, and capture each source with `record_source`.
3. Analyze: synthesize facts into a concise investment view.
4. Validate progress: use `get_todo_status` and `get_source_log` before finalizing.
5. Save: call `ingest_financial_document` exactly once with the final polished analysis.

Rules:
- Be concise, factual, and explicit about uncertainty.
- Prefer evidence and numbers over opinions.
- Do not invent prices, events, or citations.
- If browsing fails, provide a best-effort analysis and clearly note the limitation.
- Use only available browser tools exposed by MCP (for example navigate/snapshot/run_code/click/type/wait_for).
- Do not call `browser_search`.
"""
