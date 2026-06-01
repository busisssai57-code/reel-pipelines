<script lang="ts">
  import { onDestroy } from 'svelte';
  import { tweened } from 'svelte/motion';
  import { cubicOut } from 'svelte/easing';
  import { api } from '$lib/api';
  import type { BusEvent } from '$lib/types';
  import { d } from '$lib/motion';
  import { toast } from '$lib/stores/toast';
  import EventFeed from '$lib/components/EventFeed.svelte';
  import Icon from '$lib/components/Icon.svelte';

  let topic = $state('');
  let source = $state('auto');
  let jobId = $state<string | null>(null);
  let status = $state<'idle' | 'starting' | 'running' | 'done' | 'failed'>('idle');
  let evs = $state<BusEvent[]>([]);
  let timer: ReturnType<typeof setInterval> | null = null;

  const pct = tweened(0, { duration: d(500), easing: cubicOut });

  // Heuristic stage mapping over the real event stream. P1 replaces this with
  // explicit `render_stage` SSE events for exact progress (see UPGRADE_PLAN §9.2).
  const STAGES = [
    { key: 'script', label: 'Script', icon: 'review', kw: ['script'] },
    { key: 'tts', label: 'Voice', icon: 'queen', kw: ['tts', 'voice', 'kokoro', 'audio'] },
    { key: 'visuals', label: 'Visuals', icon: 'render', kw: ['visual', 'image', 'video', 'hunyuan', 'footage', 'broll'] },
    { key: 'subtitles', label: 'Subtitles', icon: 'factcheck', kw: ['subtitle', 'caption', 'sub'] },
    { key: 'music', label: 'Music', icon: 'bolt', kw: ['music'] },
    { key: 'export', label: 'Export', icon: 'drafts', kw: ['export', 'ffmpeg', 'encode', 'assemble', 'concat', 'mux'] }
  ];
  const matches = (e: BusEvent, kw: string[]) => {
    const hay = `${e.agent} ${e.type} ${e.note}`.toLowerCase();
    return kw.some((k) => hay.includes(k));
  };
  const isOk = (e: BusEvent) => /ok|done|scored|pass|ready|complete/.test((e.type || '').toLowerCase());

  let stageState = $derived.by(() => {
    const m: Record<string, 'waiting' | 'running' | 'done'> = {};
    for (const s of STAGES) {
      const hit = evs.filter((e) => matches(e, s.kw));
      m[s.key] = hit.some(isOk) ? 'done' : hit.length ? 'running' : 'waiting';
    }
    if (status === 'done') for (const s of STAGES) m[s.key] = 'done';
    return m;
  });
  let doneCount = $derived(Object.values(stageState).filter((v) => v === 'done').length);

  $effect(() => {
    if (status === 'done') pct.set(100);
    else if (status === 'idle' || status === 'starting') pct.set(status === 'idle' ? 0 : 6);
    else pct.set(Math.min(96, Math.round((doneCount / STAGES.length) * 100)));
  });

  function stop() { if (timer) clearInterval(timer); timer = null; }
  onDestroy(stop);

  async function start() {
    if (!topic.trim()) { toast('Please enter a topic', 'error'); return; }
    status = 'starting';
    const r = await api.startRender(topic.trim(), source);
    if (r?.job_id) {
      jobId = r.job_id; status = 'running'; evs = [];
      toast(`Producing: ${topic.trim()}`, 'success');
      stop();
      timer = setInterval(poll, 600);
    } else {
      status = 'idle';
      toast('Failed to start render — is the backend running?', 'error');
    }
  }
  async function poll() {
    if (!jobId) return;
    const res = await api.renderEvents(jobId);
    evs = res.events || [];
    const st = (res.job?.status as typeof status) || 'running';
    if (st === 'done' || st === 'failed') {
      status = st; stop();
      toast(st === 'done' ? 'Render complete' : 'Render failed', st === 'done' ? 'success' : 'error');
    }
  }

  const R = 86;
  const C = 2 * Math.PI * R;
  let dashoffset = $derived(C - ($pct / 100) * C);
  let busy = $derived(status === 'starting' || status === 'running');
</script>

