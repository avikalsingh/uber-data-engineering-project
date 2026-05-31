"""LangChain ReAct-style analytics agent backed by read-only Databricks tools."""

from __future__ import annotations

import json
import time
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from ai_service import DEFAULT_GEMINI_MODEL, get_gemini_model
from config_utils import get_secret

MAX_LIMIT = 25
MAX_CITY_COMPARISON = 10
MAX_PREDICTION_HOURS = 24

SYSTEM_PROMPT = """
You are a read-only Uber operations analytics agent.

Route each user question to the best specialized tool layer:
- Gold tools for KPIs, revenue, demand totals, and executive aggregates.
- Silver tools for cleaned/enriched operational detail, vehicle/payment/status mix,
  cancellation reasons, and recent sanitized ride signals.
- ML prediction tools for short-horizon demand and surge forecasts.
- External context tools for market/region context from local reference data.

You may answer only by using the curated tools provided to you. Do not write SQL,
do not claim access to tables outside the tools, and do not request or expose
passenger or driver names. Synthesize tool results into rich contextual insight,
using concrete numbers when present. Say when the tools do not return enough data.
Call retrieve_operational_context whenever a question asks "what", "why", "how", or
"explain" about topics that cannot be answered from SQL data alone, such as vehicle
types, cancellation codes, city geography, or platform architecture.
""".strip()


def is_react_agent_configured() -> bool:
    """Return True when both Gemini and Databricks credentials are available."""
    required = (
        "GEMINI_API_KEY",
        "DATABRICKS_HOST",
        "DATABRICKS_TOKEN",
        "DATABRICKS_HTTP_PATH",
    )
    return all(bool(get_secret(key)) for key in required)


def get_revenue_by_city(city: str) -> dict[str, Any]:
    """Get revenue, ride count, fare, and surge metrics for one pickup city."""
    try:
        city = _validate_city(city)
    except ValueError as exc:
        return {"error": str(exc)}

    rows = _run_query(
        """
        SELECT
            l.pickup_city AS city,
            COUNT(*) AS total_rides,
            ROUND(SUM(COALESCE(f.total_fare, 0)), 2) AS total_revenue,
            ROUND(AVG(COALESCE(f.total_fare, 0)), 2) AS avg_fare,
            ROUND(AVG(COALESCE(f.surge_multiplier, 1)), 2) AS avg_surge,
            ROUND(AVG(f.rating), 2) AS avg_rating
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_location l ON f.pickup_city_id = l.pickup_city_id
        WHERE lower(l.pickup_city) = lower(?)
        GROUP BY l.pickup_city
        """,
        [city],
    )
    if not rows:
        return {"city": city, "message": "No revenue data found for this city."}
    return _clean_value(rows[0])


def get_top_cities_by_revenue(limit: int = 10) -> dict[str, Any]:
    """Get top pickup cities ranked by total revenue."""
    try:
        limit = _validate_limit(limit)
    except ValueError as exc:
        return {"error": str(exc)}

    rows = _run_query(
        """
        SELECT
            l.pickup_city AS city,
            COUNT(*) AS total_rides,
            ROUND(SUM(COALESCE(f.total_fare, 0)), 2) AS total_revenue,
            ROUND(AVG(COALESCE(f.total_fare, 0)), 2) AS avg_fare,
            ROUND(AVG(COALESCE(f.surge_multiplier, 1)), 2) AS avg_surge,
            ROUND(AVG(f.rating), 2) AS avg_rating
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_location l ON f.pickup_city_id = l.pickup_city_id
        WHERE l.pickup_city IS NOT NULL
        GROUP BY l.pickup_city
        ORDER BY total_revenue DESC
        LIMIT ?
        """,
        [limit],
    )
    return {
        "limit": limit,
        "top_cities": [
            {"rank": index + 1, **_clean_value(row)}
            for index, row in enumerate(rows)
        ],
    }


