import logging
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List

logger = logging.getLogger("clembot.event_bus")


class EventBus:
    """Thread-safe publish/subscribe event bus for Clembot subsystems."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, event_name: str, handler: Callable[[Any], None]) -> None:
        """Subscribe a callback to an event."""
        with self._lock:
            if handler not in self._subscribers[event_name]:
                self._subscribers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: Callable[[Any], None]) -> None:
        """Unsubscribe a callback from an event."""
        with self._lock:
            if handler in self._subscribers[event_name]:
                self._subscribers[event_name].remove(handler)

    def emit(self, event_name: str, data: Any = None) -> None:
        """Emit an event to all subscribers."""
        with self._lock:
            handlers = list(self._subscribers.get(event_name, []))

        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                # Keep bus resilient against subscriber failures
                logger.warning(f"Error in event handler {handler} for {event_name}: {e}")


# Global event bus singleton
event_bus = EventBus()
