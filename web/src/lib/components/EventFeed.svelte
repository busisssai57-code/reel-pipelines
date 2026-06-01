<script lang="ts">
  import type { BusEvent } from '$lib/types';
  import { relTime } from '$lib/util';
  import { fly } from 'svelte/transition';
  import { flip } from 'svelte/animate';
  import { d } from '$lib/motion';

  let { events = [], limit = 60 }: { events?: BusEvent[]; limit?: number } = $props();

  // Stable key so flip/transition animate real inserts (not full re-render).
  const keyOf = (e: BusEvent, i: number) => `${e.ts}-${e.agent}-${e.type}-${i}`;
  let rows = $derived(events.slice(0, limit));
</script>

{#if rows.length === 0}
  <div class="empty">No agent activity yet. Start a render to see agents work live.</div>
{:else}
  <ul class="feed">
    {#each rows as e, i (keyOf(e, i))}
      <li class="row" in:fly={{ y: -6, duration: d(220) }} animate:flip={{ duration: d(320) }}>
        <span class="agent">{e.agent || '—'}</span>
        <span class="type">{e.type || ''}</span>
        <span class="note">{e.note || ''}</span>
        <span class="time">{relTime(e.ts)}</span>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .feed { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .row {
    display: grid;
    grid-template-columns: 140px auto 1fr auto;
    gap: var(--sp-3); align-items: baseline;
    padding: 8px 4px; border-bottom: 1px solid var(--separator);
    font-size: var(--t-caption);
  }
  .agent { font-weight: 700; color: var(--label-2); }
  .type { color: var(--accent); font-weight: 700; }
  .note { color: var(--label-2); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .time { color: var(--label-3); white-space: nowrap; }
  @media (max-width: 600px) {
    .row { grid-template-columns: 1fr auto; row-gap: 2px; }
    .note { grid-column: 1 / -1; white-space: normal; }
  }
</style>
