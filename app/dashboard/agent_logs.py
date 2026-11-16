"""In-memory log hub for processes that live outside Docker.

The Telegram agent runs on the host, so neither ``docker logs`` nor the
Docker socket can see it. The agent pushes formatted records to
``/dashboard/api/logs/ingest`` and the dashboard streams them over the
existing WebSocket, using :data:`agent_log_hub` as the source.
"""

import asyncio
import re
from collections import deque
from datetime import datetime, timezone

_LOG_LINE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\|\s*"
    r"(?P<level>[A-Z]+)\s+\|\s*(?P<name>[^|]+?)\s+\|\s?(?P<msg>.*)$",
    re.DOTALL,
)


def parse_agent_log_line(service: str, line: str) -> dict[str, str]:
    """Turn one formatted record into the dashboard's log entry shape."""
    match = _LOG_LINE.match(line)
    if match:
        return {
            "time": match.group("time"),
            "level": match.group("level"),
            "name": match.group("name").strip() or service,
            "msg": match.group("msg"),
        }
    return {
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": "INFO",
        "name": service,
        "msg": line,
    }


class AgentLogHub:
    """Fan-out of external log entries to dashboard WebSocket clients."""

    def __init__(self, max_history: int = 2000, online_ttl_seconds: int = 90):
        self.history: deque[dict[str, str]] = deque(maxlen=max_history)
        self.subscribers: set[asyncio.Queue] = set()
        self.online_ttl_seconds = online_ttl_seconds
        self.last_seen: datetime | None = None

    def publish(self, entry: dict[str, str]) -> None:
        self.history.append(entry)
        self.last_seen = datetime.now(timezone.utc)
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(entry)
            except asyncio.QueueFull:
                # A slow browser tab must not block ingestion.
                pass

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    def snapshot(self) -> list[dict[str, str]]:
        return list(self.history)

    def is_online(self) -> bool:
        if self.last_seen is None:
            return False
        age = datetime.now(timezone.utc) - self.last_seen
        return age.total_seconds() <= self.online_ttl_seconds


agent_log_hub = AgentLogHub()
