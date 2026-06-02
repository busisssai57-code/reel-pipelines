<script lang="ts">
  import Icon from './Icon.svelte';

  let { status = 'idle', icon = 'agents', size = 44 }:
    { status?: string; icon?: string; size?: number } = $props();

  const tone = (s: string) =>
    s === 'running' ? 'var(--accent)'
    : s === 'healing' ? 'var(--warning)'
    : s === 'error' ? 'var(--danger)'
    : 'var(--gold)';

  let active = $derived(status === 'running' || status === 'healing');
  let r = $derived(size / 2 - 2);
  let c = $derived(2 * Math.PI * r);
</script>

<span class="ring" class:active style="width:{size}px; height:{size}px; --tone:{tone(status)}">
  <svg class="svg" class:spin={active} width={size} height={size} viewBox="0 0 {size} {size}" aria-hidden="true">
    <circle class="track" cx={size / 2} cy={size / 2} r={r} />
    <circle class="arc" cx={size / 2} cy={size / 2} r={r} stroke-dasharray="{c * 0.72} {c}" />
  </svg>
  <span class="ico" style="color:{tone(status)}"><Icon name={icon} size={Math.round(size * 0.42)} /></span>
</span>

<style>
  .ring { position: relative; display: inline-grid; place-items: center; flex: none; }
  .svg { position: absolute; inset: 0; }
  .track { fill: none; stroke: var(--separator); stroke-width: 2; }
  .arc {
    fill: none; stroke: var(--tone); stroke-width: 2.5; stroke-linecap: round;
    transition: stroke var(--d-base) var(--e-standard);
  }
  .svg.spin { animation: ring-spin 3.2s linear infinite; transform-origin: center; }
  .ico { position: relative; display: inline-flex; }
  @keyframes ring-spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .svg.spin { animation: none; } }
</style>
