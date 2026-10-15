// SPDX-License-Identifier: MIT
// The inner room: behind the core of the start page, the Bridge's knowledge graph as a net in 3D.
//
// The config entries, tasks and the files they name are neurons, the references between them synapses
// (scripts/lib/bridge_cockpit/graph.py). Signals run along the synapses; a click flies to a node and lights
// what it is wired to; the journey wanders from node to node on its own. Drawn on one canvas, no library:
// the layout and the projection are in logic.js.
import { html, useEffect, useRef, useState } from './vendor/htm-preact-3.1.1.module.js'
import { GRAPH_GROUPS, graphFind, graphLive, nextHop, projectPoint, seedGraph, stepGraph } from './logic.js'
import { reducedMotion } from './motion.js'
import { T } from './text.js'

const HOP_MS = 3800
const SETTLE_STEPS = 420

/** A soft round glow in one color, drawn once and stamped for every node */
function sprite(color) {
  const c = document.createElement('canvas')
  c.width = c.height = 64
  const x = c.getContext('2d')
  const g = x.createRadialGradient(32, 32, 0, 32, 32, 32)
  g.addColorStop(0, `${color}ff`)
  g.addColorStop(0.18, `${color}ee`)
  g.addColorStop(0.42, `${color}55`)
  g.addColorStop(1, `${color}00`)
  x.fillStyle = g
  x.fillRect(0, 0, 64, 64)
  return c
}

function colorsOf(el) {
  const css = getComputedStyle(el)
  const v = name => css.getPropertyValue(name).trim() || '#888888'
  const group = Object.fromEntries(GRAPH_GROUPS.map(g => [g, v(`--void-${g}`)]))
  const live = { working: v('--void-live-working'), asks: v('--void-live-asks'), answer: v('--void-live-answer'),
    lost: v('--void-live-alarm'), alarm: v('--void-live-alarm'), warn: v('--void-live-asks') }
  return { group, live, bg: v('--void'), raised: v('--void-raised'), line: v('--void-line'), text: v('--void-text'),
    muted: v('--void-muted'), faint: v('--void-faint'), font: css.getPropertyValue('--font-ui').trim() || 'sans-serif',
    sprites: Object.fromEntries(Object.entries(group).map(([k, c]) => [k, sprite(c)])), spark: sprite(v('--void-core')) }
}

const isWork = n => n && (n.family === 'tasks' || n.family === 'streams') && n.id.endsWith('/STATUS.md')