def get_surge_patterns(hour_start: int = 0, hour_end: int = 23) -> dict[str, Any]:
    """Analyze average surge and ride volume by booking hour."""
    try:
        hour_start, hour_end = _validate_hour_range(hour_start, hour_end)
    except ValueError as exc:
        return {"error": str(exc)}

    rows = _run_query(
        """
        SELECT
            hour(b.booking_timestamp) AS booking_hour,
            COUNT(*) AS total_rides,
            ROUND(AVG(COALESCE(f.surge_multiplier, 1)), 2) AS avg_surge,
            ROUND(MAX(COALESCE(f.surge_multiplier, 1)), 2) AS peak_surge,
            ROUND(SUM(COALESCE(f.total_fare, 0)), 2) AS total_revenue
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_booking b ON f.ride_id = b.ride_id
        WHERE b.booking_timestamp IS NOT NULL
          AND hour(b.booking_timestamp) BETWEEN ? AND ?
        GROUP BY hour(b.booking_timestamp)
        ORDER BY booking_hour
        """,
        [hour_start, hour_end],
    )
    return {
        "hour_start": hour_start,
        "hour_end": hour_end,
        "patterns": _clean_value(rows),
    }


def get_city_surge_comparison(cities: str) -> dict[str, Any]:
    """Compare surge, ride count, and revenue across a comma-separated city list."""
    try:
        city_list = _validate_city_list(cities)
    except ValueError as exc:
        return {"error": str(exc)}

    placeholders = ", ".join(["?"] * len(city_list))
    rows = _run_query(
        f"""
        SELECT
            l.pickup_city AS city,
            COUNT(*) AS total_rides,
            ROUND(AVG(COALESCE(f.surge_multiplier, 1)), 2) AS avg_surge,
            ROUND(MAX(COALESCE(f.surge_multiplier, 1)), 2) AS peak_surge,
            ROUND(SUM(COALESCE(f.total_fare, 0)), 2) AS total_revenue
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_location l ON f.pickup_city_id = l.pickup_city_id
        WHERE lower(l.pickup_city) IN ({placeholders})
        GROUP BY l.pickup_city
        ORDER BY avg_surge DESC
        """,
        [city.lower() for city in city_list],
    )
    return {"cities": city_list, "comparison": _clean_value(rows)}


def get_demand_by_city(city: str) -> dict[str, Any]:
    """Get demand and cancellation metrics for one pickup city."""
    try:
        city = _validate_city(city)
    except ValueError as exc:
        return {"error": str(exc)}

    rows = _run_query(
        """
        SELECT
            l.pickup_city AS city,
            COUNT(*) AS total_rides,
            SUM(CASE WHEN b.ride_status_id = 2 THEN 1 ELSE 0 END) AS cancelled_rides,
            SUM(CASE WHEN b.ride_status_id != 2 OR b.ride_status_id IS NULL THEN 1 ELSE 0 END) AS non_cancelled_rides,
            ROUND(100.0 * SUM(CASE WHEN b.ride_status_id = 2 THEN 1 ELSE 0 END) / COUNT(*), 1) AS cancellation_rate,
            ROUND(AVG(COALESCE(f.surge_multiplier, 1)), 2) AS avg_surge
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_location l ON f.pickup_city_id = l.pickup_city_id
        LEFT JOIN uber.gold.dim_booking b ON f.ride_id = b.ride_id
        WHERE lower(l.pickup_city) = lower(?)
        GROUP BY l.pickup_city
        """,
        [city],
    )
    if not rows:
        return {"city": city, "message": "No demand data found for this city."}
    return _clean_value(rows[0])


def get_kpi_dashboard() -> dict[str, Any]:
    """Get platform-wide KPI aggregates for rides, revenue, fares, surge, and rating."""
    rows = _run_query(
        """
        SELECT
            COUNT(*) AS total_rides,
            ROUND(SUM(COALESCE(f.total_fare, 0)), 2) AS total_revenue,
            ROUND(AVG(COALESCE(f.total_fare, 0)), 2) AS avg_fare,
            ROUND(AVG(COALESCE(f.surge_multiplier, 1)), 2) AS avg_surge,
            ROUND(AVG(f.rating), 2) AS avg_rating,
            ROUND(AVG(f.distance_miles), 2) AS avg_distance,
            ROUND(100.0 * SUM(CASE WHEN b.ride_status_id = 2 THEN 1 ELSE 0 END) / COUNT(*), 1) AS cancellation_rate
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_booking b ON f.ride_id = b.ride_id
        """
    )
    return _clean_value(rows[0] if rows else {})


