<script lang="ts">
  let {
    width = '100%',
    height = '16px',
    radius = 'var(--r-sm)'
  }: { width?: string; height?: string; radius?: string } = $props();
</script>

<span class="sk" style="width:{width};height:{height};border-radius:{radius}" aria-hidden="true"></span>

<style>
  .sk {
    display: block;
    background: linear-gradient(90deg, var(--fill-2) 25%, var(--fill) 37%, var(--fill-2) 63%);
    background-size: 400% 100%;
    animation: shimmer 1.4s ease infinite;
  }
  @keyframes shimmer { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }
</style>
