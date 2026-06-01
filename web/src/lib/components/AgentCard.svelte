<script lang="ts">
  import type { Agent } from '$lib/types';
  import { relTime } from '$lib/util';
  import Icon from './Icon.svelte';

  let { agent }: { agent: Agent } = $props();
  let status = $derived(agent.status || 'idle');
  let la = $derived(agent.last_action);
</script>

<div class="agent {status}">
  <div class="head">
    <span class="name">{agent.name}</span>
    <span class="pill {status}">
      <span class="dot" aria-hidden="true"></span>{status}
    </span>
  </div>
  {#if agent.role}<div class="role muted">{agent.role}</div>{/if}
  <dl class="meta">
    <div>
      <dt>Did</dt>
      <dd>
        {#if la}
          <b>{la.type || '—'}</b>{#if la.note} · {la.note}{/if}
          <span class="time">({relTime(la.ts)})</span>
        {:else}—{/if}
      </dd>
    </div>
    <div><dt>Next</dt><dd>waits for {agent.waits_for || '—'}</dd></div>
    <div>
      <dt>Circuit</dt>
      <dd class="circuit" class:open={agent.circuit_open}>
        <Icon name={agent.circuit_open ? 'alert' : 'check'} size={14} />
        {agent.circuit_open ? 'Open' : 'Closed'}
      </dd>
    </div>
  </dl>
</div>

<style>
  .agent {
    background: var(--material);
    -webkit-backdrop-filter: var(--material-blur);
    backdrop-filter: var(--material-blur);
    border: 1px solid var(--separator);
    border-radius: var(--r-md);
    padding: var(--sp-4);
    box-shadow: var(--e-1);
    transition: border-color var(--d-fast) var(--e-standard);
  }
  .agent.error { border-color: color-mix(in srgb, var(--danger) 45%, var(--separator)); }
  .head { display: flex; align-items: center; justify-content: space-between; }
  .name { font-weight: 700; }
  .role { font-size: var(--t-caption); margin-top: 2px; }
  .pill {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: var(--r-pill);
    background: var(--fill); color: var(--label-2); text-transform: capitalize;
  }
  .pill .dot { width: 7px; height: 7px; border-radius: var(--r-pill); background: var(--label-3); }
  .pill.running { background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); }
  .pill.running .dot { background: var(--accent); animation: breathe 2s ease-in-out infinite; }
  .pill.healing { background: color-mix(in srgb, var(--warning) 20%, transparent); color: var(--warning); }
  .pill.healing .dot { background: var(--warning); animation: breathe 1.4s ease-in-out infinite; }
  .pill.error { background: color-mix(in srgb, var(--danger) 18%, transparent); color: var(--danger); }
  .meta { margin: var(--sp-3) 0 0; display: grid; gap: 6px; font-size: var(--t-caption); }
  .meta div { display: grid; grid-template-columns: 56px 1fr; gap: var(--sp-2); }
  dt { color: var(--label-3); font-weight: 700; }
  dd { margin: 0; color: var(--label-2); }
  .time { color: var(--label-3); }
  .circuit { display: inline-flex; align-items: center; gap: 5px; color: var(--success); }
  .circuit.open { color: var(--danger); }
  @keyframes breathe { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
</style>
