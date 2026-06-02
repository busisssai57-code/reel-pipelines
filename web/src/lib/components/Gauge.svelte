<script lang="ts">
  // Tiny segmented meter for circuit strength / outcome score. Pips fill
  // left-to-right in `tone`. Decorative only — the caller always pairs it with
  // an icon + text label (status is never colour-only; REDESIGN_AURUM §6).
  let { value = 0, segments = 5, tone = 'var(--gold)' }:
    { value?: number; segments?: number; tone?: string } = $props();

  let filled = $derived(Math.round(Math.max(0, Math.min(1, value)) * segments));
</script>

<span class="gauge" style="--tone:{tone}" aria-hidden="true">
  {#each Array(segments) as _, i}
    <span class="pip" class:on={i < filled}></span>
  {/each}
</span>

<style>
  .gauge { display: inline-flex; gap: 3px; align-items: center; }
  .pip {
    width: 6px; height: 6px; border-radius: 2px; background: var(--fill);
    transition: background var(--d-fast) var(--e-standard);
  }
  .pip.on { background: var(--tone); }
</style>
