from databricks import sql
from dotenv import load_dotenv
load_dotenv()
import os
import time
import streamlit as st
import requests
from config_utils import get_secret


def _ensure_warehouse_running(poll_timeout: int = 60, poll_interval: int = 5) -> str:
    """Start the SQL warehouse if it is stopped, and block until it's RUNNING
    (or until poll_timeout elapses). Called once on app load.

    Returns one of: "running", "starting_timeout", "unknown" (status check failed).
    """
    host        = _get_secret("DATABRICKS_HOST")
    token       = _get_secret("DATABRICKS_TOKEN")
    http_path   = _get_secret("DATABRICKS_HTTP_PATH")

    # Extract warehouse ID from http_path
    # e.g. /sql/1.0/warehouses/c6f1ccf7eaf58c6c → c6f1ccf7eaf58c6c
    warehouse_id = http_path.strip("/").split("/")[-1]

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    status_url = f"{host}/api/2.0/sql/warehouses/{warehouse_id}"

    resp = requests.get(status_url, headers=headers)
    if resp.status_code != 200:
        return "unknown"

    state = resp.json().get("state", "")

    if state in ("STOPPED", "STOPPING"):
        requests.post(f"{host}/api/2.0/sql/warehouses/{warehouse_id}/start", headers=headers)
        state = "STARTING"

    elapsed = 0
    while state not in ("RUNNING",) and elapsed < poll_timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval
        resp = requests.get(status_url, headers=headers)
        if resp.status_code != 200:
            return "unknown"
        state = resp.json().get("state", "")

    return "running" if state == "RUNNING" else "starting_timeout"

# Module-level connection — reused across queries so we don't pay the
# Databricks HTTP handshake + auth cost on every single query call.
_conn = None


def _get_secret(key: str) -> str:
    """Read from st.secrets first (Streamlit Cloud), fall back to os.getenv (local)."""
    return get_secret(key)


def get_connection():
    global _conn
    if _conn is None:
        _conn = sql.connect(
            server_hostname=_get_secret("DATABRICKS_HOST"),
            http_path=_get_secret("DATABRICKS_HTTP_PATH"),
            access_token=_get_secret("DATABRICKS_TOKEN")
        )
    return _conn


def query(sql_str: str, parameters: list | tuple | dict | None = None) -> list[dict]:
    """Run a SQL query, reusing the cached connection. Reconnects once on error."""
    global _conn
    for attempt in range(2):
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                if parameters is None:
                    cursor.execute(sql_str)
                else:
                    cursor.execute(sql_str, parameters)
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]
        except Exception:
            if attempt == 0:
                _conn = None  # stale connection — force reconnect and retry
            else:
                raise


@st.cache_data(ttl=10)
def get_pipeline_status() -> dict:
    """Get current pipeline run status from Databricks API."""
    import requests
    token = _get_secret("DATABRICKS_TOKEN")
    host  = _get_secret("DATABRICKS_HOST")
    pipeline_id = _get_secret("PIPELINE_ID")

    try:
        resp = requests.get(
            f"{host}/api/2.0/pipelines/{pipeline_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "state":   data.get("state", "UNKNOWN"),
                "name":    data.get("name", ""),
                "latest":  data.get("latest_updates", [{}])[0] if data.get("latest_updates") else {}
            }
    except Exception as e:
        return {"state": "UNKNOWN", "latest": {}}
    return {"state": "UNKNOWN", "latest": {}}

# ── KPI Cards ─────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_kpis() -> dict:
    rows = query("""
        SELECT
            COUNT(*)                        AS total_rides,
            ROUND(SUM(f.total_fare), 2)     AS total_revenue,
            ROUND(AVG(f.total_fare), 2)     AS avg_fare,
            ROUND(AVG(f.surge_multiplier), 2) AS avg_surge,
            ROUND(AVG(f.rating), 2)         AS avg_rating,
            ROUND(AVG(f.distance_miles), 2) AS avg_distance,
            ROUND(100.0 * SUM(CASE WHEN b.ride_status_id = 2 THEN 1 ELSE 0 END) / COUNT(*), 1) AS cancellation_rate
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_booking b ON f.ride_id = b.ride_id
    """)
    return rows[0]


# ── Live Feed ──────────────────────────────────────────────────────

