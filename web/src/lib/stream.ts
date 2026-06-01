// Live transport: prefer SSE (GET /api/stream), fall back to polling.
//
// The current backend has no /api/stream yet (lands in Phase 1 of the upgrade
// plan). So connectStream() PROBES first: if the endpoint isn't a live
// event-stream, it reports `unsupported` and the caller stays on polling.
// When P1 ships the SSE endpoint this upgrades automatically — no UI change.

import { apiBase } from './api';

export type StreamEvent = { type: string; data: any };

export interface StreamHandle {
  close: () => void;
}

/**
 * Try to open an SSE connection. Calls onEvent for each message and onState
 * with 'open' | 'closed'. If the endpoint is unavailable, calls
 * onUnsupported() exactly once and does not retry aggressively.
 */
export async function connectStream(
  onEvent: (e: StreamEvent) => void,
  onState: (s: 'open' | 'closed') => void,
  onUnsupported: () => void
): Promise<StreamHandle> {
  const noop: StreamHandle = { close: () => {} };
  if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
    onUnsupported();
    return noop;
  }

  // Probe with a short-lived fetch so a 404 doesn't trigger EventSource's
  // infinite reconnect loop against a missing endpoint.
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2500);
    const res = await fetch(`${apiBase}/api/stream`, {
      headers: { Accept: 'text/event-stream' },
      signal: ctrl.signal
    });
    clearTimeout(t);
    const ctype = res.headers.get('content-type') || '';
    if (!res.ok || !ctype.includes('text/event-stream')) {
      onUnsupported();
      return noop;
    }
    // Don't hold the probe stream open.
    try { res.body?.cancel(); } catch { /* ignore */ }
  } catch {
    onUnsupported();
    return noop;
  }

  const es = new EventSource(`${apiBase}/api/stream`);
  es.onopen = () => onState('open');
  es.onerror = () => onState('closed'); // EventSource auto-reconnects
  es.onmessage = (ev) => {
    try {
      onEvent({ type: 'message', data: JSON.parse(ev.data) });
    } catch {
      /* ignore malformed frame */
    }
  };
  // Named events the P1 backend will emit (agent_status, event, render_stage…).
  for (const name of ['snapshot', 'agent_status', 'event', 'render_stage', 'draft_changed', 'qwen_status']) {
    es.addEventListener(name, (ev: MessageEvent) => {
      try {
        onEvent({ type: name, data: JSON.parse(ev.data) });
      } catch {
        /* ignore */
      }
    });
  }
  return { close: () => es.close() };
}
