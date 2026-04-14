"""
Alex Researcher Service - Investment Advice Agent
"""

import os
import asyncio
import logging
from datetime import datetime, UTC
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from agents import Agent, Runner, trace
from agents.extensions.models.litellm_model import LitellmModel
from agents.exceptions import AgentsException, MaxTurnsExceeded, ModelBehaviorError

# Load environment before importing local modules that may read env vars
load_dotenv(override=True)

# Suppress LiteLLM warnings about optional dependencies
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)

# Import from our modules
from context import build_research_brief, get_agent_instructions, render_research_task
from mcp_servers import create_playwright_mcp_server
from tools import (
    ResearchRunContext,
    add_todo_item,
    complete_todo_item,
    get_source_log,
    get_todo_status,
    ingest_financial_document,
    record_source,
)

app = FastAPI(title="Alex Researcher Service")


# Request model
class ResearchRequest(BaseModel):
    topic: Optional[str] = None  # Optional - if not provided, agent picks a topic


def _resolve_bedrock_settings() -> tuple[str, str]:
    """Resolve Bedrock region and model with safe defaults for this project."""
    bedrock_region = (
        os.getenv("BEDROCK_REGION") or os.getenv("RESEARCHER_BEDROCK_REGION") or "us-west-2"
    ).strip()

    raw_model_id = (
        os.getenv("BEDROCK_MODEL_ID")
        or os.getenv("RESEARCHER_BEDROCK_MODEL")
        or "openai.gpt-oss-120b-1:0"
    ).strip()
    model = raw_model_id if raw_model_id.startswith("bedrock/") else f"bedrock/{raw_model_id}"
    return bedrock_region, model


def _resolve_runtime_limits() -> tuple[int, int, int]:
    """Resolve runtime limits to keep requests under App Runner timeout."""
    mcp_timeout_seconds = int(os.getenv("RESEARCHER_MCP_TIMEOUT_SECONDS", "30"))
    max_turns = int(os.getenv("RESEARCHER_MAX_TURNS", "14"))
    request_timeout_seconds = int(os.getenv("RESEARCHER_REQUEST_TIMEOUT_SECONDS", "75"))
    return mcp_timeout_seconds, max_turns, request_timeout_seconds


def _get_fallback_instructions() -> str:
    """Instructions used when browser-backed flow fails or times out."""
    return """You are Alex, an investment research agent in fallback mode.

Your browsing tools are unavailable in this run. Produce a concise best-effort analysis using general
market knowledge, clearly label uncertainty, and avoid fabricated specifics.

Required steps:
1. Create a short checklist with add_todo_item.
2. Provide a concise analysis with:
   - Executive Summary
   - What We Know vs Unknown
   - Recommendation and Risks
3. Mark checklist items complete.
4. Save final analysis once with ingest_financial_document.
"""


async def _run_fallback_agent(
    query: str, model: LitellmModel, context: ResearchRunContext
) -> str:
    """Fallback run without MCP browser dependency."""
    fallback_query = (
        f"{query}\n\n"
        "Fallback mode trigger: browser workflow failed or timed out. "
        "Proceed without browsing and explicitly mention this limitation."
    )
    fallback_agent = Agent[ResearchRunContext](
        name="Alex Investment Researcher (Fallback)",
        instructions=_get_fallback_instructions(),
        model=model,
        tools=[
            add_todo_item,
            complete_todo_item,
            get_todo_status,
            get_source_log,
            ingest_financial_document,
        ],
    )
    fallback_result = await Runner.run(
        fallback_agent,
        input=fallback_query,
        context=context,
        max_turns=8,
    )
    return str(fallback_result.final_output)


async def run_research_agent(topic: Optional[str] = None) -> str:
    """Run the research agent to generate investment advice."""
    brief = build_research_brief(topic)
    query = render_research_task(brief)

    bedrock_region, bedrock_model = _resolve_bedrock_settings()
    os.environ["AWS_REGION_NAME"] = bedrock_region  # LiteLLM expects this variable
    os.environ["AWS_REGION"] = bedrock_region
    os.environ["AWS_DEFAULT_REGION"] = bedrock_region

    model = LitellmModel(model=bedrock_model)
    context = ResearchRunContext(
        requested_topic=brief.topic,
        started_at=datetime.now(UTC).isoformat(),
    )

    mcp_timeout_seconds, max_turns, request_timeout_seconds = _resolve_runtime_limits()

    # Create and run the agent with MCP server
    try:
        with trace("Researcher"):
            async with create_playwright_mcp_server(
                timeout_seconds=mcp_timeout_seconds
            ) as playwright_mcp:
                agent = Agent[ResearchRunContext](
                    name="Alex Investment Researcher",
                    instructions=get_agent_instructions(),
                    model=model,
                    tools=[
                        add_todo_item,
                        complete_todo_item,
                        get_todo_status,
                        record_source,
                        get_source_log,
                        ingest_financial_document,
                    ],
                    mcp_servers=[playwright_mcp],
                )

                result = await asyncio.wait_for(
                    Runner.run(agent, input=query, context=context, max_turns=max_turns),
                    timeout=request_timeout_seconds,
                )

        return str(result.final_output)
    except (asyncio.TimeoutError, MaxTurnsExceeded, AgentsException, ModelBehaviorError) as e:
        logging.warning("Primary research flow failed, switching to fallback mode: %s", e)
        return await _run_fallback_agent(query=query, model=model, context=context)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "Alex Researcher",
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.post("/research")
async def research(request: ResearchRequest) -> str:
    """
    Generate investment research and advice.

    The agent will:
    1. Browse current financial websites for data
    2. Analyze the information found
    3. Store the analysis in the knowledge base

    If no topic is provided, the agent will pick a trending topic.
    """
    try:
        response = await run_research_agent(request.topic)
        return response
    except Exception as e:
        print(f"Error in research endpoint: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/research/auto")
