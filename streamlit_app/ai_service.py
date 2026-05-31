import json
import os
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv
from config_utils import get_secret

load_dotenv(override=True)


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# Ordered fallback chain — tried in sequence when a model's free-tier quota is exhausted.
FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]
FACT_TABLE_COLUMNS = [
    "ride_id",
    "pickup_city_id",
    "payment_method_id",
    "driver_id",
    "passenger_id",
    "vehicle_id",
    "distance_miles",
    "duration_minutes",
    "base_fare",
    "distance_fare",
    "time_fare",
    "surge_multiplier",
    "total_fare",
    "tip_amount",
    "rating",
    "base_rate",
    "per_mile",
    "per_minute",
]

SYSTEM_PROMPT = f"""
You are the AI Operations Analyst for an Uber real-time data engineering dashboard.

Use only the dashboard context provided by the app. Do not invent data, do not write SQL,
and do not imply that you can inspect raw Databricks tables. If a question cannot be
answered from the supplied aggregate context, say that the dashboard context does not
contain enough information.

Allowed context:
- KPI aggregates
- rides and revenue by pickup city
- rides by vehicle type
- rides by payment method
- surge multiplier distribution
- revenue and rides by region
- top-driver aggregate rows
- sanitized recent ride summaries with no passenger or driver names

Fact table schema glossary, for metric meaning only:
{", ".join(FACT_TABLE_COLUMNS)}

Answer like a concise operations analyst. Use concrete numbers when they are present.
For executive insights, return a complete dashboard readout with short sections
covering revenue, demand concentration, surge pressure, trip economics, ratings,
regional patterns, driver/recent-ride signals, and operational anomalies.
""".strip()


def get_gemini_model() -> str:
    return _get_secret("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL


def is_configured() -> bool:
    return bool(_get_secret("GEMINI_API_KEY"))


def build_dashboard_context(data: dict[str, Any]) -> dict[str, Any]:
    """Build a compact, aggregate-only payload for Gemini."""
    return {
        "kpis": _clean_value(data.get("kpis", {})),
        "rides_by_city": _clean_rows(data.get("by_city", []), limit=25),
        "rides_by_vehicle_type": _clean_rows(data.get("by_vehicle", []), limit=15),
        "rides_by_payment_method": _clean_rows(data.get("by_payment", []), limit=15),
        "surge_distribution": _clean_rows(data.get("surge", []), limit=20),
        "revenue_by_region": _clean_rows(data.get("by_region", []), limit=15),
        "top_drivers": _clean_rows(data.get("drivers", []), limit=15),
        "recent_rides": _sanitize_live_feed(data.get("live_feed", []), limit=25),
    }


def build_insights_prompt(context: dict[str, Any]) -> str:
    return (
        "Generate a complete executive insight brief for the current dashboard. "
        "Stay grounded in the JSON context and do not omit major populated sections. "
        "Use this format:\n"
        "1. Executive summary: 2-3 bullets.\n"
        "2. Metric drivers: revenue, demand concentration, surge, fare, distance, rating.\n"
        "3. Segment readout: city, vehicle, payment, region, and driver signals when present.\n"
        "4. Operational watchouts: anomalies, cancellations, low ratings, high surge, or sparse data.\n"
        "5. Recommended actions: 2-3 specific next moves.\n"
        "Keep it concise but complete; include concrete numbers from context.\n\n"
        f"Dashboard context:\n{_to_json(context)}"
    )


def build_chat_messages(
    context: dict[str, Any],
    chat_history: list[dict[str, str]],
    user_question: str,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "user",
            "content": (
                "Use this dashboard JSON context for the rest of this conversation. "
                "Acknowledge it only by answering the next user question.\n\n"
                f"{_to_json(context)}"
            ),
        }
    ]
    messages.extend(_trim_chat_history(chat_history, max_messages=8))
    messages.append({"role": "user", "content": user_question})
    return messages


