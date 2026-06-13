# Architectural & Codebase Breakdown

This document provides a technical blueprint of the Spend Analyzer codebase, including high-level interactions, file-by-file organization, database schemas, and state management flow.

---

## 🏛️ System Architecture

Spend Analyzer utilizes a decoupled client-server architecture with an asynchronous multi-agent background executor. The interaction flow is structured as follows:

```mermaid
graph TD
    User([User / Statement Dir]) -->|Upload PDF/CSV| FastAPI[FastAPI Web Server]
    Daemon[Background Trigger Daemon] -->|Scans Monitored Folders| FastAPI
    
    subgraph Multi-Agent Pipeline (Orchestrator)
        FastAPI -->|Spawns Runs| Orch[Orchestrator]
        Orch -->|Run Agent 1| Parser[Document Parser Agent]
        Orch -->|Run Agent 2| Mapper[Transaction Mapper Agent]
        Orch -->|Run Agent 3| Insights[Insights & Correlation Agent]
        Orch -->|Run Agent 4| FrontendAgent[Frontend Data Agent]
    end

    Parser -->|Extract Tables & Write| DB[(SQLite Database)]
    Mapper -->|Semantic Mapping & Write| DB
    Insights -->|Pearson correlation & Recommendations| DB
    FrontendAgent -->|Consolidation check & Ready Log| DB

    React[React 19 Frontend Dashboard] -->|REST API Requests| FastAPI
    DB -->|Query Results / Agent Runs Logs| FastAPI
```

### 1. Ingestion Flow (Manual vs. Autonomous)
* **Manual Ingestion**: The user uploads a file through the React dashboard using the `POST /api/upload` endpoint. FastAPI tries standard code parsers first. If they fail (or return 0 rows), it caches the text, calculates token cost estimations, and prompts the user for explicit approval to fall back to the Gemini statement parser.
* **Autonomous Ingestion**: A directory trigger loop polls `backend/statements_to_process/` and `backend/email_inbox/` folders every 10 seconds. If a file is found, it instantiates the Multi-Agent Orchestrator pipeline.

### 2. Multi-Agent Pipeline
* **Orchestrator (`orchestrator.py`)**: Manages execution state, initializes runs in the database, runs Agents 1-4 sequentially, handles failures, dispatches notifications, and cleans up processed/invalid statement files to prevent infinite loops.
* **Super Agent 1 (`parser_agent.py`)**: Runs layout checks. If the layout matches known banks (Axis PDF, HDFC TXT, Generic CSV), it parses and saves the transaction records to the DB. If unknown, it halts execution, transitions the run status to `failed`, and sends a mock request email to `scratch/notifications.jsonl` asking the developer to write a parser script.
* **Super Agent 2 (`mapper_agent.py`)**: Executes rules-based substring checks (Tier 1) and local vector similarity comparisons (Tier 2) using `fastembed` dense vectors (`BAAI/bge-small-en-v1.5`). Any remaining unmatched transactions are batched into chunks and sent to the Gemini API (`gemini-2.5-flash`) for structured categorization (Tier 3).
* **Super Agent 3 (`insights_agent.py`)**: Reads the SQLite tables to execute monthly aggregates. It computes a Pearson correlation matrix identifying discretionary categories (e.g. food delivery, cab services) that negatively impact monthly net balance deltas. It then invokes Gemini to write short, highly actionable behavior guidelines.
* **Super Agent 4 (`frontend_agent.py`)**: Performs final metrics computations (consolidated income, outflow, savings rate) and runs a verification leak-check ensuring that no linked transactions or `Self-Transfers` leaked into consolidation calculations. It marks the execution run status as `completed`.

---

## 📂 Directory Structure

Below is the directory hierarchy of the Spend Analyzer repository:

