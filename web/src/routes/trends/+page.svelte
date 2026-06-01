<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Trend } from '$lib/types';

  let trends = $state<Trend[]>([]);
  let loaded = $state(false);
  onMount(async () => { trends = await api.trends(); loaded = true; });
</script>

<div class="panel">
  {#if !loaded}
    <p class="empty">Loading trends…</p>
  {:else if trends.length === 0}
    <p class="empty">No trending topics discovered yet. The trend cycle runs on a schedule (or trigger it from the backend).</p>
  {:else}
    <table class="tbl">
      <thead><tr><th>Topic</th><th>Source</th><th>Score</th></tr></thead>
      <tbody>
        {#each trends.slice(0, 20) as t, i (i)}
          <tr>
            <td>{t.topic}</td>
            <td><span class="badge">{t.source}</span></td>
            <td class="tnum">{(t.score ?? 0).toFixed(2)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<style>
  .tbl { width: 100%; border-collapse: collapse; font-size: var(--t-body); }
  .tbl th { text-align: left; color: var(--label-2); font-weight: 700; padding: 10px 12px; border-bottom: 1px solid var(--separator); }
  .tbl td { padding: 12px; border-bottom: 1px solid var(--separator); }
  .tbl tr:last-child td { border-bottom: 0; }
  .tbl td:last-child, .tbl th:last-child { text-align: right; }
</style>
