<script lang="ts">
  import Icon from './Icon.svelte';
  let {
    icon = 'bolt',
    title,
    phase = '',
    children
  }: { icon?: string; title: string; phase?: string; children?: import('svelte').Snippet } = $props();
</script>

<div class="ph panel">
  <div class="ico"><Icon name={icon} size={28} /></div>
  <h2>{title}</h2>
  {#if phase}<span class="badge accent">{phase}</span>{/if}
  <p class="muted">
    {#if children}{@render children()}{:else}This surface is specced in docs/UPGRADE_PLAN.md and lands in a later phase.{/if}
  </p>
</div>

<style>
  .ph { display: flex; flex-direction: column; align-items: flex-start; gap: var(--sp-3); max-width: 640px; }
  .ico {
    width: 54px; height: 54px; border-radius: var(--r-md);
    display: grid; place-items: center; color: var(--accent);
    background: color-mix(in srgb, var(--accent) 14%, transparent);
  }
  h2 { font-size: var(--t-title2); }
  p { margin: 0; line-height: 1.55; }
</style>