def get_silver_city_deep_dive(city: str) -> dict[str, Any]:
    """Use silver enriched data for city-level vehicle, payment, status, and cancellation insights."""
    try:
        city = _validate_city(city)
    except ValueError as exc:
        return {"error": str(exc)}

    overview = _run_query(
        """
        SELECT
            pickup_city AS city,
            state,
            region,
            COUNT(*) AS total_rides,
            ROUND(SUM(COALESCE(total_fare, 0)), 2) AS total_revenue,
            ROUND(AVG(COALESCE(distance_miles, 0)), 2) AS avg_distance_miles,
            ROUND(AVG(COALESCE(duration_minutes, 0)), 2) AS avg_duration_minutes,
            ROUND(AVG(COALESCE(surge_multiplier, 1)), 2) AS avg_surge,
            ROUND(AVG(rating), 2) AS avg_rating,
            ROUND(AVG(driver_rating), 2) AS avg_driver_rating
        FROM uber.silver.silver_obt
        WHERE lower(pickup_city) = lower(?)
        GROUP BY pickup_city, state, region
        """,
        [city],
    )
    if not overview:
        return {"city": city, "message": "No silver-layer data found for this city."}

    vehicle_mix = _run_query(
        """
        SELECT
            vehicle_type,
            COUNT(*) AS rides,
            ROUND(AVG(COALESCE(total_fare, 0)), 2) AS avg_fare,
            ROUND(AVG(COALESCE(surge_multiplier, 1)), 2) AS avg_surge
        FROM uber.silver.silver_obt
        WHERE lower(pickup_city) = lower(?)
          AND vehicle_type IS NOT NULL
        GROUP BY vehicle_type
        ORDER BY rides DESC
        LIMIT 8
        """,
        [city],
    )
    payment_mix = _run_query(
        """
        SELECT
            payment_method,
            COUNT(*) AS rides
        FROM uber.silver.silver_obt
        WHERE lower(pickup_city) = lower(?)
          AND payment_method IS NOT NULL
        GROUP BY payment_method
        ORDER BY rides DESC
        LIMIT 8
        """,
        [city],
    )
    status_mix = _run_query(
        """
        SELECT
            COALESCE(ride_status, 'Unknown') AS ride_status,
            COALESCE(cancellation_reason, 'None') AS cancellation_reason,
            COUNT(*) AS rides
        FROM uber.silver.silver_obt
        WHERE lower(pickup_city) = lower(?)
        GROUP BY COALESCE(ride_status, 'Unknown'), COALESCE(cancellation_reason, 'None')
        ORDER BY rides DESC
        LIMIT 8
        """,
        [city],
    )
    return {
        "layer": "silver",
        "city": city,
        "overview": _clean_value(overview[0]),
        "vehicle_mix": _clean_value(vehicle_mix),
        "payment_mix": _clean_value(payment_mix),
        "status_mix": _clean_value(status_mix),
    }


def get_silver_recent_operational_signals(limit: int = 10) -> dict[str, Any]:
    """Use silver enriched data for recent sanitized operational signals without PII."""
    try:
        limit = _validate_limit(limit)
    except ValueError as exc:
        return {"error": str(exc)}

    rows = _run_query(
        """
        SELECT
            booking_timestamp,
            pickup_city,
            state,
            region,
            vehicle_type,
            ride_status,
            cancellation_reason,
            ROUND(COALESCE(total_fare, 0), 2) AS total_fare,
            ROUND(COALESCE(distance_miles, 0), 2) AS distance_miles,
            duration_minutes,
            ROUND(COALESCE(surge_multiplier, 1), 2) AS surge_multiplier,
            rating
        FROM uber.silver.silver_obt
        WHERE booking_timestamp IS NOT NULL
        ORDER BY booking_timestamp DESC
        LIMIT ?
        """,
        [limit],
    )
    return {"layer": "silver", "limit": limit, "recent_signals": _clean_value(rows)}


