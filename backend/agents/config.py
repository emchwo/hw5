"""Model, paths, tool access, and safety limits for the Campus Customs team.

- MODEL_NAME is fixed to gpt-6-luna for every agent (no override).
- build_model(): PydanticAI model that calls gpt-6-luna through Portkey.
- TOOL_ACCESS: which MCP tools each agent may see (least privilege).
- GATED_TOOLS: MCP calls that need a human yes before they run.
- Limits: tokens / requests / tool calls per ticket and per run, hand-off depth.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
PROMPTS_DIR = BACKEND_DIR / "prompts"
MCP_SERVER = PROJECT_DIR / "mcp_server" / "server.py"
DB_ORIGINAL = PROJECT_DIR / "data" / "campus_customs.db"
# Env overrides exist only so tests can use a scratch copy instead of the real files.
DB_WORKING = Path(os.environ.get("CAMPUS_DB", PROJECT_DIR / "data" / "campus_customs_new.db"))
AUDIT_PATH = Path(os.environ.get("CAMPUS_AUDIT", PROJECT_DIR / "output" / "audit_trail.json"))

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(PROJECT_DIR.parent / ".env")  # course root (AI Foundations/.env)

# Only gpt-6-luna is allowed for every agent. Deliberately not read from env.
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

AGENT_NAMES = ("boss", "inventory", "accounting", "facilities", "customer_service")

# Which MCP tools each agent can see. update_ticket is used only by the runner.
TOOL_ACCESS: dict[str, set[str]] = {
    "boss": {"get_tickets", "check_restock", "manage_payables", "quote_bulk_order"},
    "inventory": {"get_tickets", "check_restock", "quote_bulk_order", "save_draft"},
    "accounting": {
        "get_tickets", "check_restock", "manage_payables", "quote_bulk_order",
        "place_purchase_order", "record_discount",
    },
    "facilities": {"get_tickets", "manage_payables", "save_draft"},
    "customer_service": {"get_tickets", "check_restock", "quote_bulk_order", "save_draft"},
}

# Calls that move money or approve a discount. Only these agents may make them,
# and only after a human says yes.
GATED_TOOLS = {"place_purchase_order", "record_discount"}  # + manage_payables(action="pay")
MONEY_AGENTS = {"accounting"}

# --------------------------------------------------------------------------- #
# Safety limits (see output/harness.md, Safety section)
# --------------------------------------------------------------------------- #
TICKET_TOKEN_LIMIT = 100_000   # all agents on one ticket, input + output tokens
TICKET_REQUEST_LIMIT = 40      # model calls per ticket
TICKET_TOOL_CALL_LIMIT = 40    # tool calls (MCP + hand_off) per ticket
RUN_TOKEN_LIMIT = 300_000      # whole run across tickets; no new ticket starts past this
MAX_HANDOFF_DEPTH = 2          # boss -> specialist -> specialist, no deeper
MAX_HANDOFFS_PER_TICKET = 8
AGENT_RETRIES = 3              # tool / output retries per agent run


def ticket_usage_limits() -> UsageLimits:
    return UsageLimits(
        request_limit=TICKET_REQUEST_LIMIT,
        tool_calls_limit=TICKET_TOOL_CALL_LIMIT,
        total_tokens_limit=TICKET_TOKEN_LIMIT,
    )


def require_api_key() -> str:
    key = os.getenv("PORTKEY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is not set. Add it to .env in HW 5 or its parent folder.")
    return key


_model: OpenAIResponsesModel | None = None


def build_model() -> OpenAIResponsesModel:
    """One shared gpt-6-luna model (Responses API via Portkey) for every agent."""
    global _model
    if _model is None:
        client = AsyncOpenAI(
            api_key=require_api_key(),
            base_url=PORTKEY_BASE_URL,
            default_headers={"x-portkey-provider": "openai"},
        )
        _model = OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
    return _model


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
