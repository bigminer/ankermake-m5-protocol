"""Server-owned Printer snapshots with resumable observation cursors.

This module is deliberately observation-only.  Printer actions consume the
snapshot through the same ``watch`` interface; raw MQTT payloads remain outside
this interface.
"""

from collections import deque
from dataclasses import dataclass
from threading import Condition
import time


FACT_PATHS = (
    "state",
    "nozzle.current",
    "nozzle.target",
    "bed.current",
    "bed.target",
    "print.name",
    "print.user_name",
    "print.origin",
    "print.elapsed",
    "print.remaining",
    "print.progress",
    "print.img",
    "print.layer.current",
    "print.layer.total",
    "speed",
)


@dataclass(frozen=True)
class Watch:
    printer_id: str
    cursor: int | None = None


@dataclass(frozen=True)
class Fact:
    value: object = None
    observed_at: float | None = None
    freshness: str = "unknown"


@dataclass(frozen=True)
class Snapshot:
    printer_id: str
    cursor: int
    facts: dict[str, Fact]
    actions: dict = None

    def to_dict(self):
        payload = {
            "printerId": self.printer_id,
            "cursor": self.cursor,
            "facts": {
                path: {
                    "value": fact.value,
                    "observedAt": fact.observed_at,
                    "freshness": fact.freshness,
                }
                for path, fact in self.facts.items()
            },
            "actions": {
                request_id: action.to_dict()
                for request_id, action in (self.actions or {}).items()
            },
        }
        for path, fact in self.facts.items():
            if fact.value is not None:
                _assign_path(payload, path, fact.value)
        return payload


class CursorExpired(ValueError):
    def __init__(self, cursor, oldest_cursor, current_cursor):
        super().__init__(
            f"cursor {cursor} expired; retained range is "
            f"{oldest_cursor - 1}..{current_cursor}"
        )
        self.cursor = cursor
        self.oldest_cursor = oldest_cursor
        self.current_cursor = current_cursor


class PrinterSnapshots:
    """Reduce normalized telemetry and expose full snapshots through ``watch``."""

    def __init__(self, *, clock=time.time, fresh_for=15.0, history_limit=256):
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self._clock = clock
        self._fresh_for = fresh_for
        self._history_limit = history_limit
        self._condition = Condition()
        self._printers = {}

    def observe(self, printer_id, normalized):
        """Ingest one already-normalized telemetry observation.

        This is the internal adapter seam used by the MQTT source.  Browser and
        action callers consume observations only through ``watch``.
        """
        updates = dict(_flatten(normalized))
        if not updates:
            return

        with self._condition:
            state = self._state(printer_id)
            observed_at = self._clock()
            if any(path.startswith("print.") for path in updates):
                name = updates.get("print.name", state["values"]["print.name"][0])
                if name:
                    updates.setdefault("print.name", name)
                    identity = state["job_identities"].get(name)
                    if identity:
                        updates["print.user_name"] = identity["user_name"]
                        updates["print.origin"] = identity["origin"]
                elif "print.name" in updates:
                    state["values"]["print.user_name"] = (None, None)
                    state["values"]["print.origin"] = (None, None)
            for path, value in updates.items():
                if path in state["values"]:
                    state["values"][path] = (value, observed_at)
            self._publish(printer_id, state, observed_at)

    def ensure(self, printer_id):
        """Ensure an unknown snapshot exists for a configured printer."""
        with self._condition:
            self._state(printer_id)

    def remember_job(self, printer_id, file_name, user_name, origin):
        """Retain trusted upload identity until matching job telemetry arrives."""
        with self._condition:
            state = self._state(printer_id)
            state["job_identities"][file_name] = {
                "user_name": user_name,
                "origin": origin,
            }

    def tick(self):
        """Publish fact-freshness transitions without inventing observations."""
        with self._condition:
            now = self._clock()
            for printer_id, state in self._printers.items():
                if not state["history"]:
                    continue
                current = self._snapshot(printer_id, state, now)
                previous = state["history"][-1]
                if any(
                    current.facts[path].freshness != previous.facts[path].freshness
                    for path in FACT_PATHS
                ):
                    self._publish(printer_id, state, now)

    def record_action(self, printer_id, action):
        """Publish a server-owned action outcome on the snapshot watch stream."""
        with self._condition:
            state = self._state(printer_id)
            state["actions"][action.request_id] = action
            self._publish(printer_id, state, self._clock())

    def watch(self, watch):
        return _SnapshotWatcher(self, watch)

    def _state(self, printer_id):
        return self._printers.setdefault(
            printer_id,
            {
                "cursor": 0,
                "values": {path: (None, None) for path in FACT_PATHS},
                "actions": {},
                "job_identities": {},
                "history": deque(maxlen=self._history_limit),
            },
        )

    def _snapshot(self, printer_id, state, now=None):
        now = self._clock() if now is None else now
        facts = {}
        for path, (value, observed_at) in state["values"].items():
            if observed_at is None:
                freshness = "unknown"
            elif now - observed_at <= self._fresh_for:
                freshness = "fresh"
            else:
                freshness = "stale"
            facts[path] = Fact(value, observed_at, freshness)
        return Snapshot(printer_id, state["cursor"], facts, dict(state["actions"]))

    def _publish(self, printer_id, state, now):
        state["cursor"] += 1
        snapshot = self._snapshot(printer_id, state, now)
        state["history"].append(snapshot)
        self._condition.notify_all()


class _SnapshotWatcher:
    def __init__(self, snapshots, watch):
        self._snapshots = snapshots
        self._watch = watch
        self._initial = watch.cursor is None
        self._next_cursor = None if self._initial else watch.cursor + 1

    def __iter__(self):
        return self

    def __next__(self):
        store = self._snapshots
        with store._condition:
            state = store._state(self._watch.printer_id)

            if self._initial:
                self._initial = False
                self._next_cursor = state["cursor"] + 1
                return store._snapshot(self._watch.printer_id, state)

            while True:
                history = state["history"]
                if history and self._next_cursor < history[0].cursor:
                    raise CursorExpired(
                        self._next_cursor - 1,
                        history[0].cursor,
                        state["cursor"],
                    )
                if self._next_cursor <= state["cursor"]:
                    for snapshot in history:
                        if snapshot.cursor == self._next_cursor:
                            self._next_cursor += 1
                            return snapshot
                store._condition.wait()


def _flatten(value, prefix=""):
    if not isinstance(value, dict):
        if prefix:
            yield prefix, value
        return
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        yield from _flatten(child, path)


def _assign_path(target, path, value):
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value
