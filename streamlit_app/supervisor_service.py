"""LangGraph multi-agent supervisor for Uber analytics.

Graph topology (single question)
---------------------------------
              ┌──────────────────────────────────────────────────┐
  User ──────►│                  supervisor                       │
              │  Routes to: gold / silver / ml / context /        │
              │             full_report / FINISH                   │
              └───┬────────────┬──────────┬──────────┬───────────┘
                  ▼            ▼          ▼          ▼
             gold_agent  silver_agent  ml_agent  context_agent
                  └────────────┴──────────┴──────────┘
                                    │
                             back to supervisor

Full-city report (sequential orchestration)
-------------------------------------------
  supervisor
       │ (detects "full report" intent)
       ▼
  full_report_node
       │  runs sub-agents in order:
       ├─► gold_agent   — KPIs & revenue
       ├─► silver_agent — operational deep dive
       ├─► ml_agent     — demand & surge forecasts
       ├─► context_agent— market context
       └─► synthesizer  — unified markdown report → END
"""

from __future__ import annotations

import time
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Tool declarations — thin wrappers around react_agent_service functions
# ---------------------------------------------------------------------------

def _make_tools():
    from langchain_core.tools import tool
    import react_agent_service as _r

    @tool
    def get_kpi_dashboard() -> dict:
        """Get platform-wide KPI aggregates: rides, revenue, avg fare, surge, rating, distance, cancellation rate."""
        return _r.get_kpi_dashboard()

    @tool
    def get_revenue_by_city(city: str) -> dict:
        """Get revenue, ride count, avg fare, surge, and rating for a single pickup city."""
        return _r.get_revenue_by_city(city)

    @tool
    def get_top_cities_by_revenue(limit: int = 10) -> dict:
        """Get top pickup cities ranked by total revenue. limit: number of cities (1–25)."""
        return _r.get_top_cities_by_revenue(limit)

    @tool
    def get_surge_patterns(hour_start: int = 0, hour_end: int = 23) -> dict:
        """Analyze average surge and ride volume by booking hour (0–23)."""
        return _r.get_surge_patterns(hour_start, hour_end)

    @tool
    def get_city_surge_comparison(cities: str) -> dict:
        """Compare surge, ride count, and revenue across a comma-separated list of cities."""
        return _r.get_city_surge_comparison(cities)

    @tool
    def get_demand_by_city(city: str) -> dict:
        """Get demand, cancellation rate, and surge metrics for a single pickup city."""
        return _r.get_demand_by_city(city)

    @tool
    def get_silver_city_deep_dive(city: str) -> dict:
        """Silver-layer city deep dive: vehicle mix, payment mix, status and cancellation breakdown."""
        return _r.get_silver_city_deep_dive(city)

    @tool
    def get_silver_recent_operational_signals(limit: int = 10) -> dict:
        """Recent sanitized ride signals from the silver layer — no PII. limit: 1–25."""
        return _r.get_silver_recent_operational_signals(limit)

    @tool
    def predict_city_demand(city: str, horizon_hours: int = 1) -> dict:
        """Predict near-term ride demand for a city. horizon_hours: forecast window (1–24)."""
        return _r.predict_city_demand(city, horizon_hours)

    @tool
    def predict_surge_pressure(city: str) -> dict:
        """Predict near-term surge pressure score (low/medium/high) for a city."""
        return _r.predict_surge_pressure(city)

    @tool
    def get_external_market_context(city: str) -> dict:
        """Retrieve local market context for a city from bundled reference data and RAG."""
        return _r.get_external_market_context(city)

    @tool
    def retrieve_operational_context(query: str) -> dict:
        """Semantic RAG search over project reference docs — vehicle types, cancellation codes, geography."""
        return _r.retrieve_operational_context(query)

    return (
        [get_kpi_dashboard, get_revenue_by_city, get_top_cities_by_revenue,
         get_surge_patterns, get_city_surge_comparison, get_demand_by_city],   # gold
        [get_silver_city_deep_dive, get_silver_recent_operational_signals],    # silver
        [predict_city_demand, predict_surge_pressure],                         # ml
        [get_external_market_context, retrieve_operational_context],           # context
    )


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_SUPERVISOR_PROMPT = """You are the supervisor for a multi-agent Uber analytics system.
Given the user's question, decide which specialist agent to call next:

  gold_agent    — KPIs, revenue totals, surge patterns, city rankings, demand aggregates
  silver_agent  — Enriched city deep dives, recent operational signals, vehicle/payment mix
  ml_agent      — Near-term demand forecasts, surge pressure scores
  context_agent — Market archetypes, city geography, vehicle types, cancellation codes, RAG
  full_report   — Comprehensive full-city report combining all four layers sequentially

Rules:
- Route to full_report when the user asks for a "full report", "complete analysis",
  "comprehensive overview", or "everything about" a city.
- Route to the single most relevant specialist agent for all other questions.
- After an agent responds, re-evaluate: route to another agent if the answer is
  incomplete, or FINISH if the question is fully answered.
- Never route to the same agent twice in one turn unless strictly necessary.
""".strip()

