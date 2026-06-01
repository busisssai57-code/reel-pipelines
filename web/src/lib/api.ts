// REST client for the Python stdlib backend (server.py).
//
// Base URL resolution preserves the original dashboard contract so the hosted
// static build (bta.pages.dev) keeps working for a local user:
//   ?api=<url>  >  localStorage 'reel.apiBase'  >  legacy 'apiBase'  >  127.0.0.1:8787
// (http://127.0.0.1 is a "potentially trustworthy" origin, so an https page can
//  still call it — that's the documented local-only model.)

import type {
  Agent, Draft, BusEvent, Health, QwenStatus, RenderEventsResponse, Trend
} from './types';

function resolveBase(): string {
  let url = 'http://127.0.0.1:8787';
  try {
    const q = new URLSearchParams(location.search).get('api');
    url = q || localStorage.getItem('reel.apiBase') || localStorage.getItem('apiBase') || url;
  } catch { /* SSR / no window */ }
  return url.replace(/\/$/, '');
}

export const apiBase: string = resolveBase();

async function getJSON<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${apiBase}${path}`, { headers: { Accept: 'application/json' } });
    return res.ok ? ((await res.json()) as T) : fallback;
  } catch {
    return fallback;
  }
}

async function postJSON<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const res = await fetch(`${apiBase}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {})
    });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

export const api = {
  base: apiBase,

  health: () => getJSON<Health | null>('/api/health', null),
  agents: () => getJSON<Agent[]>('/api/agents', []),
  drafts: () => getJSON<Draft[]>('/api/drafts', []),
  events: () => getJSON<BusEvent[]>('/api/events', []),
  trends: () => getJSON<Trend[]>('/api/trends', []),
  engagement: () => getJSON<any[]>('/api/engagement', []),
  niche: () => getJSON<any[]>('/api/niche', []),
  factchecks: () => getJSON<any[]>('/api/factchecks', []),
  reviews: () => getJSON<any[]>('/api/reviews', []),
  qwenStatus: () => getJSON<QwenStatus>('/api/qwen/status', { online: false }),
  renderEvents: (jobId: string) =>
    getJSON<RenderEventsResponse>(`/api/render/${jobId}/events`, {}),

  startRender: (topic: string, visual_source: string) =>
    postJSON<{ job_id: string }>('/api/render', { topic, visual_source }),
  approve: (draftId: string | number) => postJSON('/api/approve', { draft_id: Number(draftId) }),
  reject: (draftId: string | number, regenerate = true) =>
    postJSON('/api/reject', { draft_id: Number(draftId), regenerate }),
  runNiche: () => postJSON('/api/niche/run', {}),
  resolveReview: (id: number, redo: boolean, draftId: number | null) =>
    postJSON(`/api/reviews/${id}/resolve`, { redo, draft_id: draftId }),
  qwenChat: (messages: { role: string; content: string }[]) =>
    postJSON<{ reply: string; offline?: boolean }>('/api/qwen/chat', { messages })
};