def predict_city_demand(city: str, horizon_hours: int = 1) -> dict[str, Any]:
    """Predict near-term ride demand for a city using recent silver-layer demand and surge signals."""
    try:
        city = _validate_city(city)
        horizon_hours = _validate_prediction_hours(horizon_hours)
    except ValueError as exc:
        return {"error": str(exc)}

    rows = _run_query(
        """
        SELECT
            COUNT(*) AS rides_last_6h,
            ROUND(COUNT(*) / 6.0, 2) AS avg_rides_per_hour,
            ROUND(AVG(COALESCE(surge_multiplier, 1)), 2) AS avg_surge_last_6h,
            ROUND(100.0 * SUM(CASE WHEN ride_status_id = 2 THEN 1 ELSE 0 END) / GREATEST(COUNT(*), 1), 1) AS cancellation_rate_last_6h
        FROM uber.silver.silver_obt
        WHERE lower(pickup_city) = lower(?)
          AND booking_timestamp >= current_timestamp() - INTERVAL 6 HOURS
        """,
        [city],
    )
    metrics = _clean_value(rows[0] if rows else {})
    avg_hourly = float(metrics.get("avg_rides_per_hour") or 0)
    predicted_rides = round(avg_hourly * horizon_hours, 1)
    confidence = "low" if avg_hourly == 0 else "medium"
    return {
        "layer": "ml_predictions",
        "prediction_type": "near_term_city_demand",
        "city": city,
        "horizon_hours": horizon_hours,
        "predicted_rides": predicted_rides,
        "confidence": confidence,
        "method": "Heuristic forecast from trailing 6-hour silver-layer ride rate.",
        "features": metrics,
    }


def predict_surge_pressure(city: str) -> dict[str, Any]:
    """Predict near-term surge pressure for a city from recent demand, surge, and cancellation signals."""
    try:
        city = _validate_city(city)
    except ValueError as exc:
        return {"error": str(exc)}

    rows = _run_query(
        """
        SELECT
            COUNT(*) AS rides_last_6h,
            ROUND(AVG(COALESCE(surge_multiplier, 1)), 2) AS avg_surge_last_6h,
            ROUND(MAX(COALESCE(surge_multiplier, 1)), 2) AS peak_surge_last_6h,
            ROUND(100.0 * SUM(CASE WHEN ride_status_id = 2 THEN 1 ELSE 0 END) / GREATEST(COUNT(*), 1), 1) AS cancellation_rate_last_6h
        FROM uber.silver.silver_obt
        WHERE lower(pickup_city) = lower(?)
          AND booking_timestamp >= current_timestamp() - INTERVAL 6 HOURS
        """,
        [city],
    )
    metrics = _clean_value(rows[0] if rows else {})
    avg_surge = float(metrics.get("avg_surge_last_6h") or 1)
    peak_surge = float(metrics.get("peak_surge_last_6h") or avg_surge)
    cancellation_rate = float(metrics.get("cancellation_rate_last_6h") or 0)
    pressure_score = round((avg_surge - 1) * 55 + (peak_surge - 1) * 25 + cancellation_rate * 0.2, 1)
    if pressure_score >= 45:
        pressure_band = "high"
    elif pressure_score >= 20:
        pressure_band = "medium"
    else:
        pressure_band = "low"
    return {
        "layer": "ml_predictions",
        "prediction_type": "surge_pressure",
        "city": city,
        "pressure_band": pressure_band,
        "pressure_score": pressure_score,
        "method": "Heuristic score from trailing 6-hour surge, peak surge, and cancellation pressure.",
        "features": metrics,
    }


