// Shared live state. Primary transport is SSE (GET /api/stream); when the
// stream is open the REST poll slows to a safety-net cadence. Without SSE
// support it stays on the fast poll. One instance feeds every view.

import { writable } from 'svelte/store';
import { api } from '../api';
import { connectStream, type StreamHandle } from '../stream';
import type { Agent, Draft, BusEvent, Health, QwenStatus } from '../types';

export type Transport = 'sse' | 'poll' | 'offline';

export interface LiveState {
  connected: boolean;
  transport: Transport;
  health: Health | null;
  agents: Agent[];
  drafts: Draft[];
  events: BusEvent[];
  qwen: QwenStatus | null;
  lastUpdated: number;
}

export const live = writable<LiveState>({
  connected: false,
  transport: 'offline',
  health: null,
  agents: [],
  drafts: [],
  events: [],
  qwen: null,
  lastUpdated: 0
});

const FAST = 3500;
const SLOW = 20000;

let pollTimer: ReturnType<typeof setInterval> | null = null;
let draftsTimer: ReturnType<typeof setTimeout> | null = null;
let sse: StreamHandle | null = null;
let sseOpen = false;
let started = false;

async function pollOnce(): Promise<void> {
  const [health, agents, drafts, events, qwen] = await Promise.all([
    api.health(), api.agents(), api.drafts(), api.events(), api.qwenStatus()
  ]);
  const connected = !!health || agents.length > 0;
  live.update((s) => ({
    ...s,
    connected,
    transport: connected ? (sseOpen ? 'sse' : 'poll') : 'offline',
    health, agents, drafts, events, qwen,
    lastUpdated: Date.now()
  }));
}

function setPoll(ms: number): void {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => void pollOnce(), ms);
}

// Debounced drafts refetch when a streamed event implies the draft set changed
// (SSE carries events, not the aggregate drafts list).
const DRAFT_RE = /approv|reject|render_done|replacement_ready|publish|quarantin|job_created/i;
function refreshDraftsSoon(): void {
  if (draftsTimer) return;
  draftsTimer = setTimeout(async () => {
    draftsTimer = null;
    const drafts = await api.drafts();
    live.update((s) => ({ ...s, drafts, lastUpdated: Date.now() }));
  }, 800);
}
function maybeRefreshDrafts(ev: BusEvent): void {
  const t = (ev?.type || '').toLowerCase();
  const a = (ev?.agent || '').toLowerCase();
  if (DRAFT_RE.test(t) || a === 'ui') refreshDraftsSoon();
}

export function startLive(): void {
  if (started) return;
  started = true;
  void pollOnce();
  setPoll(FAST);

  void connectStream(
    (e) => {
      if (e.type === 'snapshot') {
        live.update((s) => ({
          ...s,
          agents: e.data?.agents ?? s.agents,
          qwen: e.data?.qwen ?? s.qwen,
          connected: true, transport: 'sse', lastUpdated: Date.now()
        }));
      } else if (e.type === 'agent_status') {
        live.update((s) => ({
          ...s,
          agents: Array.isArray(e.data) ? e.data : s.agents,
          connected: true, transport: 'sse', lastUpdated: Date.now()
        }));
      } else if (e.type === 'event') {
        live.update((s) => ({
          ...s,
          events: [e.data, ...s.events].slice(0, 80),
          connected: true, transport: 'sse', lastUpdated: Date.now()
        }));
        maybeRefreshDrafts(e.data);
      } else if (e.type === 'qwen_status') {
        live.update((s) => ({ ...s, qwen: e.data }));
      }
    },
    (state) => {
      if (state === 'open') {
        sseOpen = true;
        live.update((s) => ({ ...s, transport: 'sse', connected: true }));
        setPoll(SLOW);
      } else {
        sseOpen = false;
        setPoll(FAST);
        live.update((s) => ({ ...s, transport: s.connected ? 'poll' : 'offline' }));
      }
    },
    () => { /* SSE unsupported: stay on the fast poll */ }
  ).then((h) => {
    // If stopLive() ran while connectStream was still awaiting, close the
    // freshly opened connection instead of leaking it (started is cleared by
    // stopLive, so a live handle here would otherwise be unreachable).
    if (started) sse = h;
    else h.close();
  });
}

export function stopLive(): void {
  started = false;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  if (draftsTimer) clearTimeout(draftsTimer);
  draftsTimer = null;
  sse?.close();
  sse = null;
  sseOpen = false;
}

export function refreshNow(): void {
  void pollOnce();
}
