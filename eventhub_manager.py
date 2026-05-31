"""
eventhub_manager.py — Shared Azure SDK module
──────────────────────────────────────────────
Used by both local scripts (start_eventhub.py, stop_eventhub.py)
and the Streamlit control panel (control.py).

Key Vault is the single source of truth for CONNECTION_STRING and
LISTENER_CONNECTION_STRING. The app always fetches them at runtime,
so no manual secrets paste is ever needed after start/stop.
"""
import os
import requests as req
from config_utils import get_secret

def _get_secret(key: str) -> str:
    return get_secret(key)

from azure.identity import ClientSecretCredential
from azure.mgmt.eventhub import EventHubManagementClient
from azure.keyvault.secrets import SecretClient

RESOURCE_GROUP  = _get_secret("AZURE_RESOURCE_GROUP")  or "rg-uber"
NAMESPACE       = _get_secret("AZURE_EVENTHUB_NAMESPACE") or "rg-uber-events"
EVENTHUB        = _get_secret("AZURE_EVENTHUB_NAME")      or "ubertopic"
LOCATION        = _get_secret("AZURE_LOCATION")           or "eastus"
KEY_VAULT_URL   = _get_secret("AZURE_KEY_VAULT_URL")

# Key Vault secret names — these are the keys stored in the vault
KV_CONNECTION_STRING          = "CONNECTION-STRING"
KV_LISTENER_CONNECTION_STRING = "LISTENER-CONNECTION-STRING"
KV_EVENT_HUBNAME              = "EVENT-HUBNAME"


def _get_credential() -> ClientSecretCredential:
    """Shared credential used for both EventHub mgmt and Key Vault."""
    return ClientSecretCredential(
        tenant_id=_get_secret("AZURE_TENANT_ID"),
        client_id=_get_secret("AZURE_CLIENT_ID"),
        client_secret=_get_secret("AZURE_CLIENT_SECRET")
    )


def _get_mgmt_client() -> EventHubManagementClient:
    return EventHubManagementClient(
        credential=_get_credential(),
        subscription_id=_get_secret("AZURE_SUBSCRIPTION_ID")
    )


def _get_kv_client() -> SecretClient:
    return SecretClient(
        vault_url=KEY_VAULT_URL,
        credential=_get_credential()
    )


# ── Key Vault helpers ─────────────────────────────────────────────

def kv_set(name: str, value: str) -> None:
    """Write a secret to Key Vault."""
    _get_kv_client().set_secret(name, value)


OFFLINE_SENTINEL = "OFFLINE"

def kv_clear(name: str) -> None:
    """Mark a Key Vault secret as inactive using a sentinel value."""
    _get_kv_client().set_secret(name, OFFLINE_SENTINEL)

def kv_get(name: str) -> str | None:
    """Read a secret from Key Vault. Returns None if not found or offline."""
    try:
        value = _get_kv_client().get_secret(name).value
        if not value or value == OFFLINE_SENTINEL:
            return None
        return value
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────

def get_connection_strings() -> tuple[str | None, str | None]:
    """
    Fetch CONNECTION_STRING and LISTENER_CONNECTION_STRING from Key Vault.
    Returns (sender_conn, listener_conn) — either may be None/empty if offline.
    Call this at runtime instead of reading from st.secrets.
    """
    sender   = kv_get(KV_CONNECTION_STRING)
    listener = kv_get(KV_LISTENER_CONNECTION_STRING)
    return sender, listener