def get_external_market_context(city: str) -> dict[str, Any]:
    """Get local market context for a city from external reference data bundled with the project."""
    try:
        city = _validate_city(city)
    except ValueError as exc:
        return {"error": str(exc)}

    cities = _load_city_reference()
    match = next((row for row in cities if str(row.get("city", "")).lower() == city.lower()), None)
    if not match:
        return {
            "layer": "external_context",
            "city": city,
            "message": "No bundled market context found for this city.",
        }

    rag_chunks: list[dict[str, Any]] = []
    try:
        import rag_service
        if rag_service.is_rag_configured():
            candidates = rag_service.retrieve(f"market context for {city}")
            rag_chunks = [c for c in candidates if c.get("score", 0) >= 0.6]
    except Exception:
        pass

    if rag_chunks:
        return {
            "layer": "external_context",
            "city": match["city"],
            "state": match.get("state"),
            "region": match.get("region"),
            "context_signals": rag_chunks,
            "source": "RAG retrieval from project reference documents.",
        }

    return {
        "layer": "external_context",
        "city": match["city"],
        "state": match.get("state"),
        "region": match.get("region"),
        "market_archetype": _market_archetype(match["city"], match.get("region")),
        "context_signals": _market_signals(match["city"], match.get("region")),
        "source": "Data/map_cities.json plus deterministic market heuristics; not live web data.",
    }


def retrieve_operational_context(query: str) -> dict[str, Any]:
    """Retrieve relevant operational context from project reference documents using semantic search."""
    try:
        import rag_service
        if not rag_service.is_rag_configured():
            return {"error": "RAG is not configured. GEMINI_API_KEY is required."}
        chunks = rag_service.retrieve(query, top_k=4)
        if not chunks:
            return {"query": query, "results": [], "message": "No relevant context found."}
        return {"query": query, "results": chunks}
    except Exception as exc:
        return {"error": f"RAG retrieval failed: {type(exc).__name__}: {exc}"}


