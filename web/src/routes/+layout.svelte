<script lang="ts">
  import '@fontsource-variable/inter';
  import '$lib/styles/tokens.css';
  import '$lib/styles/util.css';

  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { base } from '$app/paths';
  import { onNavigate } from '$app/navigation';
  import { get } from 'svelte/store';
  import { fly, fade } from 'svelte/transition';

  import { startLive, stopLive, refreshNow } from '$lib/stores/live';
  import { toasts } from '$lib/stores/toast';
  import { prefersReducedMotion, d } from '$lib/motion';

  import Brand from '$lib/components/Brand.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import SyncChip from '$lib/components/SyncChip.svelte';
  import ThemeToggle from '$lib/components/ThemeToggle.svelte';

  let { children } = $props();

  const nav = [
    { key: 'dashboard', label: 'Dashboard', icon: 'dashboard', href: `${base}/` },
    { key: 'render', label: 'Render', icon: 'render', href: `${base}/render` },
    { key: 'drafts', label: 'Drafts', icon: 'drafts', href: `${base}/drafts` },
    { key: 'agents', label: 'Agents', icon: 'agents', href: `${base}/agents` },
    { key: 'trends', label: 'Trends', icon: 'trends', href: `${base}/trends` },
    { key: 'niche', label: 'Niche', icon: 'niche', href: `${base}/niche` },
    { key: 'factcheck', label: 'Fact-Check', icon: 'factcheck', href: `${base}/factcheck` },
    { key: 'review', label: 'Review', icon: 'review', href: `${base}/review` },
    { key: 'queen', label: 'Queen', icon: 'queen', href: `${base}/queen` },
    { key: 'schedule', label: 'Schedule', icon: 'schedule', href: `${base}/schedule` },
    { key: 'settings', label: 'Settings', icon: 'settings', href: `${base}/settings` }
  ];
  const tabKeys = ['dashboard', 'render', 'drafts', 'agents', 'queen'];

  let seg = $derived.by(() => {
    let p: string = $page.url.pathname;
    if (base && p.startsWith(base)) p = p.slice(base.length);
    p = p.replace(/^\/+/, '').replace(/\/+$/, '');
    return p.split('/')[0] || 'dashboard';
  });
  let title = $derived(nav.find((n) => n.key === seg)?.label ?? 'Dashboard');

  // T1 — route-level View Transitions (graceful no-op without support / reduced motion).
  onNavigate((navigation) => {
    if (!document.startViewTransition || get(prefersReducedMotion)) return;
    return new Promise<void>((resolve) => {
      document.startViewTransition(async () => {
        resolve();
        await navigation.complete;
      });
    });
  });

  onMount(startLive);
  onDestroy(stopLive);
</script>

<a href="#main" class="skip">Skip to content</a>

