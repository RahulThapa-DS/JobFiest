import logging
import re
import json
from typing import Any, Generator
from pydantic import BaseModel, Field

from google.adk.workflow import Workflow, START, node
from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool, McpToolset
from google.adk.tools.mcp_tool import StdioConnectionParams
from mcp import StdioServerParameters
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App
from google.genai import types

from app.config import config

logger = logging.getLogger("jobfiest.agent")

# ==============================================================================
# Pydantic Schemas for Structured I/O
# ==============================================================================

class JobItem(BaseModel):
    title: str = Field(description="The job title")
    company: str = Field(description="The company offering the job")
    location: str = Field(description="The location of the job")
    description: str = Field(description="Brief description of the job role")
    url: str = Field(description="URL or contact page to apply for the job")

class JobSearchOutput(BaseModel):
    jobs: list[JobItem] = Field(description="List of found job postings")

class RankedJobItem(BaseModel):
    title: str = Field(description="The job title")
    company: str = Field(description="The company offering the job")
    location: str = Field(description="The location of the job")
    suitability_score: int = Field(description="A score from 1-100 indicating how well it matches the search query and location")
    reason: str = Field(description="Short reason why this job is suitable or ranked this way")

class JobRankingOutput(BaseModel):
    ranked_jobs: list[RankedJobItem] = Field(description="List of ranked job postings")

# ==============================================================================
# MCP Server Toolset Connection
# ==============================================================================

mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "app.mcp_server"],
        )
    )
)

# ==============================================================================
# Sub-Agents (with wired MCP Toolset)
# ==============================================================================

job_search_agent = LlmAgent(
    name="job_search_agent",
    model=config.model,
    instruction="""You are a job search specialist.
Your goal is to find job listings matching the user's job title and location, and query salary ranges.
Use the tools in the toolset to find jobs and salaries.
Return the search results as a clear text list or JSON-like structure of jobs, including their title, company, location, description, URL, and salary range.""",
    tools=[mcp_toolset],
)

job_ranker_agent = LlmAgent(
    name="job_ranker_agent",
    model=config.model,
    instruction="""You are a job ranking specialist.
Your goal is to take a raw list of job postings, analyze them against the user's original query, and rank them by suitability.
Use the tools to get company reviews and check commute time if starting_from city is known.
Provide a suitability score (1-100) and a concise, personalized explanation for each job.
Return the ranked list of jobs as text.""",
    tools=[mcp_toolset],
)

# ==============================================================================
# Orchestrator Agent (with AgentTools)
# ==============================================================================

orchestrator_agent = LlmAgent(
    name="orchestrator_agent",
    model=config.model,
    instruction="""You are the JobFiest Coordinator.
Your task is to coordinate finding and ranking job listings for the user based on their requested job title and location.
1. Call job_search_agent with the requested job title and location.
2. Call job_ranker_agent with the retrieved jobs list to rank and format them.
Ensure the final response is a beautiful, structured Markdown list of the ranked jobs, showing titles, companies, locations, suitability scores, ratings, and reasons.""",
    tools=[AgentTool(job_search_agent), AgentTool(job_ranker_agent)],
)

# ==============================================================================
# Workflow Function Nodes (ADK 2.0 Graph API)
# ==============================================================================

