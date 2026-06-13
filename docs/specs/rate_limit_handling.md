# Feature Specification: AI Rate-Limit Mitigation & User Notification

This specification details the implementation of proactive traffic pacing, rate-limit error detection, graceful fallback mechanisms, and user/developer notifications when the Gemini API rate limits are reached.

---

## 📋 Target User Stories

1. **Proactive Ingestion Pacing**:
   * *As a user* uploading a massive bank statement containing hundreds of transactions, I want the system to pace its batch requests to the Gemini API, so that I do not hit the API's Requests Per Minute (RPM) limits and fail the upload.

2. **Graceful Ingest Fallback (Circuit Breaker)**:
   * *As a user*, if the Gemini API rate limit is reached during statement upload or agent execution, I want the application to fall back gracefully to local rule and vector similarity categorization without crashing, tagging the remaining transactions as "Others" or using the best local match.

3. **Developer Alerting (De-duplicated)**:
   * *As an administrator*, I want to be notified (via mock email to `scratch/notifications.jsonl`) when the AI rate limit is reached, but I do not want my inbox flooded with duplicate alerts for the same ingestion batch.

4. **UI Status Awareness**:
   * *As a user*, I want to see a clear warning banner on my dashboard if the Gemini API is temporarily rate-limited, informing me when the service is expected to resume, so I am aware that AI insights and parsing fallbacks are temporarily disabled.

---

## 🗄️ Proposed Schema & State Modifications

Since rate limiting is a transient runtime concern, we can implement it as a thread-safe, in-memory circuit breaker, or store it in the database for persistence across app restarts. 

### Option A: In-Memory Tracker (Recommended for local setup)
Maintain a thread-safe state in the FastAPI app (e.g. inside a `backend/app/rate_limiter.py` file):
* `ai_rate_limited_until: Optional[datetime]`
* `last_notification_sent: Optional[datetime]`

### Option B: Database-Backed Config Table
If persistence is needed (so restarting the backend does not wipe the rate-limit block duration), we can add a simple key-value `system_settings` table to SQLite, or add columns to the `agent_runs` table to log rate-limit events.
For simplicity and reliability, we propose using a dedicated singleton module `rate_limiter.py` with in-memory states, coupled with logging rate limit events directly inside the `AgentRun` table logs.

---

## ⚡ Technical Edge Cases & Product Logic

1. **Transient vs. Hard Rate Limits**:
   * *Transient Limit (HTTP 429 / RESOURCE_EXHAUSTED)*: If a request fails with 429, we should mark the AI client as rate-limited for **5 minutes** (initial backoff). If it happens repeatedly, we increase the window (up to 15 minutes).
   * *Handling*: The SDK's built-in `HttpRetryOptions` should handle momentary burst retries, but if it ultimately fails after attempts, we trigger the 5-minute block window.

2. **Proactive Circuit Breaker**:
   * Any routine calling the Gemini API (`parse_statement_with_gemini`, `query_gemini_categorizer`, `categorize_transactions_batch`, `generate_natural_language_insights`, `map_with_gemini`) must first check `is_ai_rate_limited()`.
   * If true, it skips the Gemini call instantly and raises a specific `AIRateLimitException` or returns fallback defaults directly, protecting API quota and speeding up execution.

3. **Rate Limiting Developer Emails**:
   * When an `APIError` 429 occurs, a mock email is sent. To prevent sending 50 emails during batch operations, a cooldown of **15 minutes** is enforced on notifications.

4. **Batch Chunk Pacing**:
   * In `categorize_transactions_batch` and `map_with_gemini`, transactions are chunked (e.g., 100-120 items). If there are multiple chunks (e.g., 5 chunks for 500 items), the system will introduce a **1.5-second asynchronous delay** (`await asyncio.sleep(1.5)`) between consecutive chunk API requests.

---

## 🛠️ Proposed Changes by Component

### Backend Component

#### [NEW] [rate_limiter.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20FInance%20Handler/backend/app/rate_limiter.py)
* Create a lightweight module tracking:
  ```python
  from datetime import datetime, timedelta
  from typing import Optional

  _ai_rate_limited_until: Optional[datetime] = None
  _last_notification_sent: Optional[datetime] = None

  def is_ai_rate_limited() -> bool:
      global _ai_rate_limited_until
      if _ai_rate_limited_until and datetime.now() < _ai_rate_limited_until:
          return True
      _ai_rate_limited_until = None
      return False

  def trigger_ai_rate_limit(duration_minutes: int = 5):
      global _ai_rate_limited_until
      _ai_rate_limited_until = datetime.now() + timedelta(minutes=duration_minutes)

  def get_rate_limit_seconds_remaining() -> int:
      global _ai_rate_limited_until
      if _ai_rate_limited_until:
          diff = (_ai_rate_limited_until - datetime.now()).total_seconds()
          return max(0, int(diff))
      return 0

  def should_send_notification() -> bool:
      global _last_notification_sent
      now = datetime.now()
      if _last_notification_sent is None or now > _last_notification_sent + timedelta(minutes=15):
          _last_notification_sent = now
          return True
      return False
  ```

