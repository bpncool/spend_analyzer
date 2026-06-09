# Technical Debt & Feature Backlog

This document maps out the current technical limitations, security gaps, and bug vectors in the Spend Analyzer project, followed by a prioritized feature backlog with specific context mappings for future LLM prompt planning.

---

## ⚠️ Current Limitations & Technical Debt

### 1. File-Based Mock Email Notifications
* **Limitation**: The notification service writes human-in-the-loop emails to a local JSONL file (`scratch/notifications.jsonl`). While perfect for sandbox testing, this does not notify developers in real time.
* **Risk**: If a statement format is unrecognized, the agent fails silently from the user's perspective until they inspect the admin dashboard.

### 2. Hardcoded Statement Parsers
* **Limitation**: The deterministic parsers in `parser.py` use hardcoded column index offsets and string search constants for Axis Bank and HDFC Bank.
* **Risk**: Minor modifications to bank statement templates will break the standard parsers, forcing fallback to expensive AI parsing.

### 3. InMemory Vector Computations for SQLite
* **Limitation**: The local semantic mapping (Tier 2 in `categorizer.py` and `mapper_agent.py`) loads all historical transactions with embeddings into Python memory and loops over them calculating cosine similarity using NumPy.
* **Risk**: Performance will scale poorly ($O(N)$ memory and CPU load) as the transaction ledger grows. SQLite lacks a native vector indexing plugin in the default python standard library.

### 4. Single-User Database Local Tenancy
* **Limitation**: The current database does not model user identities.
* **Risk**: Uploads by different users will overwrite or merge into a single consolidated financial ledger, making the application single-tenant only.

---

## 📋 Prioritized Feature Backlog

| Priority | Feature Name | Description | Key Modules Affected |
| :--- | :--- | :--- | :--- |
| **High** | Production OAuth Gmail attachment scanner | Replace local folder mock email scanning with Gmail API scanner, reading real statement attachments using secure OAuth credentials. | `backend/app/agents/triggers.py` |
| **High** | Multi-User tenancy support | Add a `User` model, reference `user_id` inside the `Transaction` table, and update all API endpoints to filter records by authenticated user identity. | `backend/app/models.py`, `backend/app/main.py` |
| **Medium** | Autonomous Parser Creator Agent | When Super Agent 1 encounters an unknown format, it spawns a temporary code agent that reads the layout, automatically writes a Python parser function, runs tests on it, and imports it. | `backend/app/agents/parser_agent.py`, `backend/app/parser.py` |
| **Medium** | Interactive Override Rules UI | Build a dashboard section in React allowing users to view, search, edit, delete, or create deterministic regex rules stored in `categorization_rules`. | `frontend/src/App.tsx`, `backend/app/main.py` |
| **Low** | Native Vector Similarity in Database | Migrate from in-memory cosine similarity loop to pgvector (for Postgres deployments) or SQLite Vec extension (for local deployments) to offload similarity checks. | `backend/app/categorizer.py` |

---

## 🧠 Prompt Context Templates for Future Features

To implement the backlog features successfully using LLMs, feed the following instructions along with the project codebase:

### 1. Implementing Gmail API OAuth Scanner
* **Required Files**: [triggers.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/triggers.py), [config.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/config.py)
* **LLM Context Prompt**:
  > "Introduce a background scanner thread utilizing the Google OAuth 2.0 flow to pull attachments from Gmail. Retrieve messages with subject 'statement' or attachment types matching pdf/csv. Integrate this with `scan_emails_manually` inside `triggers.py`. Pass the extracted file stream to `orchestrate_statement_processing`. Ensure OAuth client secret config is loaded through `config.py` environment settings."

### 2. Migrating to Multi-Tenant Database Architecture
* **Required Files**: [models.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/models.py), [main.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/main.py), [utility_agents.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/utility_agents.py)
* **LLM Context Prompt**:
  > "Refactor SQLAlchemy database models to support multi-tenancy. Create a new `User` table. Add a `user_id` column as a Foreign Key in the `transactions` and `agent_runs` tables. Update FastAPI endpoints to enforce user authentication (via JWT or OAuth tokens) and ensure all database queries filter specifically by the authenticated user's ID. Update the mapper agent database helper tools in `utility_agents.py` to only fetch rules and embeddings belonging to the active user's tenancy scope."

### 3. Implementing the Autonomous Parser Creator Agent
* **Required Files**: [parser_agent.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/agents/parser_agent.py), [parser.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20Finance%20Handler/backend/app/parser.py)
* **LLM Context Prompt**:
  > "Instead of halting execution and emailing the administrator immediately on an unknown layout, configure Super Agent 1 to run a code generation task. Pass the first 2000 characters of the unknown statement to Gemini requesting a Python parsing function that adheres to the raw row schema (date, description, amount, balance_after). Write the generated code to a temp module, run validation tests against it, and if tests pass, write the parser to `parser.py` and register it dynamically."
