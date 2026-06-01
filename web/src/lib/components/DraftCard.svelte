<script lang="ts">
  import type { Draft } from '$lib/types';
  import { apiBase } from '$lib/api';
  import { categoryClass, titleCase } from '$lib/util';
  import Icon from './Icon.svelte';

  let {
    draft,
    onapprove,
    onreject
  }: {
    draft: Draft;
    onapprove?: (id: string) => void;
    onreject?: (id: string) => void;
  } = $props();

  let poster = $derived(draft.thumb_url ? apiBase + draft.thumb_url : '');
  let cat = $derived(categoryClass(draft.category || draft.cat));
  let pending = $derived((draft.status || 'pending') === 'pending');
</script>

<article class="draft">
  <div class="poster" style={poster ? `background-image:url('${poster}')` : ''} class:placeholder={!poster}>
    {#if !poster}<Icon name="render" size={30} />{/if}
    <span class="tag {cat}">{cat}</span>
    <span class="pl">{draft.pl || draft.pipeline}</span>
  </div>
  <div class="body">
    <h3 title={draft.title}>{draft.title}</h3>
    <div class="sub muted">{draft.voice || 'voice —'}</div>
    {#if draft.script}<p class="script">{draft.script}</p>{/if}

    {#if pending}
      <div class="actions">
        <button class="btn ok sm" onclick={() => onapprove?.(draft.id)}>
          <Icon name="check" size={15} /> Approve
        </button>
        <button class="btn danger sm" onclick={() => onreject?.(draft.id)}>
          <Icon name="close" size={15} /> Reject
        </button>
      </div>
    {:else}
      <div class="state {draft.status}">{titleCase(draft.status)}{#if draft.slot} · {draft.slot.slice(0, 16).replace('T', ' ')}{/if}</div>
    {/if}
  </div>
</article>

<style>
  .draft {
    background: var(--surface); border: 1px solid var(--separator);
    border-radius: var(--r-md); overflow: hidden; box-shadow: var(--e-1);
    display: flex; flex-direction: column;
    transition: transform var(--d-base) var(--e-emphasized), box-shadow var(--d-base) var(--e-emphasized);
  }
  .draft:hover { transform: translateY(-3px); box-shadow: var(--e-2); }
  .poster {
    aspect-ratio: 9 / 16; background-size: cover; background-position: center;
    position: relative; display: flex; align-items: center; justify-content: center;
    color: var(--label-3);
  }
  .poster.placeholder {
    background:
      repeating-linear-gradient(45deg, var(--surface-2), var(--surface-2) 12px, var(--surface) 12px, var(--surface) 24px);
  }
  .tag { position: absolute; top: 8px; left: 8px; }
  .pl {
    position: absolute; top: 8px; right: 8px;
    font-size: 11px; font-weight: 800; color: #fff;
    background: rgba(0, 0, 0, .42); border-radius: var(--r-pill); padding: 3px 8px;
  }
  .body { padding: var(--sp-3) var(--sp-4) var(--sp-4); display: flex; flex-direction: column; gap: 6px; flex: 1; }
  h3 { font-size: var(--t-body); font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { font-size: var(--t-caption); }
  .script {
    margin: 0; font-size: var(--t-caption); color: var(--label-2);
    display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }
  .actions { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-2); margin-top: auto; }
  .state { margin-top: auto; text-align: center; font-size: var(--t-caption); font-weight: 700; padding: 8px; border-radius: var(--r-sm); background: var(--fill-2); color: var(--label-2); }
  .state.approved { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
  .state.rejected { background: color-mix(in srgb, var(--danger) 14%, transparent); color: var(--danger); }
  .state.published { background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--accent); }
</style>
