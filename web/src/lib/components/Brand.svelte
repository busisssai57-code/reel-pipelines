<script lang="ts">
  let { compact = false }: { compact?: boolean } = $props();
</script>

<div class="brand" class:compact>
  <span class="mark" aria-hidden="true"></span>
  {#if !compact}<span class="name">Reel Studio</span>{/if}
</div>

<style>
  .brand { display: flex; align-items: center; gap: var(--sp-3); font-weight: 750; font-size: var(--t-callout); }
  .mark {
    width: 26px; height: 26px; border-radius: 8px;
    background: linear-gradient(135deg, var(--accent), #2ad0c0);
    box-shadow: 0 4px 12px color-mix(in srgb, var(--accent) 30%, transparent);
    position: relative;
  }
  .mark::after {
    content: ''; position: absolute; inset: 0; margin: auto;
    width: 0; height: 0; border-style: solid;
    border-width: 6px 0 6px 9px; border-color: transparent transparent transparent #fff;
    transform: translateX(1px);
  }
  .name { letter-spacing: -0.02em; }
</style>
