<script lang="ts">
  import { tweened } from 'svelte/motion';
  import { cubicOut } from 'svelte/easing';
  import { d } from '$lib/motion';

  let { label, value = 0, accent = false }: { label: string; value?: number; accent?: boolean } = $props();

  const n = tweened(0, { duration: d(600), easing: cubicOut });
  $effect(() => { n.set(value); });
</script>

<div class="stat" class:accent>
  <div class="val tnum">{Math.round($n)}</div>
  <div class="lab">{label}</div>
</div>

<style>
  .stat {
    background: var(--material);
    -webkit-backdrop-filter: var(--material-blur);
    backdrop-filter: var(--material-blur);
    border: 1px solid var(--separator);
    border-radius: var(--r-md);
    padding: var(--sp-5);
    box-shadow: var(--e-1);
    transition: transform var(--d-fast) var(--e-standard), border-color var(--d-fast) var(--e-standard);
  }
  .stat:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--accent) 50%, var(--separator)); }
  .val { font-size: var(--t-large); font-weight: 750; letter-spacing: -0.03em; line-height: 1; }
  .accent .val { color: var(--accent); }
  .lab { margin-top: var(--sp-2); font-size: var(--t-caption); color: var(--label-2); font-weight: 650; text-transform: uppercase; letter-spacing: .04em; }
</style>
