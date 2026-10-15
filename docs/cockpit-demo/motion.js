// SPDX-License-Identifier: MIT
// Motion of the dashboard, taken from the explainer films (skills/explainer-video/assets/motion.js):
// the same closed formulas, so a value is a pure function of the time since its change and never
// jumps. Damped springs instead of a fixed curve, a retarget bends instead of restarting, a hit rises
// in 80 ms and decays. Only transform and opacity move (DESIGN.md, Motion); under
// prefers-reduced-motion every value stands at its target at once and nothing moves on its own.
// No DOM here except the reduced-motion query; the frontend test imports this file under node.

export const clamp = (a, b, x) => Math.min(b, Math.max(a, x))
export const ramp = (t, t0, d) => clamp(0, 1, (t - t0) / d)
export const o3 = x => 1 - Math.pow(1 - x, 3)

/** Damped spring as a closed step response: 0 before t0, runs to 1. zeta 0.95 to 1 does not overshoot */
export function spring(T, t0, { w = 14, zeta = 0.95 } = {}) {
  const t = T - t0
  if (t <= 0) return 0
  if (zeta >= 1) return 1 - (1 + w * t) * Math.exp(-w * t)
  const wd = w * Math.sqrt(1 - zeta * zeta)
  return 1 - Math.exp(-zeta * w * t) * (Math.cos(wd * t) + zeta * w / wd * Math.sin(wd * t))
}

/** A value with several targets one after another, moves = [[t, to], ...]: one spring per change,
 *  summed. A new target in the middle of a move bends the path, it never starts over */
export function springTo(T, from, moves, o) {
  return moves.reduce((v, [t, to], i) => v + (to - (i ? moves[i - 1][1] : from)) * spring(T, t, o), from)
}

/** True once every spring of the moves has arrived (within eps of the step) */
export function settled(T, moves, o, eps = 0.002) {
  return moves.every(([t]) => 1 - spring(T, t, o) < eps)
}

/** Hit envelope: rises in 80 ms, then decays; with several hits the strongest counts */
export function flash(T, hits, decay = 3) {
  return Math.max(0, ...hits.filter(h => h <= T).map(h => {
    const d = T - h
    return Math.min(1, d / 0.08) * Math.exp(-Math.max(0, d - 0.08) * decay)
  }))
}

/** A light point on a rail drawn up to uDraw: visible only behind the drawing edge, fading at both ends */
export function flowAlpha(u, uDraw = 1) {
  return clamp(0, 1, (uDraw - u) / 0.06) * Math.min(1, u / 0.1, (1 - u) / 0.1)
}

/** Positions 0..1 of n points running along a rail with period p seconds, evenly spaced */
export function flowPoints(T, n, p = 1.6) {
  return Array.from({ length: n }, (_, i) => ((T / p + i / n) % 1 + 1) % 1)
}

export function reducedMotion() {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Seconds on the page clock, the time base of every formula above */
export const nowSec = () => (typeof performance === 'object' ? performance.now() : Date.now()) / 1000
