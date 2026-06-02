// Motion system — mirrors the CSS tokens in lib/styles/tokens.css and §7 of
// docs/UPGRADE_PLAN.md. Animate transform/opacity only; everything here has a
// reduced-motion collapse via `d()` and `prefersReducedMotion`.

import { readable, derived, get } from 'svelte/store';
import { reducedMotionOverride } from './stores/prefs';

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

/** Live OS `prefers-reduced-motion` flag. */
export const prefersReducedMotion = readable(false, (set) => {
  if (typeof window === 'undefined' || !window.matchMedia) return;
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
  set(mq.matches);
  const handler = () => set(mq.matches);
  mq.addEventListener('change', handler);
  return () => mq.removeEventListener('change', handler);
});

/**
 * Effective reduced-motion flag: the explicit Settings override wins (true ->
 * reduced), and when it is null we follow the OS. Every animation should
 * consult this so the Settings toggle actually takes effect.
 */
export const reduceMotion = derived(
  [prefersReducedMotion, reducedMotionOverride],
  ([os, override]) => (override === null ? os : override)
);

// Mirror the effective flag onto <html> so the CSS guard in util.css honors the
// Settings override too (the @media query in tokens.css only sees the OS state).
if (typeof document !== 'undefined') {
  reduceMotion.subscribe((on) => {
    document.documentElement.toggleAttribute('data-reduce-motion', on);
  });
}

/** Duration that collapses to ~0 when reduced motion is in effect. */
export function d(ms: number): number {
  return get(reduceMotion) ? 0 : ms;
}

/** Spring config that goes effectively instant under reduced motion. */
export function spring(preset: keyof typeof SPRING) {
  return get(reduceMotion)
    ? { stiffness: 1, damping: 1 }
    : SPRING[preset];
}
