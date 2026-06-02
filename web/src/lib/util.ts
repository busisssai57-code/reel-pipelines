import type { Agent, BusEvent } from './types';

export function relTime(ts?: number): string {
  if (!ts) return '';
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function categoryClass(cat?: string): string {
  const c = (cat || 'default').toLowerCase();
  return ['history', 'geography', 'science'].includes(c) ? c : 'default';
}

export function titleCase(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

// Bucket event timestamps into a small histogram for sparklines. Pass `agent`
// to count one agent's events; omit for global throughput. `ts` is in seconds
// (see relTime), windowed to the last `windowSec`.
export function activity(events: BusEvent[], agent?: string, buckets = 12, windowSec = 300): number[] {
  const now = Date.now() / 1000;
  const start = now - windowSec;
  const span = windowSec / buckets;
  const out = new Array(buckets).fill(0);
  const want = agent?.toLowerCase();
  for (const e of events) {
    if (want && (e.agent || '').toLowerCase() !== want) continue;
    const ts = e.ts || 0;
    if (ts < start || ts > now) continue;
    out[Math.min(buckets - 1, Math.floor((ts - start) / span))]++;
  }
  return out;
}

// Sort order for the agents grid: problems first, then active, then idle.
const STATUS_RANK: Record<string, number> = { error: 1, healing: 2, running: 3, idle: 4 };
export function statusRank(a: Agent): number {
  if (a.circuit_open) return 0; // tripped circuits float to the top
  return STATUS_RANK[(a.status || 'idle').toLowerCase()] ?? 4;
}