```
.
├── ARCHITECT_AND_STRUCTURE.md      # Documentation: System architecture, folder structure, DB schemas
├── BACKLOG_AND_PRIORITIES.md       # Documentation: Technical debt, feature backlog, prompts context
├── CONVERSATION_LOG.md             # Documentation: Synthesis of discussions, architectural pivots
├── README.md                       # Project Charter, installation guides, and roadmap
├── finance.db                      # Local SQLite database (git-ignored)
├── backend                         # Backend Application Root
│   ├── .env                        # Local secret configurations (git-ignored)
│   ├── pyproject.toml              # Dependencies definition (FastAPI, SQLAlchemy, google-antigravity, etc.)
│   ├── email_inbox                 # Monitored mock folder for statement email attachments
│   │   └── .gitkeep
│   ├── statements_to_process       # Monitored folder for dropped statement files
│   │   └── .gitkeep
│   ├── app                         # FastAPI Python Package Source
│   │   ├── __init__.py
│   │   ├── analytics.py            # Computes monthly aggregates, Pearson correlation, and NLP insights
│   │   ├── categorizer.py          # 3-tier transaction matching pipeline and embedding utilities
│   │   ├── config.py               # Settings loader (DATABASE_URL, GEMINI_API_KEY, ENCRYPTION_KEY)
│   │   ├── database.py             # SQLAlchemy engine setup and connection sessions
│   │   ├── main.py                 # FastAPI endpoints (uploads, transactions, overrides, linking, agent-runs)
│   │   ├── models.py               # SQLAlchemy Database models (Transaction, Category, Rule, AgentRun)
│   │   ├── parser.py               # Statement parsers (HDFC, Axis, Generic CSV, and Gemini parser)
│   │   ├── rate_limiter.py         # Tracks AI rate limits in-memory and handles notification cooldowns
│   │   ├── schemas.py              # Pydantic schemas for request/response serialization
│   │   └── agents                  # Autonomous Multi-Agent modules (Google Antigravity SDK)
│   │       ├── __init__.py
│   │       ├── frontend_agent.py   # Super Agent 4: Verification leak-check and logs completion
│   │       ├── insights_agent.py   # Super Agent 3: Computes spending correlations and behavior tips
│   │       ├── mapper_agent.py     # Super Agent 2: Local rules, vectors, and Gemini batch mappings
│   │       ├── orchestrator.py     # coordinator coordinating execution runs
│   │       ├── parser_agent.py     # Super Agent 1: Bank layout identifier and parser router
│   │       ├── triggers.py         # Directory watcher loop scanning drop files and mock email inbox
│   │       └── utility_agents.py   # Internal database write/read utilities and human mock emails
│   └── tests                       # Testing Suite
│       ├── Account_stmt.pdf        # Real sample Axis PDF statement for manual integration tests
│       ├── conftest.py             # Pytest config (overrides DATABASE_URL to memory-only sqlite://)
│       ├── read_account_statement.py # Text line parsing testing utility
│       ├── test_agents.py          # Pytest unit tests for agent modules, triggers, and orchestrator
│       ├── test_categorizer.py     # Pytest unit tests for rules, similarity matches, and links
│       └── test_parser.py          # Pytest unit tests for cleans, dates, and bank parsers
└── frontend                        # React Vite Frontend Application
    ├── .gitignore
    ├── eslint.config.js
    ├── index.html
    ├── package.json
    ├── tailwind.config.js
    ├── tsconfig.json
    └── src
        ├── App.css
        ├── App.tsx                 # Core Dashboard UI (KPI cards, charts, transaction table, pipeline logs)
        ├── index.css
        ├── main.tsx
        ├── assets/                 # Icons and image visual assets
        └── vite-env.d.ts
```

---

## 🗄️ Data Models & Database Schemas

Spend Analyzer uses SQLAlchemy ORM mappings in SQLite. All tables and columns are described below:

