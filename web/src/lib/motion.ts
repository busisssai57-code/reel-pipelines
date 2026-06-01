// Motion system — mirrors the CSS tokens in lib/styles/tokens.css and §7 of
// docs/UPGRADE_PLAN.md. Animate transform/opacity only; everything here has a
// reduced-motion collapse via `d()` and `prefersReducedMotion`.

import { readable, get } from 'svelte/store';

export const EASING = {
  standard: 'cubic-bezier(.4,0,.2,1)',
  decelerate: 'cubic-bezier(0,0,.2,1)',
  accelerate: 'cubic-bezier(.4,0,1,1)',
  emphasized: 'cubic-bezier(.2,0,0,1)'
} as const;

export const DURATION = {
  micro: 120,
  fast: 200,
  base: 320,
  slow: 420,
  hero: 520
} as const;

/** svelte/motion spring presets. */
export const SPRING = {
  snappy: { stiffness: 0.2, damping: 0.9 },
  smooth: { stiffness: 0.12, damping: 0.85 },
  bouncy: { stiffness: 0.16, damping: 0.6 }
} as const;

/** Live `prefers-reduced-motion` flag. */
export const prefersReducedMotion = readable(false, (set) => {
  if (typeof window === 'undefined' || !window.matchMedia) return;
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
  set(mq.matches);
  const handler = () => set(mq.matches);
  mq.addEventListener('change', handler);
  return () => mq.removeEventListener('change', handler);
});

/** Duration that collapses to ~0 when the user prefers reduced motion. */
export function d(ms: number): number {
  return get(prefersReducedMotion) ? 0 : ms;
}

/** Spring config that goes effectively instant under reduced motion. */
export function spring(preset: keyof typeof SPRING) {
  return get(prefersReducedMotion)
    ? { stiffness: 1, damping: 1 }
    : SPRING[preset];
}