@node
def security_checkpoint(ctx: Context, node_input: Any) -> Event:
    """Performs security and safety checks on user input."""
    text = ""
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text or ""
    elif isinstance(node_input, str):
        text = node_input
    elif isinstance(node_input, dict):
        text = node_input.get("text", "") or ""

    # Prompt injection check
    injection_keywords = ["ignore previous instructions", "system prompt", "jailbreak", "override instructions", "bypass"]
    for keyword in injection_keywords:
        if keyword in text.lower():
            audit_log = {
                "severity": "CRITICAL",
                "event": "PROMPT_INJECTION_DETECTED",
                "keyword": keyword,
                "input_snippet": text[:50]
            }
            logger.warning(json.dumps(audit_log))
            return Event(output="Security Check failed: Prompt injection attempt detected.", route="security_failed")

    # Domain specific rule
    illegal_keywords = ["hacker", "exploit", "weapons", "drugs", "illegal"]
    for kw in illegal_keywords:
        if kw in text.lower():
            audit_log = {
                "severity": "WARNING",
                "event": "DOMAIN_RULE_VIOLATION",
                "reason": f"Inappropriate job search keyword: {kw}",
                "input_snippet": text[:50]
            }
            logger.warning(json.dumps(audit_log))
            return Event(output=f"Security Check failed: Inappropriate search criteria '{kw}' is not allowed.", route="security_failed")

    # PII scrubbing
    scrubbed_text = text
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
    
    if re.search(email_pattern, scrubbed_text):
        scrubbed_text = re.sub(email_pattern, "[REDACTED_EMAIL]", scrubbed_text)
        logger.info("PII Scrubbing: Redacted email address.")
    if re.search(phone_pattern, scrubbed_text):
        scrubbed_text = re.sub(phone_pattern, "[REDACTED_PHONE]", scrubbed_text)
        logger.info("PII Scrubbing: Redacted phone number.")

    ctx.state["query"] = scrubbed_text
    
    audit_log = {
        "severity": "INFO",
        "event": "SECURITY_CHECK_PASSED",
        "input_snippet": scrubbed_text[:50]
    }
    logger.info(json.dumps(audit_log))
    
    return Event(output=scrubbed_text, route="__DEFAULT__")

@node
def hitl_check(ctx: Context, node_input: Any) -> Generator[RequestInput | Event, None, None]:
    """Checks if preferred location is available, triggers HITL if missing."""
    query = ctx.state.get("query", "")
    
    if ctx.resume_inputs and "ask_location" in ctx.resume_inputs:
        location = ctx.resume_inputs["ask_location"]
        ctx.state["location"] = location
        yield Event(output=f"Find jobs for: '{query}' in location: '{location}'")
        return

    # Check if location is already present in query
    has_location = "in " in query.lower() or "remote" in query.lower() or "at " in query.lower()
    
    if not has_location:
        yield RequestInput(
            interrupt_id="ask_location",
            message="Please specify a preferred location for the job search (e.g. 'Remote', 'San Francisco', 'Anywhere'):"
        )
        return
    
    # Try to extract location if present
    location = "Anywhere"
    if "remote" in query.lower():
        location = "Remote"
    elif "in " in query.lower():
        parts = query.lower().split("in ")
        if len(parts) > 1:
            location = parts[-1].strip().title()
    elif "at " in query.lower():
        parts = query.lower().split("at ")
        if len(parts) > 1:
            location = parts[-1].strip().title()
            
    ctx.state["location"] = location
    yield Event(output=f"Find jobs for: '{query}' in location: '{location}'")

@node
def security_error(node_input: str) -> Generator[Event, None, None]:
    """Handles security failures gracefully."""
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=f"❌ {node_input}")]))
    yield Event(output={"error": node_input})

@node
def final_output(node_input: Any) -> Generator[Event, None, None]:
    """Passes the final orchestrator response to the UI."""
    text = ""
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text or ""
    elif isinstance(node_input, str):
        text = node_input
    elif isinstance(node_input, dict):
        text = node_input.get("text", "") or str(node_input)
    else:
        text = str(node_input)

    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=text)]))
    yield Event(output=text)

# ==============================================================================
# Workflow Construction
# ==============================================================================

root_agent = Workflow(
    name="jobfiest_workflow",
    edges=[
        (START, security_checkpoint),
        (security_checkpoint, {"__DEFAULT__": hitl_check, "security_failed": security_error}),
        (hitl_check, orchestrator_agent),
        (orchestrator_agent, final_output),
        (security_error, final_output)
    ]
)

app = App(
    root_agent=root_agent,
    name="app",
)
