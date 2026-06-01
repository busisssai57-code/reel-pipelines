<script lang="ts">
  import { live } from '$lib/stores/live';

  let label = $derived(
    $live.transport === 'sse' ? 'Live' : $live.connected ? 'Connected' : 'Offline'
  );
  let kind = $derived(
    $live.transport === 'sse' ? 'live' : $live.connected ? 'poll' : 'offline'
  );
</script>

<span class="chip {kind}" role="status" aria-live="polite">
  <span class="led" aria-hidden="true"></span>
  {label}
</span>

<style>
  .chip {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 5px 12px; border-radius: var(--r-pill);
    font-size: var(--t-caption); font-weight: 700;
    border: 1px solid var(--separator); background: var(--fill-2); color: var(--label-2);
  }
  .led { width: 9px; height: 9px; border-radius: var(--r-pill); background: var(--label-3); }
  .chip.live { color: var(--success); }
  .chip.live .led { background: var(--success); animation: pulse 2s ease-in-out infinite; }
  .chip.poll { color: var(--accent); }
  .chip.poll .led { background: var(--accent); }
  .chip.offline { color: var(--warning); }
  .chip.offline .led { background: var(--warning); }
  @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .4; transform: scale(.82); } }
</style>
