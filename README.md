# Uber AI Operations Platform

> A multi-agent AI analytics platform that answers natural language questions about live Uber operations — grounded in a real-time data pipeline on Azure and Databricks.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://uber-data-engineering-project.streamlit.app)
[![GitHub](https://img.shields.io/badge/GitHub-avikalsingh-181717?style=flat-square&logo=github&logoColor=white)](https://github.com/avikalsingh/uber-data-engineering-project)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-2.5--flash-4285F4?style=flat-square&logo=google&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-1C3C3C?style=flat-square&logo=langchain&logoColor=white)
![Databricks](https://img.shields.io/badge/Databricks-DLT-FF3621?style=flat-square&logo=databricks&logoColor=white)

🔗 **Live Demo:** https://uber-data-engineering-project.streamlit.app
📁 **GitHub:** https://github.com/avikalsingh/uber-data-engineering-project

---

## What this is

Most AI demos are backed by static datasets or synthetic context. This one is different: a LangGraph multi-agent system that queries a live Databricks Gold layer in real time, grounded by a RAG layer over project documents, and surfaced through a Streamlit dashboard that streams fresh ride data from Azure EventHub every session.

Ask it anything about operations:

> *"Which city had the highest surge multiplier this week?"*
> *"Compare cancellation rates between UberX and Black across the West region."*
> *"Generate a full operations report for Chicago."*
> *"What's driving the revenue dip in the Southeast?"*

The AI doesn't hallucinate data — it calls curated, read-only tools that hit real SQL tables, then synthesizes the results into analyst-grade answers.

---

## 🤖 AI Architecture

Four layers, each with a distinct role.

```
┌──────────────────────────────────────────────────────────────┐
│                    User Question                              │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              LangGraph Supervisor Agent                       │
│   Routes to the right specialist based on question intent    │
└───┬──────────────┬──────────────┬──────────────┬────────────┘
    ▼              ▼              ▼              ▼
gold_agent   silver_agent    ml_agent    context_agent
(KPIs /      (operational    (demand /   (RAG — city geo,
 revenue)     deep dive)      surge       vehicle types,
                              forecast)   architecture)
    └──────────────┴──────────────┴──────────────┘
                           │
                    back to supervisor
                           │
             ┌─────────────▼──────────────┐
             │   full_report_node          │
             │  (sequential orchestration  │
             │   → synthesized markdown)   │
             └────────────────────────────┘
```

### Layer 1 — Simple Chat (`ai_service.py`)
Gemini 2.5-flash receives pre-aggregated KPI context and answers conversational questions about the current dashboard state. Fast, low-latency, zero Databricks calls. Includes an automatic multi-model fallback chain so it stays live even when free-tier quota is exhausted:

```
gemini-2.5-flash → gemini-2.0-flash → gemini-2.0-flash-lite → gemini-1.5-flash → gemini-1.5-flash-8b
```

### Layer 2 — ReAct Agent (`react_agent_service.py`)
LangChain ReAct agent with curated, read-only tool groups that hit Databricks SQL directly:

| Tool group | What it queries |
|---|---|
| Gold tools | KPI aggregates, city revenue, surge trends, driver leaderboard |
| Silver tools | Operational detail, vehicle/payment/status mix, cancellation breakdown |
| ML tools | Short-horizon demand and surge forecasts |
| Context tools | City geography, vehicle type definitions, platform architecture |

The agent reasons across multiple tool calls before answering — it won't guess when a query requires joining two data sources.

### Layer 3 — Multi-Agent Supervisor (`supervisor_service.py`)
LangGraph supervisor graph. Each incoming question is classified and routed to the right specialist sub-agent. For full-city or full-platform report requests, a dedicated orchestration node runs all four sub-agents sequentially and synthesizes a single unified markdown report.

### Layer 4 — RAG Service (`rag_service.py`)
Project reference documents (`README.md`, dimension lookup JSON files) are embedded using `gemini-embedding-001`. At query time, cosine similarity retrieves the top-k most relevant chunks, which are injected as grounding context before the agent reasons. Embeddings are cached to `.rag_cache.json` to avoid re-embedding on restart.

**All AI layers are read-only. No SQL writes. No passenger or driver names are exposed to any model.**

---

## 📊 Dashboard

Live at **https://uber-data-engineering-project.streamlit.app**

### AI Chat — Two entry points

**Floating chat** (bottom-right corner)
Persistent widget backed by the simple Gemini layer. Answers questions from pre-aggregated KPI context in under a second. Best for quick operational questions: revenue totals, top cities, surge averages.

**Agentic chat** (FAB button — bottom-left)
Full ReAct / LangGraph supervisor agent. Triggers live Databricks queries per message. Best for deep dives: multi-city comparisons, cancellation root cause, full operations reports.

### Analytics Tab
- KPI cards: total rides, revenue, avg fare, cancellation rate, avg rating
- Rides and revenue by city (bar chart)
- Vehicle type distribution (donut)
- Payment method breakdown
- Surge multiplier distribution
- Regional revenue breakdown
- Live ride feed
- Pickup heatmap (Folium)
- Top drivers leaderboard

### Pipeline Control Tab *(password protected)*
- Start / Stop Azure EventHub (provisions/deletes namespace via Azure SDK)
- Trigger Databricks DLT pipeline update
- Real-time DLT pipeline status bar
- Medallion schema overview

---

## 🏗 Data Infrastructure

The AI answers are only as good as the data underneath. The pipeline ensures the Gold layer the agents query is always fresh, deduplicated, and schema-stable.

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│  Ride Generator  │────▶│  Azure EventHub  │────▶│  Databricks DLT      │
│  (Python/Faker)  │     │  (Kafka Protocol)│     │  Delta Live Tables   │
└─────────────────┘     └──────────────────┘     └──────────┬───────────┘
                                                             │
                         ┌─────────────────┐                ▼
                         │  Azure Data      │    ┌───────────────────────┐
                         │  Factory (Batch) │───▶│  Medallion: Bronze    │
                         └─────────────────┘    │  → Silver → Gold      │
                                                 └──────────┬────────────┘
                                                            │
                                                            ▼
                                                 ┌───────────────────────┐
                                                 │  AI Agent Tools       │
                                                 │  (read-only SQL)      │
                                                 └───────────────────────┘
```

### Medallion Schema

**Bronze (9 tables)** — Raw ingestion, no transformations.

| Table | Description |
|---|---|
| `bulk_rides` | 2,000 historical rides loaded via Azure Data Factory |
| `rides_raw` | Live EventHub stream (Kafka) |
| `streaming_rides_archive` | Persistent backup — survives EventHub delete/recreate cycles |
| `map_cities` | 40 US cities across 4 regions with coordinates |
| `map_cancellation_reasons` | 4 cancellation reason codes |
| `map_payment_methods` | 4 payment types |
| `map_ride_statuses` | 2 ride status codes |
| `map_vehicle_makes` | 7 vehicle manufacturers |
| `map_vehicle_types` | 5 service tiers |

**Silver (2 tables)** — Cleaned and deduplicated.

| Table | Description |
|---|---|
| `stg_rides` | Merged bulk + stream + archive — deduplicated |
| `silver_obt` | One Big Table — all dimensions joined for downstream consumption |

**Gold (7 tables — Star Schema)** — What the AI agents query.

| Table | Type | Description |
|---|---|---|
| `fact` | Fact | Ride measures + foreign keys |
| `dim_passenger` | SCD Type 1 | Passenger profiles |
| `dim_driver` | SCD Type 1 | Driver profiles |
| `dim_vehicle` | SCD Type 1 | Vehicle registry |
| `dim_booking` | SCD Type 1 | Booking details + coordinates |
| `dim_payment` | SCD Type 1 | Payment methods |
| `dim_location` | SCD Type 2 | City dimension — tracks historical city changes |

---

## 🛠 Tech Stack

| Category | Technology |
|---|---|
| **LLM** | Google Gemini 2.5-flash (multi-model fallback chain) |
| **Agent framework** | LangChain ReAct agent |
| **Multi-agent orchestration** | LangGraph supervisor graph |
| **Embeddings / RAG** | Gemini Embeddings (`gemini-embedding-001`) + cosine similarity |
| **Dashboard** | Streamlit (Streamlit Cloud) |
| **Stream processing** | Databricks Delta Live Tables (DLT) |
| **Analytical store** | Delta Lake (Unity Catalog), star schema |
| **Streaming ingestion** | Azure EventHub (Standard, Kafka Protocol) |
| **Batch ingestion** | Azure Data Factory |
| **Secrets** | Azure Key Vault |
| **Infrastructure auth** | Azure Service Principal |
| **Data generation** | Python + Faker |
| **Language** | Python 3.11+ |

---

## 🔑 Key Design Decisions

**Agents query live Gold tables, not a snapshot**
The ReAct and supervisor agents call Databricks SQL at answer time. There is no intermediate caching layer between the agent tools and the Gold tables — answers reflect the most recent DLT pipeline run.

**Curated tool surface, not raw SQL access**
Agents cannot write SQL or access tables outside the defined tool functions. Each tool is a named, parameterized function with a fixed query shape. This keeps answers accurate and prevents prompt injection from escalating to data access.

**RAG as grounding, not retrieval-only**
The RAG layer embeds operational reference documents (city metadata, vehicle type definitions, platform architecture). When an agent gets a question like "what cities are in the West region?" it retrieves the right chunk rather than hallucinating or querying the wrong table.

**Multi-model fallback keeps AI available at zero cost**
The simple chat layer walks a five-model fallback chain when free-tier quota is exhausted. The dashboard never shows a hard failure — it degrades gracefully to the next available Gemini variant.

**Archive pattern for streaming continuity**
EventHub is deleted between sessions to control cost. A `streaming_rides_archive` Bronze table persists all streamed rides to Delta Lake before each delete, so ride counts accumulate across sessions without data loss — meaning the AI always has a growing dataset to reason over.

**DLT pipeline optimized to ~75 seconds**
Reduced from ~6–8 minutes by: removing an unnecessary watermark on `silver_obt`, setting shuffle partitions to 4, introducing a `gold_base` cache table to prevent multiple stream readers, and correcting the fact table CDC key to `ride_id` only. A slow pipeline means stale AI context — this was an AI data-freshness problem as much as an infrastructure one.

**Azure SDK over az CLI**
All EventHub management uses the `azure-mgmt-eventhub` Python SDK, not subprocess `az` calls. This is what makes the pipeline control panel work on Streamlit Cloud where no CLI is available.

---

## 🚀 Local Setup

### Prerequisites
- Python 3.11+
- Databricks workspace (Community Edition or higher)
- Azure subscription with EventHub + Key Vault access
- Gemini API key (free tier works)

### 1. Clone and install
```bash
git clone https://github.com/avikalsingh/uber-data-engineering-project.git
cd uber-data-engineering-project
python -m venv .uber_de
.uber_de\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 2. Configure `.env`
```env
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=your-token
DATABRICKS_PIPELINE_ID=your-dlt-pipeline-id
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/your-warehouse-id

ADMIN_USERNAME=your-username
ADMIN_PASSWORD=your-password
SECRET_KEY=your-secret-key

AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret
AZURE_SUBSCRIPTION_ID=your-subscription-id

GEMINI_API_KEY=your-gemini-api-key
```

### 3. Start a session
```bash
# Provision EventHub + write credentials to Key Vault
python start_eventhub.py

# Stream rides to EventHub
python connection.py

# Run dashboard
streamlit run streamlit_app/main.py
```

### 4. End a session
```bash
# Delete EventHub — stops billing
python stop_eventhub.py
```

---

## ☁️ Streamlit Cloud Deployment

Add these to **App ⋮ → Settings → Secrets**:

```toml
DATABRICKS_HOST = "https://your-workspace.cloud.databricks.com"
DATABRICKS_TOKEN = "your-token"
DATABRICKS_PIPELINE_ID = "your-pipeline-id"
DATABRICKS_HTTP_PATH = "/sql/1.0/warehouses/your-warehouse-id"

ADMIN_USERNAME = "your-username"
ADMIN_PASSWORD = "your-password"
SECRET_KEY = "your-secret-key"

AZURE_TENANT_ID = "your-tenant-id"
AZURE_CLIENT_ID = "your-client-id"
AZURE_CLIENT_SECRET = "your-client-secret"
AZURE_SUBSCRIPTION_ID = "your-subscription-id"

GEMINI_API_KEY = "your-gemini-api-key"
```

`CONNECTION_STRING` and `LISTENER_CONNECTION_STRING` are fetched from Azure Key Vault at runtime — no manual update needed after provisioning.

---

## 💰 Cost Model

| Resource | Cost |
|---|---|
| Gemini API | Free tier (fallback chain handles quota limits) |
| Azure EventHub Standard | ~$0.015/TU/hr — deleted between sessions |
| Azure Key Vault | ~$0.00/month at portfolio scale |
| Azure Data Factory | Minimal — batch load only |
| Databricks Community Edition | Free |
| Streamlit Cloud | Free |

---

## 📁 Project Structure

```
uber-data-engineering-project/
├── streamlit_app/
│   ├── main.py                    # Entry point — page config, top bar, tabs
│   ├── design_tokens.py           # Central design system (colors, fonts, spacing)
│   ├── ai_service.py              # Gemini chatbot with multi-model fallback
│   ├── react_agent_service.py     # LangChain ReAct agent with Databricks tools
│   ├── supervisor_service.py      # LangGraph multi-agent supervisor
│   ├── rag_service.py             # Gemini embeddings RAG over project docs
│   └── components/
│       ├── analytics.py           # Tab 01 — charts, KPIs, live feed, map
│       ├── control.py             # Tab 02 — pipeline control panel
│       ├── floating_chat.py       # Floating chat widget (simple Gemini)
│       ├── agentic_popup_chat.py  # FAB-triggered agentic chat (ReAct/supervisor)
│       ├── pipeline_status.py     # DLT pipeline status bar
│       ├── enhanced_charts.py     # Plotly chart helpers
│       ├── kpi_card.py            # KPI card component
│       ├── ride_table.py          # Live ride feed table
│       └── scroll_animations.py   # CSS scroll animation injector
├── Code_Files/
│   ├── archive.py                 # DLT notebook — streaming archive
│   ├── ingest.py                  # DLT notebook — bronze ingestion
│   ├── model.py                   # DLT notebook — gold star schema
│   ├── silver.py                  # DLT notebook — silver stg_rides
│   └── silver_obt.sql             # DLT notebook — silver OBT
├── Data/
│   ├── bulk_rides.json            # 2,000 historical rides
│   └── map_*.json                 # Dimension lookup files (used by RAG)
├── eventhub_manager.py            # Azure SDK — EventHub + Key Vault operations
├── connection.py                  # EventHub producer — sends ride events
├── db.py                          # Databricks SQL connector + all queries
├── data.py                        # Synthetic ride data generator
├── config_utils.py                # Unified secret resolution (st.secrets → os.getenv)
├── start_eventhub.py              # Provision EventHub
├── stop_eventhub.py               # Delete EventHub
├── auth.py                        # JWT auth helpers
├── requirements.txt
└── .gitignore
```

---

## 🔒 Security

- Credentials never hardcoded — resolved from `.env` locally, `st.secrets` + Azure Key Vault on Streamlit Cloud
- Azure Service Principal scoped to `rg-uber` resource group only
- Pipeline Control tab is password-protected
- AI agents operate read-only — no SQL writes, no passenger or driver names passed to any model

---

*A portfolio project built to demonstrate what happens when you take multi-agent AI seriously and invest in the data infrastructure to back it up.*
