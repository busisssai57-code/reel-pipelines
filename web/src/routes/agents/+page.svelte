<script lang="ts">
  import { live } from '$lib/stores/live';
  import { flip } from 'svelte/animate';
  import { d } from '$lib/motion';
  import AgentCard from '$lib/components/AgentCard.svelte';
</script>

{#if $live.agents.length === 0}
  <p class="empty">No agents reporting. Start the backend with <code>run.py ai-team</code>.</p>
{:else}
  <div class="grid cards">
    {#each $live.agents as agent (agent.name)}
      <div animate:flip={{ duration: d(320) }}><AgentCard {agent} /></div>
    {/each}
  </div>
{/if}

<style>
  code { font-family: var(--font-mono); font-size: .9em; background: var(--fill-2); padding: 1px 6px; border-radius: 6px; }
</style>
