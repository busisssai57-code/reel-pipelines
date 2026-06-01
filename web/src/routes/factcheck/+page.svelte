<script lang="ts">
  import Placeholder from '$lib/components/Placeholder.svelte';
</script>

<Placeholder icon="factcheck" title="Fact-Check" phase="Phase 2">
  Per-claim verdicts (supported / uncertain / contradicted, each shown with icon + text + color)
  from <code>/api/factchecks</code> render here in Phase 2.
</Placeholder>

<style>
  code { font-family: var(--font-mono); font-size: .9em; background: var(--fill-2); padding: 1px 6px; border-radius: 6px; }
</style>