export function InnerRoom({ s, c, focus, onClose, onTab }) {
  const t = T().inner
  const room = useRef(null)
  const canvas = useRef(null)
  const searchBox = useRef(null)
  const w = useRef(null)
  const [state, setState] = useState('loading')
  const [sel, setSel] = useState(null)
  const [detail, setDetail] = useState(null)
  const [tour, setTour] = useState(false)
  const [query, setQuery] = useState('')
  const [hidden, setHidden] = useState(() => new Set())
  const [hover, setHover] = useState(null)
  const [liveN, setLiveN] = useState(0)
  const still = reducedMotion()

  const select = i => {
    const W = w.current
    if (!W) return
    if (i === null || i === undefined) {
      W.sel = null
      W.goal.dist = 640
      W.goal.target = [0, 0, 0]
      setSel(null)
      setDetail(null)
      return
    }
    if (W.sel !== null && W.sel !== i) W.signals.push({ a: W.sel, b: i, u: 0, speed: 0.022, you: true })
    W.sel = i
    W.visited.add(i)
    if (W.visited.size >= W.g.nodes.length) W.visited = new Set([i])
    W.goal.dist = 200
    setSel(i)
    setDetail(null)
    const id = W.g.nodes[i].id
    c.graphNode(id).then(res => { if (w.current?.sel === i) setDetail(res.ok ? res.data : { error: true }) })
  }

  // the graph, once
  useEffect(() => {
    let alive = true
    c.graph().then(res => {
      if (!alive) return
      if (!res.ok || !res.data?.nodes?.length) { setState('error'); return }
      const g = seedGraph(res.data.nodes, res.data.edges)
      if (still) for (let k = 0; k < SETTLE_STEPS; k++) stepGraph(g)
      w.current = {
        g, steps: still ? SETTLE_STEPS : 0, sel: null, hover: null, visited: new Set(), signals: [], proj: [],
        cam: { yaw: 0.6, pitch: -0.3, dist: still ? 640 : 1900, target: [0, 0, 0], fov: 1 },
        goal: { dist: 640, target: [0, 0, 0] }, drag: null, lastHop: 0, hidden: new Set(), live: new Map(),
        // far dust on a large sphere around the camera's target: it gives the flight its depth
        stars: Array.from({ length: 220 }, (_, k) => {
          const y = 1 - (k + 0.5) / 220 * 2, r = Math.sqrt(1 - y * y), a = k * 2.399963
          return [Math.cos(a) * r * 1500, y * 1500, Math.sin(a) * r * 1500]
        }),
      }
      setState('ok')
    })
    return () => { alive = false }
  }, [])

  useEffect(() => { if (w.current) w.current.hidden = hidden }, [hidden, state])

  // what is alive right now: tabs at work or waiting, answers, quiet starts, workers with findings (logic.js graphLive)
  useEffect(() => { if (!s?.workers?.data && c.loadWorkers) c.loadWorkers() }, [])
  useEffect(() => {
    if (state !== 'ok') return
    const live = graphLive(w.current.g, s?.tabs?.tabs, s?.model?.returns, s?.workers?.data?.runs)
    w.current.live = live
    setLiveN(live.size)
  }, [state, s?.tabs, s?.model?.returns, s?.workers?.data])

  // opened for one thing (a task from its drawer): fly there once the net stands
  useEffect(() => {
    if (state !== 'ok' || !focus) return
    const g = w.current.g
    const slug = focus.startsWith('task:') ? focus.slice(5) : null
    const i = slug ? g.index.get(`work/tasks/${slug}/STATUS.md`) ?? g.index.get(`work/streams/${slug}/STATUS.md`) : g.index.get(focus)
    if (i !== undefined) select(i)
  }, [state, focus])

  // the frame loop: settle the net a little more, move the camera, fire signals, draw
  useEffect(() => {
    if (state !== 'ok') return undefined
    const cv = canvas.current
    const ctx = cv.getContext('2d')
    const col = colorsOf(room.current)
    let raf = 0
    const frame = now => {
      raf = requestAnimationFrame(frame)
      const W = w.current
      const { g, cam, goal } = W
      const dpr = window.devicePixelRatio || 1
      const cw = cv.clientWidth, ch = cv.clientHeight
      if (cv.width !== Math.round(cw * dpr) || cv.height !== Math.round(ch * dpr)) {
        cv.width = Math.round(cw * dpr)
        cv.height = Math.round(ch * dpr)
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      if (W.steps < SETTLE_STEPS) { stepGraph(g); stepGraph(g); W.steps += 2 }
      const P = g.pos
      if (W.sel !== null) goal.target = [P[W.sel * 3], P[W.sel * 3 + 1], P[W.sel * 3 + 2]]
      const ease = still ? 1 : 0.06
      for (let k = 0; k < 3; k++) cam.target[k] += (goal.target[k] - cam.target[k]) * ease
      cam.dist += (goal.dist - cam.dist) * (still ? 1 : 0.045)
      if (!still && !W.drag) cam.yaw += W.sel === null ? 0.0012 : 0.0005

      // the journey: on to the next node every few seconds
      if (W.tour && now - W.lastHop > HOP_MS) {
        W.lastHop = now
        const start = W.sel ?? g.adj.reduce((best, a, i) => (a.length > g.adj[best].length ? i : best), 0)
        select(W.sel === null ? start : nextHop(g, W.sel, W.visited))
      }
      // signals: now and then a synapse fires; the chosen node fires along all of its own
      if (!still) {
        if (g.links.length && Math.random() < 0.35) {
          const [a, b] = g.links[Math.floor(Math.random() * g.links.length)]
          W.signals.push(Math.random() < 0.5 ? { a, b, u: 0, speed: 0.008 + Math.random() * 0.01 } : { a: b, b: a, u: 0, speed: 0.008 + Math.random() * 0.01 })
        }
        if (W.sel !== null && Math.random() < 0.12) {
          for (const j of g.adj[W.sel]) W.signals.push({ a: W.sel, b: j, u: 0, speed: 0.015 + Math.random() * 0.01, lit: true })
        }
        if (W.signals.length > 400) W.signals.splice(0, W.signals.length - 400)
      }

      // draw: the deep, the far dust, the synapses, the neurons far to near, the signals, the names
      const bg = ctx.createRadialGradient(cw / 2, ch / 2, 0, cw / 2, ch / 2, Math.max(cw, ch) * 0.7)
      bg.addColorStop(0, col.raised)
      bg.addColorStop(1, col.bg)
      ctx.fillStyle = bg
      ctx.fillRect(0, 0, cw, ch)
      ctx.fillStyle = col.faint
      for (const [x, y, z] of W.stars) {
        const p = projectPoint(x + cam.target[0], y + cam.target[1], z + cam.target[2], cam, cw, ch)
        if (p.scale <= 0) continue
        ctx.globalAlpha = Math.min(0.7, 900 / p.depth * 0.35)
        ctx.fillRect(p.x, p.y, 1.2, 1.2)
      }
      const n = g.nodes.length
      const proj = W.proj
      const hide = W.hidden
      const near = W.sel === null ? null : new Set([W.sel, ...g.adj[W.sel]])
      for (let i = 0; i < n; i++) proj[i] = projectPoint(P[i * 3], P[i * 3 + 1], P[i * 3 + 2], cam, cw, ch)
      const shown = i => !hide.has(g.nodes[i].group) && proj[i].scale > 0
      const fog = d => Math.max(0.08, Math.min(1, 1.35 - d / 1500))
      ctx.lineWidth = 1
      for (const [a, b] of g.links) {
        if (!shown(a) || !shown(b)) continue
        const lit = near && (a === W.sel || b === W.sel)
        ctx.globalAlpha = (lit ? 0.75 : near ? 0.05 : 0.16) * fog((proj[a].depth + proj[b].depth) / 2)
        ctx.strokeStyle = lit ? col.group[g.nodes[a === W.sel ? b : a].group] : col.line
        ctx.lineWidth = lit ? 1.4 : 1
        ctx.beginPath()
        ctx.moveTo(proj[a].x, proj[a].y)
        ctx.lineTo(proj[b].x, proj[b].y)
        ctx.stroke()
      }
      const order = []
      for (let i = 0; i < n; i++) if (shown(i)) order.push(i)
      order.sort((a, b) => proj[b].depth - proj[a].depth)
      for (const i of order) {
        const p = proj[i], node = g.nodes[i]
        const base = (5 + Math.sqrt(node.degree || 0) * 2.4) * (node.leaf ? 0.7 : 1)
        // a node right before the camera stays a node, not a blur over the whole room
        const size = Math.min(48, Math.max(2, base * p.scale * 2.2)) * (i === W.sel ? 1.8 : i === W.hover ? 1.4 : 1)
        ctx.globalAlpha = fog(p.depth) * (near && !near.has(i) ? 0.22 : 1)
        ctx.drawImage(col.sprites[node.group] ?? col.sprites.other, p.x - size, p.y - size, size * 2, size * 2)
      }
      // the living ones carry a ring that breathes in their state's tone
      for (const [i, v] of W.live) {
        if (!shown(i)) continue
        const p = proj[i], node = g.nodes[i]
        const r = Math.min(48, Math.max(3, (5 + Math.sqrt(node.degree || 0) * 2.4) * p.scale * 2.2)) * 0.62
        const beat = still ? 0.5 : 0.5 + 0.5 * Math.sin(now / (v.tone === 'asks' || v.tone === 'alarm' ? 220 : 520) + i)
        ctx.globalAlpha = (0.45 + 0.5 * beat) * fog(p.depth)
        ctx.strokeStyle = col.live[v.tone]
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.arc(p.x, p.y, r * (1.1 + 0.35 * beat), 0, Math.PI * 2)
        ctx.stroke()
      }
      for (let k = W.signals.length - 1; k >= 0; k--) {
        const sg = W.signals[k]
        sg.u += sg.speed
        if (sg.u >= 1) { W.signals.splice(k, 1); continue }
        if (!shown(sg.a) || !shown(sg.b)) continue
        const pa = proj[sg.a], pb = proj[sg.b]
        const x = pa.x + (pb.x - pa.x) * sg.u, y = pa.y + (pb.y - pa.y) * sg.u
        const size = sg.you ? 14 : sg.lit ? 7 : 4.5
        ctx.globalAlpha = (sg.you || sg.lit ? 1 : 0.7) * Math.sin(Math.PI * sg.u) * fog((pa.depth + pb.depth) / 2)
        ctx.drawImage(col.spark, x - size, y - size, size * 2, size * 2)
      }
      ctx.globalAlpha = 1
      ctx.textAlign = 'center'
      for (const i of order) {
        const p = proj[i], node = g.nodes[i]
        const named = i === W.sel || i === W.hover || W.live.has(i) || (near ? near.has(i) : (node.degree >= 10 && p.depth < 900) || node.group === 'core')
        if (!named) continue
        const strong = i === W.sel || i === W.hover
        ctx.font = `${strong ? 600 : 500} ${strong ? 14 : 11}px ${col.font}`
        ctx.fillStyle = strong ? col.text : col.muted
        ctx.globalAlpha = strong ? 1 : 0.85 * fog(p.depth)
        ctx.fillText(node.label, p.x, p.y - Math.max(10, (5 + Math.sqrt(node.degree || 0) * 2.4) * p.scale * 2) - 6)
      }
      ctx.globalAlpha = 1
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [state])

  useEffect(() => { if (w.current) { w.current.tour = tour; w.current.lastHop = 0 } }, [tour, state])

  // keys of the room: Esc surfaces (or lets go of the chosen node first), space starts or stops the journey, / searches
  useEffect(() => {
    const onKey = e => {
      const typing = e.target instanceof HTMLInputElement
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        if (typing) { e.target.blur(); setQuery(''); return }
        if (w.current?.sel !== null && w.current?.sel !== undefined) { setTour(false); select(null); return }
        onClose()
        return
      }
      if (typing) return
      if (e.key === ' ') { e.preventDefault(); setTour(v => !v) }
      if (e.key === '/') { e.preventDefault(); searchBox.current?.focus() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  const pick = (x, y) => {
    const W = w.current
    if (!W) return null
    let best = null, bestD = Infinity
    W.proj.forEach((p, i) => {
      if (!p || p.scale <= 0 || W.hidden.has(W.g.nodes[i].group)) return
      const r = Math.max(9, (5 + Math.sqrt(W.g.nodes[i].degree || 0) * 2.4) * p.scale * 2.2)
      const d = Math.hypot(p.x - x, p.y - y)
      if (d < r && (d < bestD || (d === bestD && p.depth < W.proj[best].depth))) { best = i; bestD = d }
    })
    return best
  }
  const at = e => { const r = canvas.current.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top] }
  const down = e => {
    if (!w.current) return
    canvas.current.setPointerCapture?.(e.pointerId)
    w.current.drag = { x: e.clientX, y: e.clientY, moved: 0 }
  }
  const move = e => {
    const W = w.current
    if (!W) return
    if (W.drag) {
      const dx = e.clientX - W.drag.x, dy = e.clientY - W.drag.y
      W.drag = { x: e.clientX, y: e.clientY, moved: W.drag.moved + Math.abs(dx) + Math.abs(dy) }
      W.cam.yaw += dx * 0.006
      W.cam.pitch = Math.max(-1.4, Math.min(1.4, W.cam.pitch + dy * 0.006))
      return
    }
    const i = pick(...at(e))
    if (i !== W.hover) { W.hover = i; setHover(i) }
  }
  const up = e => {
    const W = w.current
    if (!W?.drag) return
    const click = W.drag.moved < 5
    W.drag = null
    if (click) { setTour(false); select(pick(...at(e))) }
  }
  const wheel = e => {
    const W = w.current
    if (!W) return
    e.preventDefault()
    W.goal.dist = Math.max(70, Math.min(1800, W.goal.dist * Math.exp(e.deltaY * 0.0012)))
  }
  useEffect(() => {
    const cv = canvas.current
    if (!cv || state !== 'ok') return undefined
    cv.addEventListener('wheel', wheel, { passive: false })
    return () => cv.removeEventListener('wheel', wheel)
  }, [state])

  const W = w.current
  const g = W?.g
  const node = g && sel !== null ? g.nodes[sel] : null
  const found = g ? graphFind(g.nodes, query) : []
  const counts = g ? GRAPH_GROUPS.map(k => [k, g.nodes.filter(n => n.group === k).length]).filter(([, k]) => k) : []
  const label = id => { const i = g?.index.get(id); return i === undefined ? id : g.nodes[i].label }
  const go = id => { const i = g?.index.get(id); if (i !== undefined) { setTour(false); select(i) } }
  const toggle = k => setHidden(h => { const x = new Set(h); if (x.has(k)) x.delete(k); else x.add(k); return x })
  const edgeList = (list, other) => html`<ul class="inner-links">${list.map(e => html`<li key=${`${e.s}>${e.t}`}>
    <button type="button" class=${`inner-link g-${g.nodes[g.index.get(e[other])]?.group ?? 'other'}`} onClick=${() => go(e[other])}>
      <span class="inner-dot" aria-hidden="true"></span><span class="inner-link-name">${label(e[other])}</span>
      <small class="mono">${e.key || e.kind}</small></button></li>`)}</ul>`

  return html`<div class="inner" ref=${room} role="dialog" aria-modal="true" aria-label=${t.title}>
    <canvas ref=${canvas} class=${`inner-canvas${hover !== null ? ' is-pointing' : ''}`}
      onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${() => { if (w.current) w.current.drag = null }}
      onPointerLeave=${() => { if (w.current) { w.current.hover = null; setHover(null) } }}></canvas>
    <div class="inner-top">
      <div class="inner-head">
        <span class="label-caps">${t.kicker}</span>
        <h2 class="inner-title">${t.title}</h2>
        ${g ? html`<p class="inner-count">${t.count(g.nodes.length, g.links.length)}${liveN ? html` · <b class="inner-live-n">${t.liveCount(liveN)}</b>` : null}</p>` : null}
      </div>
      <div class="inner-search">
        <input ref=${searchBox} type="search" class="inner-search-input" placeholder=${t.search} aria-label=${t.search}
          value=${query} onInput=${e => setQuery(e.currentTarget.value)}
          onKeyDown=${e => { if (e.key === 'Enter' && found.length) { setTour(false); select(found[0]); setQuery(''); e.currentTarget.blur() } }} />
        ${found.length ? html`<ul class="inner-found">${found.map(i => html`<li key=${i}><button type="button"
          class=${`inner-link g-${g.nodes[i].group}`} onClick=${() => { setTour(false); select(i); setQuery('') }}>
          <span class="inner-dot" aria-hidden="true"></span><span class="inner-link-name">${g.nodes[i].label}</span>
          <small class="mono">${g.nodes[i].family}</small></button></li>`)}</ul>` : null}
      </div>
      <div class="inner-tools">
        <button type="button" class=${`inner-btn${tour ? ' is-on' : ''}`} aria-pressed=${String(tour)} onClick=${() => setTour(v => !v)}
          disabled=${state !== 'ok'}>${tour ? t.tourStop : t.tour}</button>
        <button type="button" class="inner-btn" onClick=${onClose}>${t.close}</button>
      </div>
    </div>
    ${state === 'loading' ? html`<p class="inner-state">${t.loading}</p>` : null}
    ${state === 'error' ? html`<p class="inner-state">${t.error}</p>` : null}
    ${g ? html`<div class="inner-legend" role="group" aria-label=${t.regions}>
      ${counts.map(([k, n]) => html`<button type="button" key=${k} class=${`inner-region g-${k}${hidden.has(k) ? ' is-off' : ''}`}
        aria-pressed=${String(!hidden.has(k))} onClick=${() => toggle(k)}>
        <span class="inner-dot" aria-hidden="true"></span>${t.group[k] ?? k}<span class="num">${n}</span></button>`)}
    </div>` : null}
    ${node ? html`<aside class=${`inner-panel g-${node.group}`} aria-live="polite">
      <div class="inner-panel-head">
        <span class="inner-dot" aria-hidden="true"></span>
        <span class="label-caps">${t.group[node.group] ?? node.group} · ${node.family}</span>
        <button type="button" class="inner-x" aria-label=${t.letGo} title=${t.letGo} onClick=${() => { setTour(false); select(null) }}>×</button>
      </div>
      <h3 class="inner-node">${node.label}</h3>
      ${node.title && node.title !== node.label ? html`<p class="inner-node-title">${node.title}</p>` : null}
      <p class="inner-path mono">${node.id}${node.status ? html` · <b>${node.status}</b>` : null}</p>
      ${W.live.get(sel) ? html`<p class=${`inner-live is-${W.live.get(sel).tone}`}><span class="inner-dot" aria-hidden="true"></span>
        ${t.live[W.live.get(sel).tone](W.live.get(sel).text)}
        ${W.live.get(sel).ref ? html`<button type="button" class="inner-btn" onClick=${() => onTab(W.live.get(sel).ref)}>${t.toTab}</button>` : null}</p>` : null}
      ${isWork(node) ? html`<button type="button" class="inner-btn inner-open"
        onClick=${() => { onClose(); c.openItem(`task:${node.label}`) }}>${t.openTask}</button>` : null}
      ${detail?.out?.length ? html`<h4 class="label-caps inner-sub">${t.out(detail.out.length)}</h4>${edgeList(detail.out, 't')}` : null}
      ${detail?.in?.length ? html`<h4 class="label-caps inner-sub">${t.in(detail.in.length)}</h4>${edgeList(detail.in, 's')}` : null}
      ${detail && !detail.error && !detail.out?.length && !detail.in?.length ? html`<p class="inner-muted">${t.alone}</p>` : null}
      ${detail?.text ? html`<h4 class="label-caps inner-sub">${t.content}</h4><pre class="inner-text mono">${detail.text}${detail.cut ? '\n…' : ''}</pre>` : null}
      ${!detail ? html`<p class="inner-muted">${t.reading}</p>` : null}
    </aside>` : null}
    <p class="inner-hint">${tour ? t.hintTour : t.hint}</p>
  </div>`
}
