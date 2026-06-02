<script lang="ts">
  // System Vitals bar — REDESIGN_AURUM §5.2. Gold-rim glass hero: agent health
  // rollup (counts by state, each with a text label) + a single "health word"
  // from the worst state + a gold throughput sparkline.
  import type { Agent, BusEvent } from '$lib/types';
  import { activity } from '$lib/util';
  import Sparkline from './Sparkline.svelte';

  let { agents = [], events = [] }: { agents?: Agent[]; events?: BusEvent[] } = $props();

  let c = $derived.by(() => {
    const o = { total: agents.length, running: 0, idle: 0, healing: 0, tripped: 0 };
    for (const a of agents) {
      const s = (a.status || 'idle').toLowerCase();
      if (a.circuit_open || s === 'error') o.tripped++;
      else if (s === 'running') o.running++;
      else if (s === 'healing') o.healing++;
      else o.idle++;
    }
    return o;
  });

  // One health word from the worst state (icon-dot + label, never colour-only).
  let health = $derived(
    agents.length === 0 ? { word: 'OFFLINE', tone: 'var(--label-3)' }
    : c.tripped > 0 ? { word: 'DEGRADED', tone: 'var(--danger)' }
    : c.healing > 0 ? { word: 'HEALING', tone: 'var(--warning)' }
    : { word: 'NOMINAL', tone: 'var(--accent)' }
  );

  let throughput = $derived(activity(events));
</script>

<section class="vitals" aria-live="polite" aria-label="System vitals">
  <div class="health" style="--tone:{health.tone}">
    <span class="hdot" aria-hidden="true"></span>
    <span class="word">{health.word}</span>
  </div>

  <p class="break">
    <b class="tnum">{c.total}</b> agents
    <span class="seg run">{c.running} running</span>
    <span class="seg">{c.idle} idle</span>
    <span class="seg heal">{c.healing} healing</span>
    <span class="seg trip">{c.tripped} tripped</span>
  </p>

  <div class="spark">
    <span class="cap">events/min</span>
    <Sparkline points={throughput} width={140} height={28} label="Event throughput, last 5 minutes" />
  </div>
</section>

<style>
  .vitals {
    display: flex; align-items: center; gap: var(--sp-5); flex-wrap: wrap;
    background: var(--material);
    -webkit-backdrop-filter: var(--material-blur);
    backdrop-filter: var(--material-blur);
    border: 1px solid var(--gold-edge);
    border-radius: var(--r-lg);
    padding: var(--sp-4) var(--sp-5);
    box-shadow: var(--e-gold);
    margin-bottom: var(--sp-5);
  }
  .health { display: inline-flex; align-items: center; gap: var(--sp-2); color: var(--tone); font-weight: 750; }
  .health .word { font-size: var(--t-callout); letter-spacing: .02em; }
  .hdot { width: 10px; height: 10px; border-radius: var(--r-pill); background: var(--tone); animation: breathe 2s ease-in-out infinite; }
  .break { margin: 0; display: inline-flex; gap: var(--sp-3); align-items: baseline; flex-wrap: wrap; color: var(--label-2); font-size: var(--t-caption); }
  .break b { color: var(--label); font-size: var(--t-title3); }
  .seg.run { color: var(--accent); }
  .seg.heal { color: var(--warning); }
  .seg.trip { color: var(--danger); }
  .spark { margin-left: auto; display: flex; flex-direction: column; align-items: flex-end; gap: 2px; min-width: 140px; }
  .cap { font-size: 11px; color: var(--label-3); font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
  @keyframes breathe { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
  @media (prefers-reduced-motion: reduce) { .hdot { animation: none !important; } }
</style>
