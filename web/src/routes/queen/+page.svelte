<script lang="ts">
  import { api } from '$lib/api';
  import { live } from '$lib/stores/live';
  import { fly } from 'svelte/transition';
  import { d } from '$lib/motion';

  let messages = $state<{ role: 'user' | 'assistant'; content: string }[]>([]);
  let input = $state('');
  let sending = $state(false);
  let online = $derived($live.qwen?.online ?? false);

  async function send() {
    const msg = input.trim();
    if (!msg || sending) return;
    messages = [...messages, { role: 'user', content: msg }];
    input = '';
    sending = true;
    const res = await api.qwenChat(messages);
    sending = false;
    messages = [...messages, { role: 'assistant', content: res?.reply || 'No response.' }];
  }
  function onkey(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  }
</script>

<div class="panel chat">
  <div class="row between top">
    <span class="badge {online ? 'ok' : 'warn'}">
      {online ? `Qwen online · ${$live.qwen?.model || ''}` : 'Qwen offline'}
    </span>
  </div>

  <div class="log" aria-live="polite">
    {#if messages.length === 0}
      <p class="empty">Ask the queen anything about your reels, niches, or pipeline.</p>
    {/if}
    {#each messages as m, i (i)}
      <div class="msg {m.role}" in:fly={{ x: m.role === 'user' ? 24 : -24, duration: d(220) }}>{m.content}</div>
    {/each}
    {#if sending}
      <div class="msg assistant typing" aria-label="Queen is typing"><span></span><span></span><span></span></div>
    {/if}
  </div>

  <div class="row compose">
    <input class="input" bind:value={input} onkeydown={onkey} placeholder="Ask the queen…" aria-label="Message" />
    <button class="btn primary" onclick={send} disabled={sending}>Send</button>
  </div>

  {#if !online}
    <p class="muted hint">Qwen is offline — start Ollama and pull the model to chat live. Other agents fall back to deterministic stubs by design.</p>
  {/if}
</div>

<style>
  .chat { display: flex; flex-direction: column; gap: var(--sp-3); max-width: 820px; }
  .top { min-height: 24px; }
  .log { display: flex; flex-direction: column; gap: 10px; max-height: 56vh; overflow-y: auto; padding: var(--sp-2) 0; }
  .msg { max-width: 78%; padding: 10px 14px; border-radius: var(--r-md); font-size: var(--t-body); line-height: 1.5; }
  .msg.user { align-self: flex-end; background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
  .msg.assistant { align-self: flex-start; background: var(--fill); color: var(--label); border-bottom-left-radius: 4px; }
  .compose { gap: var(--sp-2); }
  .compose .input { flex: 1; }
  .hint { font-size: var(--t-caption); }
  .typing { display: inline-flex; gap: 5px; }
  .typing span { width: 7px; height: 7px; border-radius: 50%; background: var(--label-3); animation: blink 1.2s infinite; }
  .typing span:nth-child(2) { animation-delay: .2s; }
  .typing span:nth-child(3) { animation-delay: .4s; }
  @keyframes blink { 0%, 80%, 100% { opacity: .25; } 40% { opacity: 1; } }
</style>