_GOLD_PROMPT = """You are the Gold analytics agent for an Uber operations dashboard.
Answer questions about KPIs, revenue, surge patterns, and demand using Gold-layer data.
Be concise and cite numbers. Do not write SQL. Do not access tables outside your tools.""".strip()

_SILVER_PROMPT = """You are the Silver analytics agent for an Uber operations dashboard.
Answer questions about enriched ride signals, vehicle mix, payment methods, and cancellation patterns.
Use silver-layer enriched data. Be concise and cite numbers. No PII.""".strip()

_ML_PROMPT = """You are the ML forecasting agent for an Uber operations dashboard.
Provide demand predictions and surge pressure assessments for cities.
Explain confidence levels and the method behind the forecast.""".strip()

_CONTEXT_PROMPT = """You are the context and knowledge agent for an Uber operations dashboard.
Retrieve market archetypes, city geography, vehicle type details, cancellation codes, and
architecture context. Use RAG retrieval when the question asks what, why, or how about
non-SQL topics.""".strip()

_REPORT_SYNTHESIZER_PROMPT = """You are a senior Uber operations analyst writing a comprehensive city market report.

Synthesize the data provided by four specialist agents into a structured markdown report.
Be specific with numbers. Focus on insights over raw data.
Highlight patterns, anomalies, and actionable recommendations.

Use exactly this structure:

# City Report: {city}

## Executive Summary
(3–4 sentences covering overall performance and standout characteristics)

## KPI Highlights
(Key metrics from the Gold layer — rides, revenue, fares, surge, ratings)

## Operational Patterns
(Silver-layer breakdown — vehicle type mix, payment trends, cancellation insights)

## Demand Outlook
(ML demand forecast and surge pressure assessment with confidence level)

## Market Context
(Market archetype, geographic positioning, key demand signals)

## Key Recommendations
(2–3 concrete, data-driven operational recommendations)
""".strip()

# Targeted questions sent to each sub-agent during sequential orchestration
_STEP_QUERIES: dict[str, str] = {
    "gold": (
        "Return complete KPI and revenue metrics for {city}: "
        "total rides, total revenue, avg fare, avg surge, avg rating, cancellation rate, "
        "and demand overview. Use get_kpi_dashboard and get_revenue_by_city."
    ),
    "silver": (
        "Provide a full silver-layer deep dive for {city}: "
        "vehicle type mix, payment method breakdown, ride status and cancellation reason mix, "
        "and the 5 most recent operational signals."
    ),
    "ml": (
        "Forecast demand and surge pressure for {city}: "
        "predicted rides for the next 3 hours and the current surge pressure band and score."
    ),
    "context": (
        "Get full market context for {city}: "
        "market archetype, key demand signals, city geography, and any relevant reference data."
    ),
}

_MEMBERS = ["gold_agent", "silver_agent", "ml_agent", "context_agent"]
_FINISH = "FINISH"


# ---------------------------------------------------------------------------
# Cached agent factory — shared by graph nodes and sequential orchestration
# Keyed by model name so each fallback model gets its own cached instance.
# ---------------------------------------------------------------------------