def answer_with_react_agent(
    user_question: str,
    chat_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Answer a question through the LangChain agent and curated Databricks tools."""
    question = (user_question or "").strip()
    if not question:
        return {"ok": False, "answer": "Ask an analytics question to run the ReAct agent.", "metadata": {}}
    if not is_react_agent_configured():
        return {
            "ok": False,
            "answer": "ReAct Agent is disabled. Add Gemini and Databricks credentials to Streamlit secrets or .env.",
            "metadata": {},
        }

    started_at = time.time()
    try:
        agent = _get_agent()
        messages = _build_agent_messages(chat_history or [], question)
        result = agent.invoke({"messages": messages})
        answer = _extract_agent_text(result)
        return {
            "ok": True,
            "answer": answer or "The ReAct agent returned an empty response.",
            "metadata": {
                "mode": "LangChain ReAct Agent",
                "model": get_gemini_model() or DEFAULT_GEMINI_MODEL,
                "tool_access": "router: silver, gold, ml_predictions, external_context",
                "available_tools": [tool.__name__ for tool in _get_tools()],
                "execution_time_seconds": round(time.time() - started_at, 2),
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            },
        }
    except ImportError as exc:
        return {
            "ok": False,
            "answer": f"ReAct Agent dependencies are not installed: {exc.name or type(exc).__name__}. Run pip install -r requirements.txt.",
            "metadata": {},
        }
    except Exception as exc:
        return {
            "ok": False,
            "answer": f"ReAct Agent is unavailable right now: {type(exc).__name__}: {exc}",
            "metadata": {},
        }


@lru_cache(maxsize=1)
def _get_agent() -> Any:
    from langchain.agents import create_agent
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
        model=get_gemini_model() or DEFAULT_GEMINI_MODEL,
        google_api_key=get_secret("GEMINI_API_KEY"),
        temperature=0,
    )
    return create_agent(
        model=llm,
        tools=_get_tools(),
        system_prompt=SYSTEM_PROMPT,
    )


def _get_tools() -> list[Any]:
    return [
        get_revenue_by_city,
        get_top_cities_by_revenue,
        get_surge_patterns,
        get_city_surge_comparison,
        get_demand_by_city,
        get_kpi_dashboard,
        get_silver_city_deep_dive,
        get_silver_recent_operational_signals,
        predict_city_demand,
        predict_surge_pressure,
        get_external_market_context,
        retrieve_operational_context,
    ]


def _run_query(sql_str: str, parameters: list | tuple | dict | None = None) -> list[dict[str, Any]]:
    import db

    return db.query(sql_str, parameters)


def _build_agent_messages(chat_history: list[dict[str, str]], question: str) -> list[dict[str, str]]:
    messages = [
        {"role": item["role"], "content": str(item["content"])}
        for item in chat_history[-6:]
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    messages.append({"role": "user", "content": question})
    return messages


def _extract_agent_text(result: Any) -> str:
    if isinstance(result, dict):
        if isinstance(result.get("output"), str):
            return result["output"].strip()
        messages = result.get("messages")
        if messages:
            last = messages[-1]
            content = getattr(last, "content", None)
            if content is None and isinstance(last, dict):
                content = last.get("content")
            return _content_to_text(content)
    return _content_to_text(result)


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content).strip()


def _validate_city(city: str) -> str:
    city = str(city or "").strip()
    if len(city) < 2:
        raise ValueError("City name must be at least 2 characters.")
    if len(city) > 80:
        raise ValueError("City name is too long.")
    return city


def _validate_city_list(cities: str) -> list[str]:
    city_list = []
    for city in str(cities or "").split(","):
        clean = _validate_city(city)
        if clean.lower() not in {existing.lower() for existing in city_list}:
            city_list.append(clean)
    if len(city_list) > MAX_CITY_COMPARISON:
        raise ValueError(f"Compare at most {MAX_CITY_COMPARISON} cities at a time.")
    return city_list


def _validate_limit(limit: int) -> int:
    try:
        clean = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("Limit must be a number.") from exc
    if clean < 1 or clean > MAX_LIMIT:
        raise ValueError(f"Limit must be between 1 and {MAX_LIMIT}.")
    return clean


def _validate_hour_range(hour_start: int, hour_end: int) -> tuple[int, int]:
    try:
        start = int(hour_start)
        end = int(hour_end)
    except (TypeError, ValueError) as exc:
        raise ValueError("Hours must be numbers from 0 to 23.") from exc
    if not 0 <= start <= 23 or not 0 <= end <= 23:
        raise ValueError("Hours must be between 0 and 23.")
    if start > end:
        start, end = end, start
    return start, end


def _validate_prediction_hours(horizon_hours: int) -> int:
    try:
        clean = int(horizon_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError("Prediction horizon must be a number of hours.") from exc
    if clean < 1 or clean > MAX_PREDICTION_HOURS:
        raise ValueError(f"Prediction horizon must be between 1 and {MAX_PREDICTION_HOURS} hours.")
    return clean


@lru_cache(maxsize=1)
def _load_city_reference() -> list[dict[str, Any]]:
    project_root = Path(__file__).resolve().parents[1]
    with open(project_root / "Data" / "map_cities.json", encoding="utf-8") as handle:
        return json.load(handle)


def _market_archetype(city: str, region: str | None) -> str:
    city_lower = city.lower()
    if city_lower in {"new york", "chicago", "philadelphia"}:
        return "dense urban commuter market"
    if city_lower in {"las vegas"}:
        return "tourism and event-driven market"
    if city_lower in {"san diego", "san jose"}:
        return "coastal technology and leisure market"
    if city_lower in {"houston", "dallas", "san antonio", "phoenix"}:
        return "car-oriented growth market"
    return f"{region or 'general'} regional market"


def _market_signals(city: str, region: str | None) -> list[str]:
    signals = {
        "New York": ["airport and commuter peaks", "high late-night demand", "weather-sensitive supply imbalance"],
        "Las Vegas": ["event calendar sensitivity", "hotel and airport corridors", "nightlife-driven peaks"],
        "Chicago": ["commuter peaks", "winter weather sensitivity", "airport corridor demand"],
        "Houston": ["sprawling trip distances", "airport and energy-sector commute demand"],
        "Phoenix": ["longer distance trips", "seasonal heat effects", "airport and resort demand"],
        "Philadelphia": ["commuter and university demand", "regional rail and airport corridors"],
        "San Antonio": ["tourism corridor demand", "family and leisure trip mix"],
        "San Diego": ["coastal leisure demand", "airport and event demand"],
        "Dallas": ["airport hub demand", "business district commute peaks"],
        "San Jose": ["technology commute patterns", "airport and regional business demand"],
    }
    return signals.get(city, [f"{region or 'regional'} demand patterns", "local event and commute sensitivity"])


def _clean_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _clean_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_value(item) for item in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
