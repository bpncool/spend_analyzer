# Chronological Conversation & Evolution Summary

This document traces the development history, architectural decisions, technical pivots, and logical rationale behind the evolution of the Spend Analyzer project.

---

## 🛠️ Phase 1: Ingestion, Linking, & Exclusions (Manual Era)

### 1. Ingestion of Multi-Account Statements
* **Initial State**: The system supported basic CSV parsing. 
* **Evolution**: We added specialized statement parser algorithms:
  - **HDFC Bank TXT Statement Parser**: Reads fixed-width files, recovers multi-line transaction description continuations, extracts opening balances, and parses debit/credit columns.
  - **Axis Bank PDF Statement Parser**: Reads PDF tables (using `pdfplumber`), automatically maps column offsets, uses a dual-pass approach to capture opening balance positions, and falls back to string-matching regular expressions if the tables are improperly drawn.
* **Result**: We ingested 618 historical transactions from HDFC and Axis bank accounts into the SQLite database.

### 2. Symmetrical Transaction Linking
* **Problem**: Credit card payments and internal checking transfers were counted twice (once as a debit outflow from the source account and once as a credit inflow to the target account), inflating consolidated expenses.
* **Solution**: Developed a symmetrical linking mechanism:
  - Added the `linked_transaction_id` and `exclude_from_matching` columns to the database schema.
  - Created the `/api/transactions/link-candidates` endpoint, which finds counterpart transactions in other accounts matching the opposite amount sign within a ±7-day window, sorted by date proximity and value difference.
  - Created `/api/transactions/link` to bind transactions symmetrically. Both records are updated with `exclude_from_matching = True` (excluding them from future rules/vector mapping overrides) and categorized under the specialized category `"Self-Transfers"`.
  - Created `/api/transactions/unlink` to reset them back to `"Bank Transfer"` and clear the links.

### 3. Consolidated Calculations Exclusion
* **Rationle**: In the React dashboard, `Self-Transfers` and symmetrically linked transaction items are excluded from consolidated metrics (Inflow, Outflow, Net, Savings Rate) and the Spend by Category charts, keeping analytics accurate and free of internal transfer inflation.

---

## 🤖 Phase 2: The Agentic Automation Pipeline

### 1. Multi-Agent Integration (Google Antigravity SDK)
* **Goal**: Automate statement uploads, parsing, transaction classification, Pearson correlation metrics, and database validation.
* **Architectural Pivot**: We introduced the **Google Antigravity (AGY) SDK** to orchestrate four specialized "Super Agents" running on top of a central background trigger daemon:
  - **Super Agent 1 (Document Parser)**: Detects statement layout. Router: Axis PDF -> PDF parser; HDFC TXT -> TXT parser; Generic CSV -> CSV parser. Unknown -> Notifies human administrator via email.
  - **Super Agent 2 (Transaction Mapper)**: Performs Tier 1 (Rules) and Tier 2 (Local vector semantic similarity) checks. For remaining unmatched transactions, it makes a single batched Gemini structured JSON call (Tier 3), reducing API invocation costs by up to 87%.
  - **Super Agent 3 (Insights & Correlation)**: Groups transactions by month, pivots discretionary spending categories, runs a Pearson correlation matrix against net monthly balance change deltas, and calls Gemini to draft highly personalized behavior guidelines.
  - **Super Agent 4 (Frontend Data)**: Computes consolidated figures and runs a leak-check validation ensuring no linked transactions or `Self-Transfers` were merged into consolidated data.
  - **Orchestrator (`orchestrator.py`)**: Sequential controller coordinates agents 1-4, updates the DB logs, and deletes statement files once finished.

### 2. Directory & Email Triggers
* Created the `triggers.py` module containing a polling loop that checks the `backend/statements_to_process/` and `backend/email_inbox/` directories every 10 seconds.
* Dropping files in these folders triggers the agentic orchestrator automatically.

---

## ⚙️ Key Technical Decisions & Constraints

### 1. Disabling Uvicorn `--reload`
* **Observation**: In early tests, writing to the SQLite database during a parser run triggered uvicorn's file watcher (since it watches the working directory, including the virtual environment `.venv` and the database `finance.db`). This caused massive CPU spikes and infinite server reload loops.
* **Decision**: The backend server is run without `--reload` in production/tests.

### 2. Sandbox-Safe Mock Emails
* **Decision**: Because local test machines lack SMTP/Postfix configurations, the `send_notification_email` function writes email files directly to a local file in `/Users/bhaveshpachnanda/.gemini/antigravity/scratch/notifications.jsonl`. This allows automated unit tests to verify email dispatches without network requests.

### 3. Dynamic Category Alignment in Gemini Mappers
* **Problem**: In early mapper implementations, the system instructions inside the mapper agent hardcoded default category strings. However, if a user created a custom category, the prompt passed the database categories list while the system instructions still referenced the old list, confusing the model.
* **Decision**: We refactored both `mapper_agent.py` and `categorizer.py` to instruct Gemini to strictly pick categories from the `'Allowed Categories'` list passed in the prompt, using the default rules as generalized examples of mapping types.

### 4. Git Remote Integration
* To push the project code, we initialized a repository, established a `.gitignore` to protect environment configurations and statement PDFs/TXTs/DBs, linked it to SSH remote origin, resolved merge conflicts with default GitHub files, and pushed cleanly to the `main` branch.
