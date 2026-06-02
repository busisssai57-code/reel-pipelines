// Persisted user preferences (theme, reduced-motion override). Client-only.
import { writable, type Writable } from 'svelte/store';

function persisted<T>(key: string, initial: T): Writable<T> {
  let start = initial;
  try {
    const raw = localStorage.getItem(key);
    if (raw !== null) start = JSON.parse(raw) as T;
  } catch { /* ignore */ }

  const store = writable<T>(start);
  store.subscribe((v) => {
    try {
      localStorage.setItem(key, JSON.stringify(v));
    } catch { /* ignore */ }
  });
  return store;
}

export type Theme = 'aurum' | 'auto' | 'light' | 'dark';

// Theme is stored as a bare string (the no-flash script in app.html reads it
// directly), so use a small bespoke store rather than JSON.
function themeStore(): Writable<Theme> {
  let start: Theme = 'aurum';
  try {
    const raw = localStorage.getItem('reel.theme') as Theme | null;
    if (raw === 'aurum' || raw === 'auto' || raw === 'light' || raw === 'dark') start = raw;
  } catch { /* ignore */ }

  const store = writable<Theme>(start);
  store.subscribe((v) => {
    try {
      localStorage.setItem('reel.theme', v);
      const resolved =
        v === 'aurum' ? 'aurum'
        : v === 'dark' || (v === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark'
        : 'light';
      document.documentElement.dataset.theme = resolved;
    } catch { /* ignore */ }
  });
  return store;
}

export const theme = themeStore();

// Optional explicit reduced-motion override (Settings). null = follow OS.
export const reducedMotionOverride = persisted<boolean | null>('reel.reducedMotion', null);