<div class="app">
  <aside class="side" aria-label="Primary">
    <div class="side-brand"><Brand /></div>
    <nav class="side-nav" aria-label="Primary">
      {#each nav as item (item.key)}
        <a class="nav-link" href={item.href} aria-current={seg === item.key ? 'page' : undefined}>
          <span class="ico"><Icon name={item.icon} size={19} /></span>
          <span>{item.label}</span>
        </a>
      {/each}
    </nav>
  </aside>

  <header class="topbar">
    <h1 class="page-title">{title}</h1>
    <div class="row">
      <SyncChip />
      <button class="btn sm" onclick={refreshNow} aria-label="Refresh"><Icon name="refresh" size={16} /></button>
      <ThemeToggle />
    </div>
  </header>

  <main id="main">
    {@render children()}
  </main>

  <nav class="tabs" aria-label="Primary (mobile)">
    {#each nav.filter((n) => tabKeys.includes(n.key)) as item (item.key)}
      <a class="tab" href={item.href} aria-current={seg === item.key ? 'page' : undefined}>
        <Icon name={item.icon} size={22} />
        <span>{item.label}</span>
      </a>
    {/each}
  </nav>
</div>

<!-- Toast host -->
<div class="toast-host" aria-live="polite">
  {#each $toasts as t (t.id)}
    <div class="toast {t.kind}" in:fly={{ y: 40, duration: d(280) }} out:fade={{ duration: d(180) }}>
      {t.msg}
    </div>
  {/each}
</div>

<style>
  .skip {
    position: fixed; top: -60px; left: 12px; z-index: 100;
    background: var(--accent); color: #fff; padding: 10px 16px; border-radius: var(--r-sm);
    transition: top var(--d-fast) var(--e-standard);
  }
  .skip:focus { top: 12px; }

  .app {
    display: grid;
    grid-template-columns: 248px 1fr;
    grid-template-rows: auto 1fr;
    grid-template-areas: 'side bar' 'side main';
    min-height: 100vh;
  }

  .side {
    grid-area: side;
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
    padding: var(--sp-4) var(--sp-3);
    background: var(--material);
    -webkit-backdrop-filter: var(--material-blur);
    backdrop-filter: var(--material-blur);
    border-right: 1px solid var(--separator);
  }
  .side-brand { padding: var(--sp-2) var(--sp-2) var(--sp-5); }
  .side-nav { display: flex; flex-direction: column; gap: 2px; }
  .nav-link {
    display: flex; align-items: center; gap: var(--sp-3);
    min-height: var(--touch-min); padding: 0 var(--sp-3);
    border-radius: var(--r-sm); color: var(--label-2); font-weight: 600;
    transition: background var(--d-fast) var(--e-standard), color var(--d-fast) var(--e-standard);
  }
  .nav-link .ico { width: 22px; display: inline-flex; justify-content: center; }
  .nav-link:hover { background: var(--fill-2); color: var(--label); }
  .nav-link[aria-current='page'] {
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    color: var(--accent);
  }

  .topbar {
    grid-area: bar;
    position: sticky; top: 0; z-index: 20;
    display: flex; align-items: center; justify-content: space-between; gap: var(--sp-4);
    padding: var(--sp-3) var(--sp-6);
    background: var(--material);
    -webkit-backdrop-filter: var(--material-blur);
    backdrop-filter: var(--material-blur);
    border-bottom: 1px solid var(--separator);
  }

  main {
    grid-area: main;
    width: 100%; max-width: 1440px; margin: 0 auto;
    padding: var(--sp-6);
  }

  .tabs { display: none; }

  @media (max-width: 900px) {
    .app { grid-template-columns: 1fr; grid-template-areas: 'bar' 'main'; }
    .side { display: none; }
    main { padding: var(--sp-4); padding-bottom: 88px; }
    .tabs {
      position: fixed; left: 0; right: 0; bottom: 0; z-index: 30;
      display: flex; justify-content: space-around;
      padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
      background: var(--material);
      -webkit-backdrop-filter: var(--material-blur);
      backdrop-filter: var(--material-blur);
      border-top: 1px solid var(--separator);
    }
    .tab {
      display: flex; flex-direction: column; align-items: center; gap: 3px;
      min-width: 56px; min-height: 48px; justify-content: center;
      color: var(--label-3); font-size: 11px; font-weight: 650;
    }
    .tab[aria-current='page'] { color: var(--accent); }
  }

  .toast-host {
    position: fixed; right: 20px; bottom: 20px; z-index: 200;
    display: flex; flex-direction: column; gap: 10px; align-items: flex-end;
  }
  @media (max-width: 900px) { .toast-host { bottom: 92px; } }
  .toast {
    background: var(--surface-2); color: var(--label);
    border: 1px solid var(--separator); border-left: 3px solid var(--label-3);
    border-radius: var(--r-md); padding: 14px 18px; box-shadow: var(--e-2);
    max-width: 360px; font-size: var(--t-body); font-weight: 600;
  }
  .toast.success { border-left-color: var(--success); }
  .toast.error { border-left-color: var(--danger); }
  .toast.info { border-left-color: var(--accent); }
</style>
