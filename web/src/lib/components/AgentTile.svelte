<script lang="ts">
  // Enhanced agent card (replaces AgentCard) — REDESIGN_AURUM §5.4. Icon in an
  // animated StatusRing, a gold activity Sparkline, an outcome-score gauge (when
  // the backend exposes it), and a circuit gauge. Every status carries an icon +
  // text label, never colour alone.
  import type { Agent } from '$lib/types';
  import { relTime } from '$lib/util';
  import Icon from './Icon.svelte';
  import StatusRing from './StatusRing.svelte';
  import Sparkline from './Sparkline.svelte';
  import Gauge from './Gauge.svelte';

  let { agent, activity = [] }: { agent: Agent; activity?: number[] } = $props();

  let status = $derived((agent.status || 'idle').toLowerCase());
  let la = $derived(agent.last_action);
  let score = $derived(typeof agent.score === 'number' ? agent.score : null);

  // Circuit health: closed (blue) / healing → half (orange) / open (red).
  let circuit = $derived(
    agent.circuit_open
      ? { v: 0, tone: 'var(--danger)', icon: 'alert', label: 'Open' }
      : status === 'healing'
        ? { v: 0.5, tone: 'var(--warning)', icon: 'gauge', label: 'Half-open' }
        : { v: 1, tone: 'var(--accent)', icon: 'check', label: 'Closed' }
  );
</script>

<div class="tile {status}">
  <div class="head">
    <StatusRing {status} size={40} />
    <div class="id">
      <span class="name">{agent.name}</span>
      {#if agent.role}<span class="role muted">{agent.role}</span>{/if}
    </div>
    <span class="pill {status}"><span class="dot" aria-hidden="true"></span>{status}</span>
  </div>

  <Sparkline points={activity} height={26} label={`${agent.name} recent activity`} />

  <dl class="meta">
    <div>
      <dt>Did</dt>
      <dd>
        {#if la}<b>{la.type || '—'}</b>{#if la.note} · {la.note}{/if} <span class="t">({relTime(la.ts)})</span>{:else}—{/if}
      </dd>
    </div>
    <div><dt>Reacts</dt><dd>{agent.waits_for || '—'}</dd></div>
    {#if score !== null}
      <div>
        <dt>Score</dt>
        <dd class="g"><Gauge value={score} tone="var(--gold)" /> <span class="tnum">{score.toFixed(2)}</span></dd>
      </div>
    {/if}
    <div>
      <dt>Circuit</dt>
      <dd class="g" style="color:{circuit.tone}">
        <Gauge value={circuit.v} segments={3} tone={circuit.tone} />
        <Icon name={circuit.icon} size={13} /> {circuit.label}
      </dd>
    </div>
  </dl>
</div>

<style>
  .tile {
    background: var(--material);
    -webkit-backdrop-filter: var(--material-blur);
    backdrop-filter: var(--material-blur);
    border: 1px solid var(--separator);
    border-radius: var(--r-md);
    padding: var(--sp-4);
    box-shadow: var(--e-1);
    display: flex; flex-direction: column; gap: var(--sp-3);
    transition: transform var(--d-base) var(--e-standard),
                box-shadow var(--d-base) var(--e-standard),
                border-color var(--d-fast) var(--e-standard);
  }
  /* Premium hover: lift + the Aurum gold rim. */
  .tile:hover { transform: translateY(-4px); border-color: var(--gold-edge); box-shadow: var(--e-gold); }
  .tile.error { border-color: color-mix(in srgb, var(--danger) 45%, var(--separator)); }

  .head { display: flex; align-items: center; gap: var(--sp-3); }
  .id { display: flex; flex-direction: column; min-width: 0; flex: 1; }
  .name { font-weight: 700; }
  .role { font-size: var(--t-caption); }
  .pill {
    display: inline-flex; align-items: center; gap: 6px; flex: none;
    font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: var(--r-pill);
    background: var(--fill); color: var(--label-2); text-transform: capitalize;
  }
  .pill .dot { width: 7px; height: 7px; border-radius: var(--r-pill); background: var(--label-3); }
  .pill.running { background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); }
  .pill.running .dot { background: var(--accent); animation: breathe 2s ease-in-out infinite; }
  .pill.healing { background: color-mix(in srgb, var(--warning) 20%, transparent); color: var(--warning); }
  .pill.healing .dot { background: var(--warning); animation: breathe 1.4s ease-in-out infinite; }
  .pill.error { background: color-mix(in srgb, var(--danger) 18%, transparent); color: var(--danger); }

  .meta { margin: 0; display: grid; gap: 6px; font-size: var(--t-caption); }
  .meta > div { display: grid; grid-template-columns: 56px 1fr; gap: var(--sp-2); align-items: center; }
  dt { color: var(--label-3); font-weight: 700; }
  dd { margin: 0; color: var(--label-2); min-width: 0; }
  .t { color: var(--label-3); }
  .g { display: inline-flex; align-items: center; gap: 8px; }
  @keyframes breathe { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
  @media (prefers-reduced-motion: reduce) { .pill .dot { animation: none !important; } }
</style>
