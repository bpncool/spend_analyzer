import threading
from datetime import datetime, timedelta
from typing import Optional

_lock = threading.Lock()
_ai_rate_limited_until: Optional[datetime] = None
_last_notification_sent: Optional[datetime] = None

def is_ai_rate_limited() -> bool:
    """Checks if the AI rate limit block is currently active."""
    global _ai_rate_limited_until
    with _lock:
        if _ai_rate_limited_until:
            if datetime.now() < _ai_rate_limited_until:
                return True
            else:
                _ai_rate_limited_until = None
        return False

def trigger_ai_rate_limit(duration_minutes: int = 5):
    """Sets a rate limit block window for the specified duration (default: 5 minutes)."""
    global _ai_rate_limited_until
    with _lock:
        _ai_rate_limited_until = datetime.now() + timedelta(minutes=duration_minutes)

def get_rate_limit_seconds_remaining() -> int:
    """Returns the remaining seconds of the active rate limit block."""
    global _ai_rate_limited_until
    with _lock:
        if _ai_rate_limited_until:
            diff = (_ai_rate_limited_until - datetime.now()).total_seconds()
            return max(0, int(diff))
        return 0

def clear_ai_rate_limit():
    """Resets the rate limit block duration to None (primarily for testing)."""
    global _ai_rate_limited_until, _last_notification_sent
    with _lock:
        _ai_rate_limited_until = None
        _last_notification_sent = None

def should_send_notification() -> bool:
    """Enforces a 15-minute cooldown between mock email alerts to avoid duplicates."""
    global _last_notification_sent
    with _lock:
        now = datetime.now()
        if _last_notification_sent is None or now > _last_notification_sent + timedelta(minutes=15):
            _last_notification_sent = now
            return True
        return False
