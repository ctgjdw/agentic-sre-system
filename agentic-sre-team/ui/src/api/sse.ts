import { useEffect, useRef, useState } from "react";
import type { StreamEvent } from "./types";

// The gateway sets `event:` per frame (runner._emit -> EventSourceResponse) and an
// `id:` = the persisted seq, so a native EventSource resends Last-Event-ID on reconnect
// and the server replays from case_events. These are the type_ names the runner emits
// (graph/runner.py + graph/deps.py + node stream_writer calls).
export const STREAM_EVENT_TYPES = [
  "node_start",
  "node_end",
  "plan",
  "tool_call",
  "worker_warning",
  "gate_waiting",
  "node_update",
  "token",
  "parked",
  "error",
  "context_added",
  "run_idle",
] as const;

// Cap retained events so a very long-running case can't grow the array unbounded.
const MAX_EVENTS = 500;

export function useCaseStream(caseId: string): { events: StreamEvent[]; connected: boolean } {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setEvents([]);
    // jsdom (test env) has no EventSource; degrade to a disconnected, empty stream so
    // screens that use this hook still render in unit tests.
    if (typeof EventSource === "undefined") {
      setConnected(false);
      return;
    }
    const source = new EventSource(`/api/cases/${caseId}/stream`);
    sourceRef.current = source;
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    const push = (type: string) => (e: MessageEvent) => {
      // A listener named "error" also catches EventSource's OWN connection-error event,
      // which is an Event (not a MessageEvent) with no `data`. Ignore those - a real
      // server `error` frame always carries a JSON payload. onerror handles reconnect UI.
      if (typeof e.data !== "string") return;
      let payload: Record<string, unknown> = {};
      try {
        payload = JSON.parse(e.data);
      } catch {
        /* malformed frame: keep the bare type */
      }
      const seq = e.lastEventId ? Number(e.lastEventId) : undefined;
      setEvents((prev) => [...prev.slice(-(MAX_EVENTS - 1)), { type, seq, ...payload }]);
    };
    for (const t of STREAM_EVENT_TYPES) {
      source.addEventListener(t, push(t));
    }
    return () => {
      source.close();
      setConnected(false);
    };
  }, [caseId]);

  return { events, connected };
}