def generate_insights(data: dict[str, Any]) -> tuple[bool, str]:
    if not is_configured():
        return False, "Gemini is disabled. Add GEMINI_API_KEY to Streamlit secrets or .env."

    context = build_dashboard_context(data)
    return _call_gemini(
        [{"role": "user", "content": build_insights_prompt(context)}],
        max_tokens=1400,
    )


def answer_question(
    data: dict[str, Any],
    chat_history: list[dict[str, str]],
    user_question: str,
) -> tuple[bool, str]:
    if not is_configured():
        return False, "Gemini is disabled. Add GEMINI_API_KEY to Streamlit secrets or .env."
    if not user_question.strip():
        return False, "Ask a dashboard question to get an AI answer."

    context = build_dashboard_context(data)
    return _call_gemini(
        build_chat_messages(context, chat_history, user_question.strip()),
        max_tokens=900,
    )


def _is_quota_error(exc: Exception) -> bool:
    """Return True for 429 / free-tier quota exhaustion errors from any Gemini SDK."""
    msg = str(exc).lower()
    typename = type(exc).__name__.lower()
    return (
        "429" in msg
        or "quota" in msg
        or "resource_exhausted" in msg
        or "resourceexhausted" in typename
        or "too many requests" in msg
    )


def _call_gemini(messages: list[dict[str, str]], max_tokens: int) -> tuple[bool, str]:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return False, "Gemini SDK is not installed. Run pip install -r requirements.txt."

    api_key = _get_secret("GEMINI_API_KEY")
    primary = get_gemini_model()
    models_to_try = [primary] + [m for m in FALLBACK_MODELS if m != primary]

    last_exc: Exception | None = None
    for model in models_to_try:
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=_messages_to_prompt(messages),
                config=types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=0.2,
                    system_instruction=SYSTEM_PROMPT,
                ),
            )
            text = getattr(response, "text", "").strip()
            return True, text or "Gemini returned an empty response."
        except Exception as exc:
            if _is_quota_error(exc) and model != models_to_try[-1]:
                last_exc = exc
                continue
            return False, f"Gemini is unavailable: {type(exc).__name__}: {exc}"

    return False, f"All Gemini models are quota-limited. Last error: {last_exc}"


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    parts = []
    for message in messages:
        role = "Analyst" if message["role"] == "assistant" else "User"
        parts.append(f"{role}: {message['content']}")
    return "\n\n".join(parts)


def _get_secret(key: str) -> str | None:
    return get_secret(key)


def _sanitize_live_feed(rows: Any, limit: int) -> list[dict[str, Any]]:
    allowed = {
        "booking_timestamp",
        "vehicle_type",
        "pickup_city",
        "total_fare",
        "distance_miles",
        "duration_minutes",
        "surge_multiplier",
        "rating",
        "driver_rating",
    }
    clean_rows = []
    for row in list(rows or [])[:limit]:
        if not isinstance(row, dict):
            continue
        clean_rows.append({key: _clean_value(row.get(key)) for key in allowed if key in row})
    return clean_rows


def _clean_rows(rows: Any, limit: int) -> list[dict[str, Any]]:
    clean_rows = []
    for row in list(rows or [])[:limit]:
        if isinstance(row, dict):
            clean_rows.append({str(key): _clean_value(value) for key, value in row.items()})
    return clean_rows


def _trim_chat_history(chat_history: list[dict[str, str]], max_messages: int) -> list[dict[str, str]]:
    allowed_roles = {"user", "assistant"}
    clean = [
        {"role": item["role"], "content": str(item["content"])}
        for item in chat_history
        if item.get("role") in allowed_roles and item.get("content")
    ]
    return clean[-max_messages:]


def _clean_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _clean_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_value(item) for item in value]
    return value


def _to_json(value: Any) -> str:
    return json.dumps(_clean_value(value), indent=2, sort_keys=True, default=str)
