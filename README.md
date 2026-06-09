# Spend Analyzer - Personal Finance Intelligence Dashboard

Spend Analyzer is an autonomous, agentic personal finance helper designed to ingest, parse, match, and analyze bank and credit card statements. Built with a modern, high-performance web architecture, it leverages local vector embeddings and autonomous multi-agent pipelines to deliver deep insights into spending patterns, net savings rates, and multi-account correlations.

---

## 🌟 Core Vision & Value Proposition

Traditional personal finance tools rely on manual spreadsheet entries or insecure third-party scraping services that frequently break and leak PII. Spend Analyzer solves this through a **secure, local-first ingestion approach** augmented by **Autonomous AI Agents**:

1. **Secure Local Ingestion**: Ingests files (PDF, TXT, CSV) directly. Text extraction runs entirely locally. PII is scrubbed before any transaction descriptions reach external APIs.
2. **Hybrid Multi-Tier Categorization**: Matches transactions using a 3-tier mapping pipeline:
   - **Tier 1 (Deterministic)**: Substring and regex rules defined by the user.
   - **Tier 2 (Semantic)**: Local ONNX-powered dense vector representations (via `fastembed` using `BAAI/bge-small-en-v1.5`) matching against historical mappings.
   - **Tier 3 (Agentic Fallback)**: Cheap, structured Gemini API calls (`gemini-2.5-flash`) for unmatched descriptions.
3. **Multi-Account Linking & Exclusions**: Symmetrically links transfer pairs across different accounts (e.g. Axis debit of ₹5,000 linked to HDFC credit of ₹5,000) and classifies them as `Self-Transfers`, automatically excluding them from consolidated expense metrics and charts to prevent inflation of spending.
4. **Autonomous Multi-Agent Processing**: Orchestrates four specialized "Super Agents" using the **Google Antigravity (AGY) SDK** to monitor uploads, map transactions, run statistical Pearson correlation analyses, and verify metric readiness.

---

## 👥 Target Audience & Use Cases

* **Multi-Account Earners**: Individuals managing transactions across multiple credit cards, checking accounts, and investment accounts who need a unified savings view.
* **Privacy-Conscious Users**: Users who want to analyze bank statements without sharing passwords or linking live bank logins to third-party providers.
* **Active Investors**: Users tracking SIP payments and broker transfers who need to distinguish regular expenses from asset allocation.

### Primary Use Cases:
* **Statement Dropping**: Dragging and dropping PDF/CSV bank statements into monitored local folders or receiving them as mock email attachments.
* **Double-Counting Prevention**: Flagging and linking credit card payments and internal transfers so consolidated charts reflect true discretionary outflow.
* **Behavioral Self-Audit**: Highlighting which spending categories (e.g. food delivery, cab rides) show the strongest negative correlation with monthly net savings.

---

## 🛠️ Technology Stack

### Backend
* **FastAPI**: Main ASGI web framework providing structured API endpoints.
* **SQLAlchemy & SQLite**: ORM database storage for local runs.
* **Google Antigravity SDK**: Autonomous agent workflows, local agent configs, and tool bindings.
* **Google GenAI SDK**: Structured JSON outputs and schema validations via `gemini-2.5-flash`.
* **Fastembed (ONNX Runtime)**: Local text embedding generation (`BAAI/bge-small-en-v1.5`) for semantic similarity mappings.
* **Pandas**: Structured dataset pivots and Pearson correlation calculations.
* **pdfplumber**: Reliable PDF tabular text parsing.

### Frontend
* **React 19 & Vite**: Fast development server and build pipeline.
* **Tailwind CSS v4**: Modern, responsive utility-first styling.
* **Recharts**: Consolidated visual charts (Spend by Category bar charts and Monthly Trend lines).
* **Lucide React**: Premium iconography.

---

## 🚀 Getting Started

### Prerequisites
* Python 3.11 or higher
* Node.js v18 or higher
* A Gemini API Key (set as `GEMINI_API_KEY`)

### Backend Setup
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Initialize virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r pyproject.toml
   ```
3. Configure environment variables inside `.env`:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   DATABASE_URL=sqlite:///./finance.db
   ```
4. Run the FastAPI server:
   ```bash
   .venv/bin/python -m uvicorn app.main:app --port 8000
   ```

### Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```
2. Install node dependencies:
   ```bash
   npm install
   ```
3. Launch the Vite development server:
   ```bash
   PATH="/Users/bhaveshpachnanda/.local/bin:$PATH" npm run dev -- --port 5174
   ```
4. Open your browser and navigate to [http://localhost:5174](http://localhost:5174).

---

## 🗺️ Current State vs. Future Vision

| Feature | Current Implementation (Stable) | Long-Term Vision (Roadmap) |
| :--- | :--- | :--- |
| **Ingestion** | Manual API upload + local folder drop/mock email polling. | Production Gmail API OAuth scanner, automatically reading real email statements. |
| **Parsing** | Axis Bank PDF, HDFC Bank TXT, and Generic CSV layouts. | Autonomous Parser Generator writing custom python scripts for unknown banks. |
| **Mappers** | Static rule database + local cosine vector similarity + Gemini. | Collaborative cross-user mapping database with federated privacy. |
| **Analytics** | Monthly aggregates + Pearson correlation on net balance delta. | Full forecast modeling (Prophet/ARIMA) predicting future balance dips. |
| **Tenancy** | Single-user local SQLite database. | Full multi-tenant SaaS hosting with Firebase/Auth0 encryption. |