async def research_auto():
    """
    Automated research endpoint for scheduled runs.
    Picks a trending topic automatically and generates research.
    Used by EventBridge Scheduler for periodic research updates.
    """
    try:
        # Always use agent's choice for automated runs
        response = await run_research_agent(topic=None)
        return {
            "status": "success",
            "timestamp": datetime.now(UTC).isoformat(),
            "message": "Automated research completed",
            "preview": response[:200] + "..." if len(response) > 200 else response,
        }
    except Exception as e:
        print(f"Error in automated research: {e}")
        return {"status": "error", "timestamp": datetime.now(UTC).isoformat(), "error": str(e)}


@app.get("/health")
async def health():
    """Detailed health check."""
    bedrock_region, bedrock_model = _resolve_bedrock_settings()

    # Debug container detection
    container_indicators = {
        "dockerenv": os.path.exists("/.dockerenv"),
        "containerenv": os.path.exists("/run/.containerenv"),
        "aws_execution_env": os.environ.get("AWS_EXECUTION_ENV", ""),
        "ecs_container_metadata": os.environ.get("ECS_CONTAINER_METADATA_URI", ""),
        "kubernetes_service": os.environ.get("KUBERNETES_SERVICE_HOST", ""),
    }

    return {
        "service": "Alex Researcher",
        "status": "healthy",
        "alex_api_configured": bool(os.getenv("ALEX_API_ENDPOINT") and os.getenv("ALEX_API_KEY")),
        "timestamp": datetime.now(UTC).isoformat(),
        "debug_container": container_indicators,
        "aws_region": os.environ.get("AWS_DEFAULT_REGION", "not set"),
        "bedrock_region": bedrock_region,
        "bedrock_model": bedrock_model,
    }


@app.get("/test-bedrock")
async def test_bedrock():
    """Test Bedrock connection directly."""
    try:
        import boto3

        bedrock_region, bedrock_model = _resolve_bedrock_settings()
        os.environ["AWS_REGION_NAME"] = bedrock_region
        os.environ["AWS_REGION"] = bedrock_region
        os.environ["AWS_DEFAULT_REGION"] = bedrock_region

        # Debug: Check what region boto3 is actually using
        session = boto3.Session()
        actual_region = session.region_name

        # Try to create Bedrock client explicitly in configured region
        boto3.client("bedrock-runtime", region_name=bedrock_region)

        # Debug: Try to list models to verify connection
        try:
            bedrock_client = boto3.client("bedrock", region_name=bedrock_region)
            models = bedrock_client.list_foundation_models()
            openai_models = [
                m["modelId"] for m in models["modelSummaries"] if "openai" in m["modelId"].lower()
            ]
        except Exception as list_error:
            openai_models = f"Error listing: {str(list_error)}"

        # Try basic model invocation with configured model
        model = LitellmModel(model=bedrock_model)

        agent = Agent(
            name="Test Agent",
            instructions="You are a helpful assistant. Be very brief.",
            model=model,
        )

        result = await Runner.run(agent, input="Say hello in 5 words or less", max_turns=1)

        return {
            "status": "success",
            "model": str(model.model),  # Use actual model from LitellmModel
            "region": actual_region,
            "configured_bedrock_region": bedrock_region,
            "response": result.final_output,
            "debug": {
                "boto3_session_region": actual_region,
                "available_openai_models": openai_models,
            },
        }
    except Exception as e:
        import traceback

        return {
            "status": "error",
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc(),
            "debug": {
                "boto3_session_region": session.region_name if "session" in locals() else "unknown",
                "env_vars": {
                    "AWS_REGION_NAME": os.environ.get("AWS_REGION_NAME"),
                    "AWS_REGION": os.environ.get("AWS_REGION"),
                    "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION"),
                },
            },
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