@lru_cache(maxsize=6)
def _get_agents(model_name: str) -> dict[str, Any]:
    """Build and cache the LLM + 4 sub-agents for a specific model."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langgraph.prebuilt import create_react_agent
    from config_utils import get_secret

    api_key = get_secret("GEMINI_API_KEY")
    llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, temperature=0)

    gold_tools, silver_tools, ml_tools, context_tools = _make_tools()

    return {
        "llm": llm,
        "gold": create_react_agent(llm, gold_tools, prompt=_GOLD_PROMPT),
        "silver": create_react_agent(llm, silver_tools, prompt=_SILVER_PROMPT),
        "ml": create_react_agent(llm, ml_tools, prompt=_ML_PROMPT),
        "context": create_react_agent(llm, context_tools, prompt=_CONTEXT_PROMPT),
    }


def _iter_models() -> list[str]:
    """Return models to try in order: configured primary first, then fallbacks."""
    from ai_service import FALLBACK_MODELS, get_gemini_model, DEFAULT_GEMINI_MODEL
    primary = get_gemini_model() or DEFAULT_GEMINI_MODEL
    return [primary] + [m for m in FALLBACK_MODELS if m != primary]


# ---------------------------------------------------------------------------
# Sequential orchestration helpers
# ---------------------------------------------------------------------------

def run_step(agent_key: str, city: str) -> str:
    """Invoke one sub-agent with a city-focused question, falling back through models on quota errors."""
    from langchain_core.messages import HumanMessage
    from ai_service import _is_quota_error

    question = _STEP_QUERIES[agent_key].format(city=city)
    models = _iter_models()
    last_exc: Exception | None = None

    for model in models:
        try:
            agents = _get_agents(model)
            result = agents[agent_key].invoke({"messages": [HumanMessage(content=question)]})
            return _extract_answer(result.get("messages", []))
        except Exception as exc:
            if _is_quota_error(exc) and model != models[-1]:
                last_exc = exc
                continue
            raise

    raise RuntimeError(f"All models quota-limited in run_step({agent_key}): {last_exc}")


def synthesize_city_report(city: str, sections: dict[str, str]) -> str:
    """Synthesize four sub-agent outputs into a unified markdown report, with model fallback."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from ai_service import _is_quota_error

    body = "\n\n".join(
        f"### {key.upper()} AGENT DATA:\n{text}"
        for key, text in sections.items()
        if text.strip()
    )
    models = _iter_models()
    last_exc: Exception | None = None

    for model in models:
        try:
            llm = _get_agents(model)["llm"]
            response = llm.invoke([
                SystemMessage(content=_REPORT_SYNTHESIZER_PROMPT.format(city=city)),
                HumanMessage(content=f"City: {city}\n\n{body}"),
            ])
            return _content_to_str(response.content)
        except Exception as exc:
            if _is_quota_error(exc) and model != models[-1]:
                last_exc = exc
                continue
            raise

    raise RuntimeError(f"All models quota-limited in synthesize_city_report: {last_exc}")


