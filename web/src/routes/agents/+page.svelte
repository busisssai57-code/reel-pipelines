<script lang="ts">
  import { live } from '$lib/stores/live';
  import { flip } from 'svelte/animate';
  import { d } from '$lib/motion';
  import { activity, statusRank } from '$lib/util';
  import AgentTile from '$lib/components/AgentTile.svelte';
  import SystemVitals from '$lib/components/SystemVitals.svelte';

  // Problems first, then active, then idle — re-sorts animate via FLIP.
  let agents = $derived([...$live.agents].sort((a, b) => statusRank(a) - statusRank(b)));
</script>

<SystemVitals agents={$live.agents} events={$live.events} />

{#if $live.agents.length === 0}
  <p class="empty">No agents reporting. Start the backend with <code>run.py ai-team</code>.</p>
{:else}
  <div class="grid cards">
    {#each agents as agent (agent.name)}
      <div animate:flip={{ duration: d(320) }}>
        <AgentTile {agent} activity={activity($live.events, agent.name)} />
      </div>
    {/each}
  </div>
{/if}

<style>
  code { font-family: var(--font-mono); font-size: .9em; background: var(--fill-2); padding: 1px 6px; border-radius: 6px; }
</style>
