<script lang="ts">
  import { live } from '$lib/stores/live';
  import { flip } from 'svelte/animate';
  import { d } from '$lib/motion';
  import StatCard from '$lib/components/StatCard.svelte';
  import AgentCard from '$lib/components/AgentCard.svelte';
  import EventFeed from '$lib/components/EventFeed.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  let drafts = $derived($live.drafts);
  let counts = $derived({
    total: drafts.length,
    pending: drafts.filter((x) => x.status === 'pending').length,
    approved: drafts.filter((x) => x.status === 'approved').length,
    published: drafts.filter((x) => x.status === 'published').length
  });
  let loading = $derived($live.lastUpdated === 0);
</script>

<section class="grid tiles" aria-label="Overview">
  <StatCard label="Total Reels" value={counts.total} accent />
  <StatCard label="Pending" value={counts.pending} />
  <StatCard label="Approved" value={counts.approved} />
  <StatCard label="Published" value={counts.published} />
</section>

<h2 class="section-title">AI Agents</h2>
{#if loading}
  <div class="grid cards">
    {#each Array(4) as _}
      <div class="panel"><Skeleton height="20px" width="50%" /><div style="height:10px"></div><Skeleton height="48px" /></div>
    {/each}
  </div>
{:else if $live.agents.length === 0}
  <p class="empty">No agents reporting. Start the backend with <code>run.py ai-team</code>.</p>
{:else}
  <div class="grid cards">
    {#each $live.agents as agent (agent.name)}
      <div animate:flip={{ duration: d(320) }}><AgentCard {agent} /></div>
    {/each}
  </div>
{/if}

<h2 class="section-title">Recent Activity</h2>
<div class="panel feed-panel">
  <EventFeed events={$live.events} />
</div>

<style>
  .feed-panel { max-height: 360px; overflow-y: auto; }
  code { font-family: var(--font-mono); font-size: .9em; background: var(--fill-2); padding: 1px 6px; border-radius: 6px; }
</style>