### 1. `transactions` (Core Ledger Table)
Stores individual transaction records extracted from bank or credit card statements.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `VARCHAR(36)` | Primary Key, Default: UUID | Unique identifier of the transaction. |
| `date` | `DATE` | Not Null | Date of transaction execution. |
| `description` | `VARCHAR(255)`| Not Null | Original description string from statement. |
| `amount` | `NUMERIC(10,2)`| Not Null | Value (negative for debit/expense, positive for credit/income). |
| `balance_after` | `NUMERIC(10,2)`| Nullable | Running account balance after transaction (if available). |
| `category` | `VARCHAR(50)` | Nullable, Default: `"Others"` | Assigned classification category. |
| `source` | `VARCHAR(100)`| Not Null | Ingestion source identifier (e.g. `axis_pdf_agent_upload`). |
| `raw_payload` | `TEXT` (JSON) | Nullable | Unstructured row cell mappings stored as JSON. |
| `description_embedding`| `TEXT` (JSON)| Nullable | 384-float vector list stored as a JSON array. |
| `exclude_from_matching`| `BOOLEAN` | Default: `False` | Flags if manual category override is permanent (skips re-categorization loops). |
| `linked_transaction_id`| `VARCHAR(36)` | Nullable | Links counterpart transactions for internal/self transfers. |
| `ai_rate_limited`      | `BOOLEAN`     | Default: `False` | True if transaction failed AI categorization due to rate limit. |
| `created_at`           | `TIMESTAMP`   | Default: UTC Now | Transaction insertion timestamp. |

### 2. `categories` (Category Seed Table)
Contains all categories allowed by the system.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `name` | `VARCHAR(50)` | Primary Key | Unique name of the category (e.g. `Grocery`, `Self-Transfers`). |
| `description` | `TEXT` | Nullable | Brief category details. |
| `is_custom` | `BOOLEAN` | Default: `False` | True if created dynamically by the user. |

### 3. `categorization_rules` (Deterministic Matching Table)
Contains deterministic rule configurations created when a user chooses to "Remember this override rule".

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | Primary Key, Auto-increment | Unique identifier of the rule. |
| `pattern` | `VARCHAR(100)`| Not Null, Unique | Text pattern to match in the transaction description. |
| `category` | `VARCHAR(50)` | Not Null, Foreign Key | Category to assign. |
| `is_regex` | `BOOLEAN` | Default: `False` | True if the pattern should be evaluated as a Regular Expression. |
| `user_confirmed` | `BOOLEAN` | Default: `True` | True if explicitly confirmed by a user override action. |

### 4. `agent_runs` (Autonomous Multi-Agent Logs Table)
Maintains logs and run statuses of orchestrator pipeline executions.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `VARCHAR(36)` | Primary Key | Unique run execution identifier. |
| `timestamp` | `TIMESTAMP` | Default: Current Local | Run start timestamp. |
| `status` | `VARCHAR(20)` | Not Null | Current execution stage (`started`, `parsing`, `mapping`, `analyzing`, `frontend`, `completed`, `failed`). |
| `statement_source`| `VARCHAR(150)`| Not Null | Details of how trigger scan was initialized (e.g. `folder_trigger (unsupported_layout.txt)`). |
| `log_output` | `TEXT` (JSON) | Not Null | JSON list containing line-by-line runtime console logs. |
| `error_message` | `TEXT` | Nullable | Traceback stack or error details if status is `failed`. |

---

## ⚡ AI Rate Limiter & Mitigation Flow

To prevent application blockages and excess token consumption during high traffic, Spend Analyzer implements a proactive rate limit mitigation strategy:

1. **In-Memory Rate Limiter (`rate_limiter.py`)**:
   - Tracks if the AI engine is rate limited and blocks calls for a specific window (default: 5 minutes).
   - Manages a de-duplicated notification cooldown (default: 1 hour) to prevent email spam.
   - De-duplicated emails are dispatched to `scratch/notifications.jsonl`.
2. **Batch Pacing**:
   - Introduces a `1.5s` pacing delay (`await asyncio.sleep(1.5)`) between consecutive chunk requests to smoothen traffic.
3. **Graceful Fallback**:
   - Checks `is_ai_rate_limited()` before calls to Gemini.
   - If blocked or if a `429`/`RESOURCE_EXHAUSTED` error is caught, the transactions are categorized under `"Others"` and flagged as `ai_rate_limited = True` in the database.
4. **Dashboard Control & Reclassification**:
   - Displays a warning banner indicating active block windows and remaining retry duration.
   - Provides table filtering via "⚠️ Rate Limited Only" to view flagged items.
   - Allows users to select multiple transactions and force re-classification through `POST /api/transactions/reclassify` when limits clear, running the entire mapping pipeline.
