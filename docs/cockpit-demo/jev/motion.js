// SPDX-License-Identifier: MIT
// Motion of the Jev page. The springs, the clock and the reduced-motion query come from the
// dashboard's own scripts/web/motion.js, so the Jev tab moves exactly like the rest of the page;
// here are only the few film formulas the dashboard does not need (skills/explainer-video/assets/
// motion.js: seeded noise, windows, ripples, typed text, counters) and `track`, a value that
// follows its target. No DOM here except the reduced-motion query in ../motion.js; the node test
// imports this file.

import { clamp, flash, nowSec, o3, ramp, reducedMotion, settled, spring, springTo, flowAlpha } from '../motion.js'

export { clamp, flash, nowSec, o3, ramp, reducedMotion, settled, spring, springTo, flowAlpha }

/* Window: fades in from a over f and out from b over f */
export const win = (t, a, b, f = 0.35) => ramp(t, a, f) * (1 - ramp(t, b, f))

/* Zufall mit Saat (mulberry32): gleiche Saat, gleiche Folge. Nie Math.random, sonst ist T kein Zustand mehr */
export function rng(seed = 1) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6D2B79F5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/* glattes Rauschen in einer Dimension, aus Werten mit Saat: Drift ohne Zustand */
export function noise1(x, seed = 1) {
  const h = i => { const r = rng(seed * 7919 + i * 104729); r(); return r() * 2 - 1 }
  const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f)
  return h(i) * (1 - u) + h(i + 1) * u
}

/* Rings, one per hit: each grows and fades on its own. Result per hit { alpha, scale } */
export const ripples = (T, hits, { grow = 1.6, life = 0.9 } = {}) => hits.map(h => {
  const d = T - h
  return d < 0 ? { alpha: 0, scale: 1 } : { alpha: Math.min(1, d / 0.08) * Math.exp(-3 * d), scale: 1 + grow * o3(clamp(0, 1, d / life)) }
})

/* Text, der schnell beginnt und zum Ende langsamer wird; der Cursor steht beim Tippen und blinkt danach dreimal */
export const typed = (T, text, t0, d) => text.slice(0, Math.round(text.length * o3(ramp(T, t0, d))))
export const cursorOn = (T, t0, d) => T < t0 + d + 0.3 || (T < t0 + d + 2 && Math.floor((T - t0 - d - 0.3) * 1.8) % 2 === 0)

/* Zahl, die steigt und langsamer ankommt; im CSS tabular-nums und eine feste Mindestbreite */
export const countTo = (T, to, t0, d, from = 0) => from + (to - from) * o3(ramp(T, t0, d))

/** A value that follows its target with the dashboard spring, like useTween in components.js but
 *  outside a hook, for frame functions that keep one per element. `st` is the last state (or null),
 *  the result is the next one; a new target in mid move bends the path. Read it with trackAt */
export function track(st, to, now, still = false) {
  if (!st || still) return { from: to, to, moves: [] }
  if (to === st.to) return st
  return { from: st.from, to, moves: [...st.moves, [now, to]] }
}

/** The value of a tracked state at time now; a settled state collapses to its target */
export function trackAt(st, now, o = { w: 12, zeta: 0.95 }) {
  if (!st) return 0
  if (!st.moves.length) return st.to
  if (settled(now, st.moves, o)) { st.from = st.to; st.moves = []; return st.to }
  return springTo(now, st.from, st.moves, o)
}

/** True while a tracked state still moves */
export const tracking = st => !!st && st.moves.length > 0
