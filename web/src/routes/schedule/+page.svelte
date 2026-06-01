<script lang="ts">
  import Placeholder from '$lib/components/Placeholder.svelte';
</script>

<Placeholder icon="schedule" title="Schedule" phase="Phase 4">
  The Mon–Sun week grid with draggable, keyboard-reorderable category-colored chips
  (backed by a new <code>/api/schedule</code> + SchedulerOptimizer agent) lands in Phase 4.
</Placeholder>

<style>
  code { font-family: var(--font-mono); font-size: .9em; background: var(--fill-2); padding: 1px 6px; border-radius: 6px; }
</style>
