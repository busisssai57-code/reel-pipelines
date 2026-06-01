<script lang="ts">
  import { theme, reducedMotionOverride, type Theme } from '$lib/stores/prefs';
  import { apiBase } from '$lib/api';
  import { toast } from '$lib/stores/toast';

  const themes: { v: Theme; label: string }[] = [
    { v: 'auto', label: 'Auto' },
    { v: 'light', label: 'Light' },
    { v: 'dark', label: 'Dark' }
  ];

  let base = $state('');
  try { base = localStorage.getItem('reel.apiBase') || ''; } catch { /* ignore */ }

  function saveBase() {
    try {
      if (base.trim()) localStorage.setItem('reel.apiBase', base.trim());
      else localStorage.removeItem('reel.apiBase');
      toast('Saved — reload to apply the new API base', 'success');
    } catch { toast('Could not save', 'error'); }
  }
</script>

<div class="grid cards settings">
  <section class="panel">
    <h2 class="section-title">Appearance</h2>
    <div class="field">
      <span class="lbl">Theme</span>
      <div class="seg" role="radiogroup" aria-label="Theme">
        {#each themes as t}
          <button role="radio" aria-checked={$theme === t.v} onclick={() => theme.set(t.v)}>{t.label}</button>
        {/each}
      </div>
    </div>
    <label class="check">
      <input type="checkbox" checked={$reducedMotionOverride === true}
        onchange={(e) => reducedMotionOverride.set((e.currentTarget as HTMLInputElement).checked ? true : null)} />
      Reduce motion (override OS setting)
    </label>
  </section>

  <section class="panel">
    <h2 class="section-title">Connection</h2>
    <p class="muted small">Current API base: <code>{apiBase}</code></p>
    <label class="field">
      <span class="lbl">Override API base (for a tunnel / remote backend)</span>
      <input class="input" bind:value={base} placeholder="https://your-tunnel.trycloudflare.com" />
    </label>
    <button class="btn primary" onclick={saveBase}>Save</button>
    <p class="muted small">Leave blank to use the default local backend (<code>http://127.0.0.1:8787</code>). Also overridable per-visit with <code>?api=</code>.</p>
  </section>

  <section class="panel">
    <h2 class="section-title">About</h2>
    <p class="muted">Reel Studio — Apple-inspired, motion-first dashboard. Phase 0 build (SvelteKit, static). Roadmap and specs in <code>docs/UPGRADE_PLAN.md</code>.</p>
  </section>
</div>

<style>
  .settings { align-items: start; }
  .field { display: flex; flex-direction: column; gap: 8px; margin: var(--sp-3) 0; }
  .lbl { font-size: var(--t-caption); color: var(--label-2); font-weight: 700; }
  .small { font-size: var(--t-caption); }
  .seg { display: inline-flex; background: var(--surface-2); border: 1px solid var(--separator); border-radius: var(--r-sm); overflow: hidden; width: fit-content; }
  .seg button { min-height: 38px; padding: 0 var(--sp-4); border: 0; background: transparent; color: var(--label-2); font-weight: 700; }
  .seg button[aria-checked='true'] { background: var(--accent); color: #fff; }
  .check { display: flex; align-items: center; gap: 10px; font-weight: 600; margin-top: var(--sp-2); }
  code { font-family: var(--font-mono); font-size: .88em; background: var(--fill-2); padding: 1px 6px; border-radius: 6px; }
</style>