#### [MODIFY] [categorizer.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20FInance%20Handler/backend/app/categorizer.py)
* Import `is_ai_rate_limited`, `trigger_ai_rate_limit`, and `should_send_notification` from `rate_limiter`.
* In `query_gemini_categorizer` and `categorize_transactions_batch`:
  * Check `is_ai_rate_limited()` at entry. Fall back immediately to local models or "Others" if true.
  * Wrap the `generate_content` call in a try/except matching `google.genai.errors.APIError` (and generic exceptions with code/message checks).
  * If a rate limit is detected:
    1. Call `trigger_ai_rate_limit(5)`.
    2. If `should_send_notification()` is true, dispatch a mock email warning using `send_notification_email`.
    3. Log the incident to stdout/run steps and raise/return fallback.
  * In the chunking loop, if `len(chunks) > 1`, add `await asyncio.sleep(1.5)` between successive Gemini requests to pace traffic.

#### [MODIFY] [parser.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20FInance%20Handler/backend/app/parser.py)
* In `parse_statement_with_gemini`, check `is_ai_rate_limited()` at entry. Raise `HTTPException` or `ValueError` immediately with message `"AI Parsing is temporarily rate-limited."` if true.
* Catch 429 exceptions to set the rate-limit state and trigger notification email.

#### [MODIFY] [analytics.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20FInance%20Handler/backend/app/analytics.py)
* Check `is_ai_rate_limited()` in `generate_natural_language_insights` before invoking Gemini. Fall back to static rule-based tips immediately if rate-limited.

#### [MODIFY] [main.py](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20FInance%20Handler/backend/app/main.py)
* Expose a status endpoint:
  ```python
  @app.get("/api/ai-status")
  def get_ai_status():
      """Retrieves the rate limit status of the AI engine."""
      from .rate_limiter import is_ai_rate_limited, get_rate_limit_seconds_remaining
      return {
          "is_rate_limited": is_ai_rate_limited(),
          "seconds_remaining": get_rate_limit_seconds_remaining()
      }
  ```

---

### Frontend Component

#### [MODIFY] [App.tsx](file:///Users/bhaveshpachnanda/Antigravity%20Personal%20FInance%20Handler/frontend/src/App.tsx)
* Add a state hook `aiStatus` tracking `{ is_rate_limited: boolean, seconds_remaining: number }`.
* Periodically poll `GET /api/ai-status` (every 10 seconds, or on page load).
* If `is_rate_limited` is true:
  * Display a beautiful warning banner at the top of the dashboard page (using Tailwind or CSS variables):
    > **⚠️ AI Engine Rate-Limited**: AI categorization and conversational insights are temporarily paused to protect api limits. Local rules and vector search remain operational. Resuming in X seconds.
  * Disable the AI confirmation button in the upload flow if the rate limit is active, warning the user beforehand.

---

## 🧪 Verification Plan

### Automated Tests
* Create `backend/tests/test_rate_limiter.py` verifying that:
  1. Triggering the rate limiter blocks subsequent requests.
  2. The block expires or is cleared correctly.
  3. Batch chunking paces calls with delay.
  4. 429 exceptions from Gemini SDK are correctly intercepted.

### Manual Verification
1. Temporarily change the rate limiter default block duration to 30 seconds for easy manual testing.
2. Force a mock 429 error by hacking a temporary route or mock class that throws `APIError` with status code 429.
3. Verify that:
   * The warning banner appears in the React UI and displays a countdown.
   * `scratch/notifications.jsonl` contains exactly one warning email.
   * Uploading a statement during the block uses rule/vector fallback immediately without crashing.
   * Once the 30-second timer expires, the warning banner disappears and normal operations resume.

---

# 🤖 Sub-agent Hand-off Prompt

Pass the prompt block below to an Antigravity builder sub-agent to proceed with the implementation:

```text
You are tasked with implementing the AI Rate-Limit Mitigation & User Notification feature in the Spend Analyzer codebase.
Refer to the specification in docs/specs/rate_limit_handling.md.

1. Create backend/app/rate_limiter.py to track rate limits in-memory.
2. Refactor backend/app/categorizer.py, backend/app/parser.py, and backend/app/analytics.py to:
   - Check is_ai_rate_limited() before making any Gemini API calls.
   - Intercept rate-limit exception errors (code 429 or RESOURCE_EXHAUSTED).
   - Set the block window and dispatch a de-duplicated mock email to scratch/notifications.jsonl.
   - Introduce a 1.5s delay (asyncio.sleep) between batch chunks to smooth traffic.
3. Expose GET /api/ai-status in backend/app/main.py.
4. Update frontend/src/App.tsx to poll this endpoint and show a dashboard banner if the rate limit is active.

Workspace Documentation Rule: Once the feature has passed verification, run a check to update the repository documentation. Modify the relevant tracking documentation or `.md` references within the project directory to reflect the exact state of the new code additions.
```

<!-- [SKILL_ACTIVE: generate-spec.md] -->