def answer_with_full_report(city: str) -> dict[str, Any]:
    """Run Gold → Silver → ML → Context sequentially, then synthesize a full city report."""
    city = (city or "").strip()
    if not city:
        return {"ok": False, "answer": "Specify a city name to generate a full report.", "metadata": {}}
    if not is_supervisor_configured():
        return {"ok": False, "answer": "Add Gemini and Databricks credentials to generate reports.", "metadata": {}}

    started_at = time.time()
    try:
        sections: dict[str, str] = {}
        for key in ("gold", "silver", "ml", "context"):
            sections[key] = run_step(key, city)

        report = synthesize_city_report(city, sections)
        primary = _iter_models()[0]
        return {
            "ok": True,
            "answer": report,
            "metadata": {
                "mode": "Sequential Full-City Report",
                "model": primary,
                "city": city,
                "agents_called": ["gold_agent", "silver_agent", "ml_agent", "context_agent", "synthesizer"],
                "steps_completed": list(sections.keys()),
                "execution_time_seconds": round(time.time() - started_at, 2),
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "answer": f"Report generation failed: {type(exc).__name__}: {exc}",
            "metadata": {},
        }


# ---------------------------------------------------------------------------
# LangGraph graph builder
# ---------------------------------------------------------------------------

@lru_cache(maxsize=6)
def _build_graph(model_name: str):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.types import Command
    from pydantic import BaseModel

    agents = _get_agents(model_name)
    llm = agents["llm"]

    # --- Routing model ---
    class Route(BaseModel):
        next: Literal[
            "gold_agent", "silver_agent", "ml_agent", "context_agent",
            "full_report", "FINISH"
        ]

    supervisor_llm = llm.with_structured_output(Route)

    def supervisor_node(state: MessagesState) -> Command:
        messages = [SystemMessage(content=_SUPERVISOR_PROMPT)] + state["messages"]
        route = supervisor_llm.invoke(messages)
        goto = route.next
        if goto == _FINISH:
            return Command(goto=END)
        return Command(goto=goto)

    # --- Sub-agent wrapper: run agent, return to supervisor ---
    def _wrap_agent(agent, name: str):
        def node(state: MessagesState) -> Command:
            result = agent.invoke(state)
            return Command(goto="supervisor", update={"messages": result["messages"]})
        node.__name__ = name
        return node

    # --- Full-report node: sequential orchestration ---
    class CityExtract(BaseModel):
        city: str = ""

    def full_report_node(state: MessagesState) -> Command:
        last_human = next(
            (m for m in reversed(state["messages"]) if getattr(m, "type", "") == "human"),
            None,
        )
        if not last_human:
            msg = AIMessage(content="Please specify a city name for the full report.")
            return Command(goto=END, update={"messages": [msg]})

        extraction = llm.with_structured_output(CityExtract).invoke([
            SystemMessage("Extract the US city name. Return empty string if none found."),
            HumanMessage(last_human.content),
        ])
        city = extraction.city.strip()
        if not city:
            msg = AIMessage(content="Please specify a city name for the full report.")
            return Command(goto=END, update={"messages": [msg]})

        result = answer_with_full_report(city)
        return Command(goto=END, update={"messages": [AIMessage(content=result["answer"])]})

    # --- Build graph ---
    builder = StateGraph(MessagesState)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("gold_agent", _wrap_agent(agents["gold"], "gold_agent"))
    builder.add_node("silver_agent", _wrap_agent(agents["silver"], "silver_agent"))
    builder.add_node("ml_agent", _wrap_agent(agents["ml"], "ml_agent"))
    builder.add_node("context_agent", _wrap_agent(agents["context"], "context_agent"))
    builder.add_node("full_report", full_report_node)

    builder.add_edge(START, "supervisor")

    return builder.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_supervisor_configured() -> bool:
    """Return True when both Gemini and Databricks credentials are available."""
    from react_agent_service import is_react_agent_configured
    return is_react_agent_configured()


def answer_with_supervisor(
    user_question: str,
    chat_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Route a question through the LangGraph supervisor and return a structured result."""
    question = (user_question or "").strip()
    if not question:
        return {"ok": False, "answer": "Ask an analytics question to run the supervisor.", "metadata": {}}
    if not is_supervisor_configured():
        return {
            "ok": False,
            "answer": "Supervisor is disabled. Add Gemini and Databricks credentials.",
            "metadata": {},
        }

    started_at = time.time()
    try:
        from langchain_core.messages import AIMessage, HumanMessage
        from ai_service import _is_quota_error

        history_msgs = []
        for item in (chat_history or [])[-6:]:
            role = item.get("role")
            content = str(item.get("content", ""))
            if role == "user":
                history_msgs.append(HumanMessage(content=content))
            elif role == "assistant":
                history_msgs.append(AIMessage(content=content))
        history_msgs.append(HumanMessage(content=question))

        models = _iter_models()
        last_exc: Exception | None = None

        for model in models:
            try:
                graph = _build_graph(model)
                result = graph.invoke({"messages": history_msgs})
                answer = _extract_answer(result.get("messages", []))
                agents_called = _detect_agents(result.get("messages", []))
                return {
                    "ok": True,
                    "answer": answer or "The supervisor returned an empty response.",
                    "metadata": {
                        "mode": "LangGraph Supervisor",
                        "model": model,
                        "agents_called": agents_called,
                        "tool_access": "supervisor → gold / silver / ml / context / full_report",
                        "execution_time_seconds": round(time.time() - started_at, 2),
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    },
                }
            except Exception as exc:
                if _is_quota_error(exc) and model != models[-1]:
                    last_exc = exc
                    continue
                raise

        return {
            "ok": False,
            "answer": f"All Gemini models are quota-limited. Try again later. Last error: {last_exc}",
            "metadata": {},
        }

    except ImportError as exc:
        return {
            "ok": False,
            "answer": f"Supervisor dependencies not installed: {getattr(exc, 'name', None) or type(exc).__name__}.",
            "metadata": {},
        }
    except Exception as exc:
        return {
            "ok": False,
            "answer": f"Supervisor unavailable: {type(exc).__name__}: {exc}",
            "metadata": {},
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_answer(messages: list) -> str:
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        if content and getattr(msg, "type", "") == "ai":
            if not getattr(msg, "tool_calls", None):
                return _content_to_str(content)
    return ""


def _content_to_str(content: Any) -> str:
    """Extract plain text from a string or a list of Gemini content blocks."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content", "")
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content).strip()


def _detect_agents(messages: list) -> list[str]:
    tool_to_agent = {
        "get_kpi_dashboard": "gold_agent",
        "get_revenue_by_city": "gold_agent",
        "get_top_cities_by_revenue": "gold_agent",
        "get_surge_patterns": "gold_agent",
        "get_city_surge_comparison": "gold_agent",
        "get_demand_by_city": "gold_agent",
        "get_silver_city_deep_dive": "silver_agent",
        "get_silver_recent_operational_signals": "silver_agent",
        "predict_city_demand": "ml_agent",
        "predict_surge_pressure": "ml_agent",
        "get_external_market_context": "context_agent",
        "retrieve_operational_context": "context_agent",
    }
    seen: list[str] = []
    for msg in messages:
        for tc in getattr(msg, "tool_calls", []) or []:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            if name:
                agent = tool_to_agent.get(name)
                if agent and agent not in seen:
                    seen.append(agent)
    return seen or ["supervisor"]


def _get_model_name() -> str:
    try:
        from ai_service import DEFAULT_GEMINI_MODEL, get_gemini_model
        return get_gemini_model() or DEFAULT_GEMINI_MODEL
    except Exception:
        return "gemini-2.5-flash"
