# Spend Analyzer Master Prompt

You are an expert AI software developer and architect. You are working on **Spend Analyzer**, an agentic personal finance helper designed to ingest, parse, map, and analyze bank and credit card statements locally and securely.

Below is a complete description of the system architecture, directory layouts, database schemas, processing flows, and coding constraints. Use this context to implement features, fix bugs, or write tests correctly.

---

## 🌟 Project Overview & Vision
Spend Analyzer provides a secure, local-first finance dashboard that ingests bank statements (PDF, TXT, CSV), categorizes transactions, resolves transfers across multiple accounts, and displays correlations and behavioral tips.
Key features include:
1. **Secure Ingestion**: Text extraction runs locally. Unknown templates are handled gracefully or processed using token-bounded LLM fallbacks.
2. **Symmetrical Transaction Linking**: Identifies credit card payments and bank-to-bank transfers (e.g., debit of ₹5,000 from Axis, credit of ₹5,000 to HDFC) within a ±7-day window. These are categorized as `"Self-Transfers"` and linked via `linked_transaction_id`.
3. **Double-Counting Exclusions**: Symmetrically linked transactions and `"Self-Transfers"` are automatically excluded from consolidated calculations (monthly Inflow, Outflow, Net, and Savings Rate) and frontend charts to prevent spending metric inflation.
4. **Google Antigravity SDK Pipeline**: An autonomous background orchestrator coordinates 4 specialized agents sequentially.

---

## 🏛️ Codebase Architecture & Directory Layout

### Component Diagram
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

### Directory Structure & File Map
* **Configuration & Docs**:
  - [ARCHITECT_AND_STRUCTURE.md](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/ARCHITECT_AND_STRUCTURE.md): Blueprint of codebase, database, and system logs.
  - [BACKLOG_AND_PRIORITIES.md](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/BACKLOG_AND_PRIORITIES.md): Feature roadmap and LLM prompt context templates.
  - [CONVERSATION_LOG.md](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/CONVERSATION_LOG.md): Summary of architectural pivots and implementation history.
* **Backend Source (`backend/app/`)**:
  - [main.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/main.py): FastAPI endpoints handling uploads, linking overrides, and agent run histories.
  - [models.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/models.py): SQLAlchemy models for SQLite mapping.
  - [config.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/config.py): Environment settings (`DATABASE_URL`, `GEMINI_API_KEY`, etc.).
  - [categorizer.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/categorizer.py): 3-Tier Categorization Pipeline (Deterministic Regex rules -> Semantic Vector Cosine similarity via `fastembed` -> Agentic Gemini fallback).
  - [parser.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/parser.py): Table/text extraction for Axis (PDF), HDFC (TXT), Generic CSV, and dynamic custom parsers.
  - [analytics.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/analytics.py): Pearson correlation analyses on monthly aggregates and behavioral suggestions.
  - [rate_limiter.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/rate_limiter.py): In-memory rate limits & notification cooldown triggers.
  - [custom_parsers/](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/custom_parsers/): Package directory for dynamically generated statement parsers.
* **Autonomous Agents (`backend/app/agents/`)**:
  - [orchestrator.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/orchestrator.py): Orchestrates sequential agent lifecycle executions (Runs 1 to 4).
  - [parser_agent.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/parser_agent.py): (Agent 1) Identifies bank layout (including registered custom formats) and parses files.
  - [parser_creator_agent.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/parser_creator_agent.py): Spawns code generation agent to build and test python parsers for unrecognized formats.
  - [mapper_agent.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/mapper_agent.py): (Agent 2) Groups transactions and executes the 3-Tier categorization pipeline.
  - [insights_agent.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/insights_agent.py): (Agent 3) Computes expense correlation metrics and calls Gemini for insights.
  - [frontend_agent.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/frontend_agent.py): (Agent 4) Performs leak check tests to block `Self-Transfers` from consolidated charts, and logs completion.
  - [triggers.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/triggers.py): Scans the `statements_to_process/` and `email_inbox/` folders for new files.
* **Frontend Dashboard (`frontend/src/`)**:
  - [App.tsx](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/frontend/src/App.tsx): React 19 Dashboard containing KPI metric blocks, Recharts visual graphs, transaction ledgers, linkage overrides, dynamic parser build prompts, and agent pipeline logs.

---

## 🗄️ Database Schema & Data Models

