"""Tools for the Alex Researcher agent."""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List

import httpx
from agents import RunContextWrapper, function_tool
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class ResearchRunContext:
    """Per-run mutable state for planning and source tracking."""

    requested_topic: str
    started_at: str
    todos: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[Dict[str, str]] = field(default_factory=list)
    ingestion_count: int = 0


def _ingest(document: Dict[str, Any]) -> Dict[str, Any]:
    """Internal function to make the actual API call."""
    alex_api_endpoint = os.getenv("ALEX_API_ENDPOINT")
    alex_api_key = os.getenv("ALEX_API_KEY")

    if not alex_api_endpoint or not alex_api_key:
        raise RuntimeError("ALEX_API_ENDPOINT or ALEX_API_KEY is not configured")

    with httpx.Client() as client:
        response = client.post(
            alex_api_endpoint,
            json=document,
            headers={"x-api-key": alex_api_key},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
def ingest_with_retries(document: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest with retry logic for SageMaker cold starts."""
    return _ingest(document)


@function_tool
def add_todo_item(
    wrapper: RunContextWrapper[ResearchRunContext], task: str, success_criteria: str = ""
) -> Dict[str, Any]:
    """Add a checklist item for the current research run."""
    cleaned_task = task.strip()
    cleaned_criteria = success_criteria.strip()
    if not cleaned_task:
        return {"success": False, "error": "Task cannot be empty"}

    item_id = len(wrapper.context.todos) + 1
    item = {
        "id": item_id,
        "task": cleaned_task,
        "success_criteria": cleaned_criteria,
        "status": "pending",
        "created_at": datetime.now(UTC).isoformat(),
    }
    wrapper.context.todos.append(item)
    return {
        "success": True,
        "item": item,
        "total_items": len(wrapper.context.todos),
    }


@function_tool
def complete_todo_item(
    wrapper: RunContextWrapper[ResearchRunContext], item_id: int, evidence: str
) -> Dict[str, Any]:
    """Mark a checklist item complete with evidence of completion."""
    cleaned_evidence = evidence.strip()
    if not cleaned_evidence:
        return {"success": False, "error": "Evidence is required to complete a task"}

    for item in wrapper.context.todos:
        if item["id"] == item_id:
            item["status"] = "completed"
            item["evidence"] = cleaned_evidence
            item["completed_at"] = datetime.now(UTC).isoformat()
            return {"success": True, "item": item}

    return {"success": False, "error": f"Todo item {item_id} not found"}


@function_tool
def get_todo_status(wrapper: RunContextWrapper[ResearchRunContext]) -> Dict[str, Any]:
    """Return current checklist status for self-verification before final output."""
    total = len(wrapper.context.todos)
    completed = sum(1 for item in wrapper.context.todos if item["status"] == "completed")
    pending = total - completed
    return {
        "success": True,
        "summary": {
            "topic": wrapper.context.requested_topic,
            "started_at": wrapper.context.started_at,
            "total_items": total,
            "completed_items": completed,
            "pending_items": pending,
            "ingestion_count": wrapper.context.ingestion_count,
        },
        "items": wrapper.context.todos,
    }


@function_tool
def record_source(
    wrapper: RunContextWrapper[ResearchRunContext], url: str, note: str = ""
) -> Dict[str, Any]:
    """Record a source URL and optional note used during research."""
    cleaned_url = url.strip()
    cleaned_note = note.strip()
    if not cleaned_url:
        return {"success": False, "error": "URL cannot be empty"}

    for source in wrapper.context.sources:
        if source["url"] == cleaned_url:
            if cleaned_note and cleaned_note not in source["note"]:
                source["note"] = f"{source['note']} | {cleaned_note}".strip(" |")
            return {
                "success": True,
                "message": "Source already recorded, merged note",
                "source": source,
                "source_count": len(wrapper.context.sources),
            }

    source = {
        "url": cleaned_url,
        "note": cleaned_note,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    wrapper.context.sources.append(source)
    return {
        "success": True,
        "source": source,
        "source_count": len(wrapper.context.sources),
    }


@function_tool
def get_source_log(wrapper: RunContextWrapper[ResearchRunContext]) -> Dict[str, Any]:
    """Return the list of sources captured in this run."""
    return {
        "success": True,
        "source_count": len(wrapper.context.sources),
        "sources": wrapper.context.sources,
    }


@function_tool
def ingest_financial_document(
    wrapper: RunContextWrapper[ResearchRunContext], topic: str, analysis: str
) -> Dict[str, Any]:
    """
    Ingest a financial document into the Alex knowledge base.
    
    Args:
        topic: The topic or subject of the analysis (e.g., "AAPL Stock Analysis", "Retirement Planning Guide")
        analysis: Detailed analysis or advice with specific data and insights
    
    Returns:
        Dictionary with success status and document ID
    """
    if wrapper.context.ingestion_count >= 1:
        return {
            "success": False,
            "error": "Final analysis was already ingested for this run.",
        }

    if not os.getenv("ALEX_API_ENDPOINT") or not os.getenv("ALEX_API_KEY"):
        return {
            "success": False,
            "error": "Alex API not configured. Running in local mode."
        }
    
    document = {
        "text": analysis,
        "metadata": {
            "topic": topic,
            "timestamp": datetime.now(UTC).isoformat()
        }
    }
    
    try:
        result = ingest_with_retries(document)
        wrapper.context.ingestion_count += 1
        return {
            "success": True,
            "document_id": result.get("document_id"),  # Changed from documentId
            "message": f"Successfully ingested analysis for {topic}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
