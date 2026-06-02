<script lang="ts">
  import { theme, type Theme } from '$lib/stores/prefs';
  import Icon from './Icon.svelte';

  const order: Theme[] = ['aurum', 'auto', 'light', 'dark'];
  const icon: Record<Theme, string> = { aurum: 'bolt', auto: 'auto', light: 'sun', dark: 'moon' };
  const label: Record<Theme, string> = { aurum: 'Theme: Aurum', auto: 'Theme: Auto', light: 'Theme: Light', dark: 'Theme: Dark' };

  function cycle() {
    theme.update((t) => order[(order.indexOf(t) + 1) % order.length]);
  }
</script>

<button class="toggle" onclick={cycle} aria-label={label[$theme]} title={label[$theme]}>
  <Icon name={icon[$theme]} size={18} />
</button>

<style>
  .toggle {
    width: 38px; height: 38px; border-radius: var(--r-sm);
    border: 1px solid var(--separator); background: var(--fill-2); color: var(--label);
    display: inline-flex; align-items: center; justify-content: center;
    transition: background var(--d-fast) var(--e-standard), transform var(--d-micro) var(--e-standard);
  }
  .toggle:hover { background: var(--fill); }
  .toggle:active { transform: scale(.94); }
</style>
