<script lang="ts">
  // Tiny activity chart. Renders bars from `points`; width is the viewBox
  // coordinate space and the SVG stretches to fill its container.
  let { points = [], width = 160, height = 28, label = '' }:
    { points?: number[]; width?: number; height?: number; label?: string } = $props();

  let max = $derived(points.length ? Math.max(1, ...points) : 1);
  let bw = $derived(width / Math.max(points.length, 1));
  const barH = (v: number, max: number, height: number) => Math.max(2, (v / max) * (height - 2));
</script>

<svg class="spark" width="100%" height={height} viewBox="0 0 {width} {height}"
     preserveAspectRatio="none" role="img" aria-label={label}>
  {#each points as v, i}
    <rect x={i * bw + 0.4} y={height - barH(v, max, height)}
          width={Math.max(0.8, bw - 1)} height={barH(v, max, height)} rx="0.8"
          class:empty={v === 0} />
  {/each}
</svg>

<style>
  .spark { display: block; }
  .spark rect { fill: var(--gold); opacity: .9; }
  .spark rect.empty { fill: var(--separator); opacity: 1; }
</style>
