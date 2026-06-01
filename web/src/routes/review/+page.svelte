<script lang="ts">
  import Placeholder from '$lib/components/Placeholder.svelte';
</script>

<Placeholder icon="review" title="Reviewer (QA gate)" phase="Phase 2">
  The reviewer checks every agent's work; redos are <b>gated</b> — it flags &amp; proposes, you approve.
  Findings from <code>/api/reviews</code> with approve-redo / dismiss (and undo) land here in Phase 2.
</Placeholder>

<style>
  code { font-family: var(--font-mono); font-size: .9em; background: var(--fill-2); padding: 1px 6px; border-radius: 6px; }
</style>