def start_eventhub(on_status=None) -> tuple[str, str]:
    """
    Provision EventHub namespace, topic, and SAS policies.
    Writes connection strings directly to Key Vault.
    Returns (sender_connection_string, listener_connection_string).
    """
    def log(msg):
        if on_status:
            on_status(msg)

    client = _get_mgmt_client()

    log("Creating EventHub namespace...")
    client.namespaces.begin_create_or_update(
        resource_group_name=RESOURCE_GROUP,
        namespace_name=NAMESPACE,
        parameters={
            "location": LOCATION,
            "sku": {"name": "Standard", "tier": "Standard", "capacity": 1}
        }
    ).result()
    log("Namespace ready")

    log("Creating EventHub topic...")
    client.event_hubs.create_or_update(
        resource_group_name=RESOURCE_GROUP,
        namespace_name=NAMESPACE,
        event_hub_name=EVENTHUB,
        parameters={"message_retention_in_days": 1, "partition_count": 2}
    )
    log("Topic ready")

    log("Creating access policies...")
    client.namespaces.create_or_update_authorization_rule(
        resource_group_name=RESOURCE_GROUP,
        namespace_name=NAMESPACE,
        authorization_rule_name="SenderPolicy",
        parameters={"rights": ["Send"]}
    )
    client.namespaces.create_or_update_authorization_rule(
        resource_group_name=RESOURCE_GROUP,
        namespace_name=NAMESPACE,
        authorization_rule_name="ListenerPolicy",
        parameters={"rights": ["Listen"]}
    )

    log("Fetching connection strings...")
    sender_keys   = client.namespaces.list_keys(RESOURCE_GROUP, NAMESPACE, "SenderPolicy")
    listener_keys = client.namespaces.list_keys(RESOURCE_GROUP, NAMESPACE, "ListenerPolicy")

    sender_conn   = sender_keys.primary_connection_string
    listener_conn = listener_keys.primary_connection_string

    # ── Write to Key Vault ────────────────────────────────────────
    log("Writing connection strings to Key Vault...")
    kv_set(KV_CONNECTION_STRING, sender_conn)
    kv_set(KV_LISTENER_CONNECTION_STRING, listener_conn)
    kv_set(KV_EVENT_HUBNAME, EVENTHUB)
    log("Key Vault updated")

    return sender_conn, listener_conn


def stop_eventhub(on_status=None) -> None:
    """
    Delete the EventHub namespace and clear Key Vault secrets.
    Billing stops immediately.
    """
    def log(msg):
        if on_status:
            on_status(msg)

    client = _get_mgmt_client()
    log("Deleting namespace...")
    client.namespaces.begin_delete(
        resource_group_name=RESOURCE_GROUP,
        namespace_name=NAMESPACE
    ).result()
    log("Namespace deleted — billing stopped")

    # ── Clear Key Vault ───────────────────────────────────────────
    log("Clearing Key Vault secrets...")
    kv_clear(KV_CONNECTION_STRING)
    kv_clear(KV_LISTENER_CONNECTION_STRING)
    kv_clear(KV_EVENT_HUBNAME)
    log("Key Vault cleared")


def update_pipeline_connection_string(listener_conn_str: str, on_status=None) -> None:
    """Update the EventHub connection string in the Databricks DLT pipeline config."""
    def log(msg):
        if on_status:
            on_status(msg)

    host        = _get_secret("DATABRICKS_HOST")
    token       = _get_secret("DATABRICKS_TOKEN")
    pipeline_id = _get_secret("PIPELINE_ID")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    log("Updating Databricks pipeline config...")
    resp = req.get(f"{host}/api/2.0/pipelines/{pipeline_id}", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to get pipeline settings: {resp.status_code}")

    pipeline = resp.json()
    config   = pipeline.get("spec", {}).get("configuration", {})
    config["connection_string"] = listener_conn_str

    updated_spec = pipeline["spec"]
    updated_spec["configuration"] = config

    resp = req.put(
        f"{host}/api/2.0/pipelines/{pipeline_id}",
        headers=headers,
        json=updated_spec
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to update pipeline: {resp.status_code}")
    log("Pipeline config updated")


def trigger_pipeline(full_refresh: bool = False):
    """Trigger a Databricks DLT pipeline update. Returns the API response."""
    host        = _get_secret("DATABRICKS_HOST")
    token       = _get_secret("DATABRICKS_TOKEN")
    pipeline_id = _get_secret("PIPELINE_ID")

    return req.post(
        f"{host}/api/2.0/pipelines/{pipeline_id}/updates",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"full_refresh": full_refresh}
    )