### 1. `transactions`
Core transaction ledger table:
* `id` (VARCHAR(36), PK): UUID.
* `date` (DATE): Transaction date.
* `description` (VARCHAR(255)): Original statement description string.
* `amount` (NUMERIC(10,2)): Negative = Debit (expense), Positive = Credit (income).
* `balance_after` (NUMERIC(10,2)): Running balance (nullable).
* `category` (VARCHAR(50)): Defaults to `"Others"`.
* `source` (VARCHAR(100)): Ingestion descriptor (e.g. `axis_pdf_agent_upload`).
* `description_embedding` (JSON): 384-float JSON list representation.
* `exclude_from_matching` (BOOLEAN): If True, skips semantic/agentic mapping.
* `linked_transaction_id` (VARCHAR(36), Nullable): Points to counterpart transfer.
* `ai_rate_limited` (BOOLEAN, Default: False): Flags failed mapping attempts.

### 2. `categorization_rules`
Deterministic substring/regex matches:
* `id` (INTEGER, PK): Auto-incremented.
* `pattern` (VARCHAR(100), Unique): Text matched against descriptions.
* `category` (VARCHAR(50)): Target category assignment.
* `is_regex` (BOOLEAN): Match pattern using regex compile.
* `user_confirmed` (BOOLEAN): Set to True for user-validated patterns.

### 3. `agent_runs`
Pipeline execution logs:
* `id` (VARCHAR(36), PK): Run UUID.
* `timestamp` (TIMESTAMP): Launch time.
* `status` (VARCHAR(20)): (`started`, `parsing`, `mapping`, `analyzing`, `frontend`, `completed`, `failed`).
* `log_output` (JSON): Text lines of agent runtime logs.
* `error_message` (TEXT, Nullable): Failure diagnostics.

---

## ⚡ Crucial Architecture Rules & Coding Constraints

1. **Uvicorn File Watcher Loop prevention**:
   > [!IMPORTANT]
   > Do **NOT** enable `--reload` when launching the FastAPI server on development. Writing to SQLite (`finance.db`) inside the project root will trigger Uvicorn's watch loops, causing infinite server reloads and freezing the agent pipeline.
2. **Sandbox-Safe Notification Emails**:
   > [!NOTE]
   > To test email dispatches without making actual SMTP connections, the system writes email notification JSON payloads to the local file `/Users/bhaveshpachnanda/.gemini/antigravity/scratch/notifications.jsonl`. Maintain this behavior for unit tests and local runs.
3. **Dynamic Category Alignment**:
   > [!IMPORTANT]
   > When prompt-crafting for Gemini API category classification (Tier 3), do **NOT** hardcode the allowed categories. Query the database to retrieve the active categories and dynamically pass the `'Allowed Categories'` list to the model.
4. **Calculations Leak Check Rule**:
   > [!CAUTION]
   > Every consolidated financial calculation (Inflow, Outflow, Net, Savings Rate) and category chart query MUST explicitly exclude transactions categorized under `"Self-Transfers"` or where `linked_transaction_id IS NOT NULL`.
5. **Dynamic Custom Parsers & Package-Agnostic Imports**:
   > [!IMPORTANT]
   > When dynamically compiling, validating, or running imports for dynamic custom parsers under `app/custom_parsers/`, ensure all imports and validation hooks use relative or package-agnostic paths (e.g. `__package__` and dynamic package resolutions) instead of hardcoded package prefixes like `"backend.app"`. This prevents `ModuleNotFoundError` across different runtime env configurations (e.g., uvicorn runner vs pytest runner).
6. **Double-Trigger Prevention for Pending Uploads**:
   > [!WARNING]
   > Store files pending user approval for custom parser creator in the isolated directory `backend/uploads_pending_parser/` instead of `backend/statements_to_process/` to avoid triggering the background scanner thread loop automatically before the user confirms.
7. **Post-Implementation Documentation Rule**:
   > [!IMPORTANT]
   > Once any feature, change, or bug fix has passed verification, run a check to update the repository documentation. Modify the relevant tracking documentation, markdown files (e.g., `ARCHITECT_AND_STRUCTURE.md`, `CONVERSATION_LOG.md`), or `.md` references within the project directory to reflect the exact state of the new code additions.

---

## 🛠️ Typical Development Tasks & Recipes

### Running the Backend
```bash
cd backend
source .venv/bin/activate
python -m uvicorn app.main:app --port 8000
```

### Running the Frontend
```bash
cd frontend
npm run dev -- --port 5174
```

### Running the Pytest Suite
```bash
cd backend
source .venv/bin/activate
pytest tests/
```

### Adding a New Bank Parser
1. Implement your parsing logic inside [parser.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/parser.py).
2. Wire the layout identifier check inside Super Agent 1 ([parser_agent.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/parser_agent.py)) to route files matching the layout to your new parser.
3. Add a corresponding test suite inside [test_parser.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/tests/test_parser.py).