@st.cache_data(ttl=10)
def get_live_feed(limit: int = 10) -> list[dict]:
    return query(f"""
        SELECT
            f.ride_id,
            b.booking_timestamp,
            p.passenger_name,
            d.driver_name,
            d.driver_rating,
            v.vehicle_type,
            l.pickup_city,
            f.total_fare,
            f.distance_miles,
            f.duration_minutes,
            f.surge_multiplier,
            f.rating
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_passenger  p ON f.passenger_id   = p.passenger_id
        LEFT JOIN uber.gold.dim_driver     d ON f.driver_id      = d.driver_id
        LEFT JOIN uber.gold.dim_vehicle    v ON f.vehicle_id     = v.vehicle_id
        LEFT JOIN uber.gold.dim_booking    b ON f.ride_id        = b.ride_id
        LEFT JOIN uber.gold.dim_location   l ON f.pickup_city_id = l.pickup_city_id
        ORDER BY b.booking_timestamp DESC
        LIMIT {limit}
    """)


# ── Charts ─────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_rides_by_city() -> list[dict]:
    return query("""
        SELECT
            l.pickup_city AS city,
            COUNT(*) AS total_rides,
            ROUND(SUM(f.total_fare), 2) AS total_revenue
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_location l ON f.pickup_city_id = l.pickup_city_id
        GROUP BY l.pickup_city
        ORDER BY total_rides DESC
        LIMIT 10
    """)


@st.cache_data(ttl=60)
def get_rides_by_vehicle_type() -> list[dict]:
    return query("""
        SELECT
            v.vehicle_type,
            COUNT(*) AS total_rides,
            ROUND(AVG(f.total_fare), 2) AS avg_fare
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_vehicle v ON f.vehicle_id = v.vehicle_id
        GROUP BY v.vehicle_type
        ORDER BY total_rides DESC
    """)


@st.cache_data(ttl=60)
def get_rides_by_payment() -> list[dict]:
    return query("""
        SELECT
            pm.payment_method,
            COUNT(*) AS total_rides
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_payment pm ON f.payment_method_id = pm.payment_method_id
        GROUP BY pm.payment_method
        ORDER BY total_rides DESC
    """)


@st.cache_data(ttl=60)
def get_surge_distribution() -> list[dict]:
    return query("""
        SELECT
            ROUND(surge_multiplier, 1) AS surge_bucket,
            COUNT(*) AS ride_count
        FROM uber.gold.fact
        WHERE surge_multiplier IS NOT NULL
        GROUP BY surge_bucket
        ORDER BY surge_bucket
    """)


# ── Driver Insights ────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_top_drivers(limit: int = 5) -> list[dict]:
    return query(f"""
        SELECT
            d.driver_name,
            ROUND(AVG(d.driver_rating), 2)               AS driver_rating,
            COUNT(*)                                      AS total_rides,
            ROUND(SUM(COALESCE(f.total_fare, 0)), 2)     AS total_revenue,
            ROUND(AVG(COALESCE(f.tip_amount, 0)), 2)     AS avg_tip
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_driver d ON f.driver_id = d.driver_id
        WHERE d.driver_name IS NOT NULL
        GROUP BY d.driver_name
        ORDER BY total_rides DESC
        LIMIT {limit}
    """)


# ── Regional Revenue ───────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_revenue_by_region() -> list[dict]:
    return query("""
        SELECT
            mc.region,
            COUNT(*)                              AS total_rides,
            ROUND(SUM(COALESCE(f.total_fare, 0)), 2) AS total_revenue
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_location l  ON f.pickup_city_id = l.pickup_city_id
        LEFT JOIN uber.bronze.map_cities mc ON l.pickup_city    = mc.city
        WHERE mc.region IS NOT NULL
        GROUP BY mc.region
        ORDER BY total_revenue DESC
    """)


# ── Map Data ───────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_pickup_locations(limit: int = 200) -> list[dict]:
    return query(f"""
        SELECT
            b.pickup_latitude,
            b.pickup_longitude,
            b.pickup_address,
            f.total_fare
        FROM uber.gold.fact f
        LEFT JOIN uber.gold.dim_booking b ON f.ride_id = b.ride_id
        WHERE b.pickup_latitude IS NOT NULL
          AND b.pickup_longitude IS NOT NULL
          AND b.pickup_latitude BETWEEN -90 AND 90
          AND b.pickup_longitude BETWEEN -180 AND 180
        LIMIT {limit}
    """)
