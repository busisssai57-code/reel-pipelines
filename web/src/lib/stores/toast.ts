import { writable } from 'svelte/store';

export type ToastKind = 'info' | 'success' | 'error';
export interface Toast {
  id: number;
  msg: string;
  kind: ToastKind;
}

export const toasts = writable<Toast[]>([]);
let seq = 0;

export function toast(msg: string, kind: ToastKind = 'info', ttl = 3200): void {
  const t: Toast = { id: ++seq, msg, kind };
  toasts.update((a) => [...a, t]);
  setTimeout(() => toasts.update((a) => a.filter((x) => x.id !== t.id)), ttl);
}