<div class="studio">
  <div class="form panel">
    <h2 class="section-title">Start Production</h2>
    <label class="field">
      <span>Topic</span>
      <input class="input" bind:value={topic} placeholder="Why the ocean is salty" />
    </label>
    <label class="field">
      <span>Visual source</span>
      <select class="input" bind:value={source}>
        <option value="auto">Auto (AI generation)</option>
        <option value="stock">Stock footage</option>
        <option value="hybrid">Hybrid mix</option>
      </select>
    </label>
    <button class="btn primary trigger" onclick={start} disabled={busy}>
      <Icon name="render" size={18} fill /> {busy ? 'Producing…' : 'Start Render'}
    </button>

    <div class="stages">
      {#each STAGES as s (s.key)}
        <div class="stage {stageState[s.key]}">
          <span class="si"><Icon name={stageState[s.key] === 'done' ? 'check' : s.icon} size={18} /></span>
          <span class="sn">{s.label}</span>
          <span class="ss">{stageState[s.key]}</span>
        </div>
      {/each}
    </div>
  </div>

  <div class="col">
    <div class="ring-panel panel">
      {#if status === 'idle'}
        <div class="idle"><Icon name="render" size={46} /><p class="muted">Ready to produce video</p></div>
      {:else}
        <div class="ring-wrap">
          <svg class="ring" viewBox="0 0 200 200" role="progressbar"
            aria-valuenow={Math.round($pct)} aria-valuemin="0" aria-valuemax="100" aria-label="Render progress">
            <circle class="track" cx="100" cy="100" r={R} />
            <circle class="bar" class:done={status === 'done'} class:failed={status === 'failed'}
              cx="100" cy="100" r={R} stroke-dasharray={C} stroke-dashoffset={dashoffset} />
          </svg>
          <div class="ring-text">
            <div class="pct tnum">{Math.round($pct)}%</div>
            <div class="muted lbl">{status === 'done' ? 'Complete' : status === 'failed' ? 'Failed' : 'Rendering…'}</div>
          </div>
        </div>
      {/if}
    </div>
    <div class="panel">
      <h2 class="section-title">Timeline</h2>
      <EventFeed events={evs} limit={40} />
    </div>
  </div>
</div>

<style>
  .studio { display: grid; grid-template-columns: minmax(260px, 360px) 1fr; gap: var(--sp-5); align-items: start; }
  @media (max-width: 860px) { .studio { grid-template-columns: 1fr; } }

  .field { display: flex; flex-direction: column; gap: 6px; margin-bottom: var(--sp-3); }
  .field span { font-size: var(--t-caption); color: var(--label-2); font-weight: 700; }

  .trigger {
    width: 100%; min-height: 60px; font-size: var(--t-callout); margin-top: var(--sp-2);
    color: #fff; border: 0; border-radius: var(--r-md);
    background: linear-gradient(135deg, var(--accent), #2ad0c0);
    box-shadow: 0 10px 30px color-mix(in srgb, var(--accent) 35%, transparent);
  }
  .trigger[disabled] { filter: grayscale(.3); opacity: .8; }

  .stages { display: grid; gap: var(--sp-2); margin-top: var(--sp-5); }
  .stage {
    display: grid; grid-template-columns: 30px 1fr auto; align-items: center; gap: var(--sp-3);
    padding: 10px 12px; border-radius: var(--r-sm);
    border: 1px solid var(--separator); background: var(--surface-2);
    transition: border-color var(--d-base) var(--e-standard), background var(--d-base) var(--e-standard);
  }
  .stage .si { color: var(--label-3); display: inline-flex; }
  .stage .sn { font-weight: 650; }
  .stage .ss { font-size: var(--t-caption); color: var(--label-3); text-transform: capitalize; }
  .stage.running { border-color: color-mix(in srgb, var(--accent) 55%, var(--separator)); background: color-mix(in srgb, var(--accent) 9%, var(--surface-2)); }
  .stage.running .si { color: var(--accent); animation: pulse 1.6s ease-in-out infinite; }
  .stage.done .si { color: var(--success); }
  .stage.done .ss { color: var(--success); }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }

  .ring-panel { display: grid; place-items: center; min-height: 280px; padding: var(--sp-6); }
  .idle { display: grid; place-items: center; gap: var(--sp-3); color: var(--label-3); }
  .ring-wrap { position: relative; width: 200px; height: 200px; }
  .ring { width: 200px; height: 200px; transform: rotate(-90deg); }
  .ring .track { fill: none; stroke: var(--separator); stroke-width: 8; }
  .ring .bar {
    fill: none; stroke: var(--accent); stroke-width: 8; stroke-linecap: round;
    transition: stroke-dashoffset var(--d-slow) var(--e-standard), stroke var(--d-base) var(--e-standard);
  }
  .ring .bar.done { stroke: var(--success); }
  .ring .bar.failed { stroke: var(--danger); }
  .ring-text { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; }
  .pct { font-size: 40px; font-weight: 750; letter-spacing: -.03em; }
  .lbl { font-size: var(--t-caption); }
</style>
