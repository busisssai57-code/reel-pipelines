# Reel Studio — "Aurum" UI/UX Redesign Plan

> Apple-inspired, motion-first redesign of the Reel Studio dashboard.
> Premium **black + gold** aesthetic, restrained 6-colour system, and an
> **Agents section reimagined as a living "Orchestra."**
> Status: **design spec** — ready for a frontend team (or a follow-up build pass).

This plan builds *on top of* the existing design system — it does not throw it
away. The current `web/src/lib/styles/tokens.css` (8-pt grid, fluid type, SF Pro
stack, motion tokens, materials, light/dark, reduced-motion guard, View
Transitions) is already Apple-grade. Aurum is a **palette + elevation + motion +
Agents** layer, expressed as new tokens and components.

---

## 0. Context (filled)

| Field | Value |
|---|---|
| **Platform** | Web — responsive SPA, installable PWA (SvelteKit 5 + `adapter-static`). Desktop-first with a mobile bottom-tab bar. Evergreen browsers. |
| **Audience** | The **studio operator** (a single power user running the autonomous reel-production system) who needs at-a-glance system health + control. Secondary: remote viewers of the public showcase (`bta.pages.dev`) who see the UI shell with offline states. |
| **Brand palette** | black · gold · red · white · blue · orange (hard constraint) |
| **References** | This codebase · Apple HIG · Apple Pro apps (Final Cut, Logic) · Apple TV / product-page dark aesthetic · Linear / Vercel for information density |
| **Constraints** | Brand-aligned, accessible (WCAG 2.2 AA min), performant (transform/opacity-only animation, 60fps), responsive, no new heavy deps |

---

## 1. North Star & principles

1. **Premium restraint.** Black canvas, white type, *one* signature colour (gold)
   used sparingly so it always feels expensive. Colour = meaning, never decoration.
2. **Motion with intent.** Every animation explains a change (state, navigation,
   data). Nothing loops for decoration except a single "alive" breath on active
   elements. All motion collapses under `prefers-reduced-motion`.
3. **Deference.** Content and live data are the hero; chrome recedes into glass
   materials and hairlines.
4. **Depth, not noise.** Soft elevation + a faint **gold hairline** on raised,
   premium surfaces conveys hierarchy without borders shouting.
5. **The Agents section is the showpiece** — it must feel like watching a living
   machine, not reading a table.

---

## 2. Visual design system — "Aurum"

### 2.1 Colour — semantic mapping of the 6 brand colours

Apple uses a near-monochrome canvas + a few colours that each carry a **job**.
We assign every brand colour a single semantic role so the UI stays legible:

| Brand colour | Role | Where it appears |
|---|---|---|
| **Black** | Canvas / substrate | App background (true black, OLED), deepest shadow |
| **White** | Text / icons / light surfaces | Label hierarchy (92/55/35% on dark), light-mode surfaces |
| **Gold** | **Signature** — premium, approved, achievement | Brand mark, hero numerals, focus glow, "approved/published" status, outcome scores, the gold hairline |
| **Blue** | **Primary / interactive** | Buttons, links, selected nav, "running/active" system state, focus ring base |
| **Red** | Destructive / live / failure | Reject, delete, errors, tripped circuit, the `● LIVE` render dot |
| **Orange** | Warning / in-progress | Rendering, self-healing/retry, caution, half-open circuit |

> **Greens are intentionally absent** (not in the palette). The codebase's
> `--success: #34c759` is **remapped**: positive *outcomes* (approved, published,
> score) → **Gold**; positive *operational* state (healthy, running) → **Blue**.
> Because we collapse the green channel, **status is never colour-only** — every
> status carries an icon + text label (see §6 Accessibility). This is the primary
> palette↔convention conflict, resolved in favour of accessibility.

### 2.2 Colour tokens (paste-ready) — add to `tokens.css`

Aurum is **dark-first**. Add a `[data-theme="aurum"]` block (and make it the
default in the no-flash script + Settings). Light mode keeps the existing values
but swaps accent→blue stays, success→gold.

```css
/* ---- Aurum (premium dark) — new default ---- */
[data-theme="aurum"] {
  /* Canvas & surfaces (black + white substrate) */
  --bg:         #000000;
  --surface:    #131316;   /* raised glass */
  --surface-2:  #1c1c20;   /* inset / controls */
  --label:      rgba(255,255,255,.92);
  --label-2:    rgba(255,255,255,.58);
  --label-3:    rgba(255,255,255,.38);
  --separator:  rgba(255,255,255,.10);

  /* Signature gold (metallic; large/icon use the bright tone, text uses -ink) */
  --gold:       #E8B23A;   /* on #000 ≈ 9.7:1 (AAA) */
  --gold-ink:   #F2C95B;   /* small text on dark ≈ 11:1 */
  --gold-edge:  rgba(232,178,58,.22);          /* the premium hairline */
  --gold-grad:  linear-gradient(135deg,#F6D67A,#E8B23A 45%,#C8902A);

  /* Interactive / primary */
  --accent:     #0A84FF;   /* large/fill */
  --accent-ink: #4DA3FF;   /* small interactive text on dark ≈ 7.4:1 */
  --accent-on:  #ffffff;

  /* Status (each always paired with icon+label) */
  --running:    #0A84FF;   /* blue   — active */
  --warning:    #FF9F0A;   /* orange — in-progress / healing  ≈ 9.2:1 */
  --danger:     #FF453A;   /* red    — failed / live          ≈ 5.3:1 */
  --approved:   #E8B23A;   /* gold   — approved / published */

  /* Fills & materials */
  --fill:       rgba(255,255,255,.10);
  --fill-2:     rgba(255,255,255,.06);
  --material:        color-mix(in srgb, var(--surface) 64%, transparent);
  --material-blur:   blur(24px) saturate(180%);

  /* Elevation — soft + an optional gold rim for premium surfaces */
  --e-1: 0 1px 2px rgba(0,0,0,.5), 0 8px 24px rgba(0,0,0,.45);
  --e-2: 0 8px 24px rgba(0,0,0,.55), 0 28px 64px rgba(0,0,0,.6);
  --e-gold: 0 0 0 1px var(--gold-edge), 0 10px 40px rgba(232,178,58,.10);
}
```

> **Gold in light mode** must darken for text contrast: use `--gold-ink:#8A6D1C`
> (≈4.6:1 on white). Bright `#E8B23A` is decorative-only on light backgrounds.

### 2.3 Typography

Keep the existing stack and fluid scale; add a **display/hero** treatment.

- **Family:** `-apple-system, "SF Pro Display/Text", "Inter Variable", system-ui` (already shipped via `@fontsource-variable/inter`).
- **Scale:** existing `--t-caption…--t-display` (13 → clamp 56px).
- **Hero numerals:** tabular (`font-variant-numeric: tabular-nums`, already global via `.tnum`), tracking `-0.03em`, optionally painted with `--gold-grad` (`background-clip:text`) for the single biggest metric on a screen — never more than one gold numeral per view.
- **Weights:** Display 700/750; titles 700; body 400/600; labels 650–700 (matches current).
- **Letter-spacing:** headings `-0.02em` (already set); display `-0.03em`.

### 2.4 Iconography

- Keep the existing line-icon set (`lib/components/Icon.svelte`), 1.5–2px stroke,
  rounded joins — SF-Symbols-like.
- **Rule:** icons inherit `currentColor`; status icons take the status colour AND
  sit next to a text label.
- Add 3 agent-centric glyphs: `pulse` (activity), `gauge` (circuit), `orbit`
  (orchestra view toggle).

### 2.5 Spacing, grid, radius

Unchanged — the 8-pt grid (`--sp-1…8`), radius scale (`--r-sm…--r-pill`), and
44px touch targets are correct. Aurum adds **one** elevation idea: *premium*
surfaces (hero panels, the active agent) get the `--e-gold` rim; everything else
uses `--e-1/2`. Restraint keeps gold meaningful.

---

## 3. Motion & interaction

Built on the existing `lib/motion.ts` — **do not invent new timings.**

### 3.1 Tokens (already defined)

| Token | Value | Use |
|---|---|---|
| `--d-micro` 120ms | press, ripple | tap feedback |
| `--d-fast` 200ms | hover, toggles, route fade | most micro-interactions |
| `--d-base` 320ms | cards, sheets, FLIP | element enter/move |
| `--d-slow` 420ms | progress ring, large reveals | hero |
| `--d-hero` 520ms | first-paint hero | once per screen |
| Easings | standard / decelerate / accelerate / emphasized | `--e-*` |
| Springs | snappy / smooth / bouncy | `SPRING` presets |

### 3.2 Signature motions

1. **Page transition** — keep the route-level View Transitions (`onNavigate` +
   `::view-transition`), `--d-fast`, cross-fade + 4px rise. Title morphs.
2. **List stagger** — cards enter `y:+12, opacity:0 → 0`, spring `smooth`, 24ms
   stagger, cap 10 items then instant.
3. **FLIP reorder** — `animate:flip` (already used) when agents/drafts re-sort by
   status; `--d-base`, emphasized easing.
4. **Number roll** — metrics tween with `svelte/motion tweened`, `--d-slow`,
   `cubicOut`, tabular to avoid jitter (the Render ring already does this).
5. **Gold shimmer** — a *one-shot* diagonal sheen sweeps a metric/badge when it
   reaches a milestone (draft approved, score = 1.0). 700ms, runs once, never loops.
6. **Bus pulse** *(Agents centerpiece)* — when an event travels agent A→B, a 6px
   light dot animates along the connecting edge (160–260ms, decelerate). Colour =
   event class (blue normal / orange healing / red error / gold outcome).
7. **Breath** — active status dots/rings opacity 1↔.45, 2s ease-in-out (exists in
   `AgentCard`). The *only* permitted infinite loop.

### 3.3 Micro-interactions

| Element | Rest → Hover → Active |
|---|---|
| Button (primary) | gradient blue → brightness +6%, lift 1px → scale .98, 120ms |
| Card / tile | `--e-1` → lift `translateY(-4px)` + `--e-gold` rim + ≤3° pointer-tilt → settle |
| Nav link | `--label-2` → `--fill-2` bg → selected = gold left-bar + `--accent` text |
| Toggle/Theme | thumb spring `snappy`; icon cross-fade 200ms |
| Focus | `:focus-visible` = 3px `--accent` outline + 2px offset (exists) → on premium controls add a soft `--gold-edge` glow |

### 3.4 Reduced motion

`d()` already collapses durations to 0 and springs to instant under
`prefers-reduced-motion`. The global guard in `tokens.css` neutralises CSS
animations. **Bus pulses and shimmer become instant state changes** (dot appears
at destination; badge just turns gold). No information is motion-only.

---

## 4. Layout & wireframes

### 4.1 App shell (Aurum)

Same structure as today (`+layout.svelte`): sticky glass **sidebar** (248px) +
glass **topbar** + mobile **bottom tabs**. Aurum changes: true-black canvas,
gold brand mark, selected nav gets a **gold accent bar** + blue label.

```
┌──────────────┬─────────────────────────────────────────────────────────┐
│ ◆ REEL STUDIO│  Agents                          ◷ Synced · ⟳ · ☾        │ ← glass topbar
│  (gold mark) │─────────────────────────────────────────────────────────│
│              │                                                         │
│ ▸ Dashboard  │   [ page content ]                                      │
│ ▸ Render     │                                                         │
│ █ Agents  ◀──┼── selected: gold left-bar, blue text, fill tint         │
│ ▸ Drafts     │                                                         │
│ ▸ Trends     │                                                         │
│ ▸ Queen      │                                                         │
│ ▸ Settings   │                                                         │
└──────────────┴─────────────────────────────────────────────────────────┘
   sticky glass            max-width 1440, 32px gutters
mobile: sidebar→bottom tab bar (Dashboard·Render·Drafts·Agents·Queen)
```

### 4.2 Dashboard (overview)

```
┌──────────── System Vitals (gold-rim hero glass) ───────────────┐
│  ⬤ ALL SYSTEMS NOMINAL        events/min  ▁▂▅▇▆▃  ← sparkline   │
│  12 agents · 9 idle · 2 running · 1 healing                     │
└────────────────────────────────────────────────────────────────┘
┌─ Drafts this week ─┐ ┌─ Render queue ─┐ ┌─ Approval rate ─┐
│   21  (gold tnum)  │ │  ◔ 1 active    │ │   86%  ▁▃▅▇      │   ← StatCards, stagger-in
└────────────────────┘ └────────────────┘ └─────────────────┘
┌─ Live event feed ───────────────────────────────────────────┐
│ ● 12:04 quality   export_scored  A_57  score 1.0  (gold)    │
│ ● 12:03 visual_qa qa_pass        27.3s                       │
└──────────────────────────────────────────────────────────────┘
```

### 4.3 Render

Keep the existing two-pane Studio (form + progress ring + timeline), restyled:
the ring track on black, **blue→gold gradient** stroke as it nears 100%, the
center numeral tabular; `● LIVE` red dot while encoding; stage chips light up
blue→gold as they complete. (Pairs with the real per-stage SSE events from
Phase 1 of the upgrade plan — exact progress replaces today's heuristic.)

---

## 5. The Agents section — "The Orchestra" (centerpiece)

**Goal:** turn a flat card grid into a *living system view*. Three coordinated
parts, progressively enhanced (grid works without the canvas).

### 5.1 Information architecture

```
Agents
├── System Vitals bar      (health rollup + throughput)
├── View switch:  [ Orchestra ◯ ]  [ Grid ▦ ]   ← segmented, remembers choice
├── Orchestra (default, desktop)   — constellation of agent nodes + bus edges
├── Grid (default, mobile / reduced-motion) — enhanced Agent Tiles
└── Agent Detail sheet     (slide-over on select)
```

### 5.2 System Vitals bar

A gold-rim glass panel:
- Big tabular count of agents; segmented breakdown `running / idle / healing /
  tripped` with the status colours + labels.
- **Throughput sparkline** (events/min over last ~5 min) painted gold.
- A single "health word" with a breathing dot: **NOMINAL** (blue), **HEALING**
  (orange), **DEGRADED** (red) — driven by worst circuit state.

### 5.3 Orchestra (constellation)

```
                 ┌───────────────────────────────────────────┐
                 │            ◦ AudienceFeedback              │
                 │       ╱            ·pulse·          ╲       │
                 │  ◦ Variant ── ● Trigger ──→ ● Render ◦     │   ● = active (gold/blue glow)
                 │       ╲          (hub)          ╱           │   ◦ = idle (dim)
                 │     ◦ Episodes ── ◦ AutoPost ── ◦ QA       │   ── = bus subscription edge
                 │            light dot travels A→B on event   │
                 └───────────────────────────────────────────┘
```

- **Nodes** = agents, placed on a calm ring/orbit (deterministic layout; no
  jitter). Each node: icon in a **status ring** (animated SVG `stroke-dashoffset`),
  name on hover, gold halo when it's the most-recently-active agent.
- **Edges** = real bus subscriptions (`subscribes` / emitted types). Faint
  hairlines; a **bus-pulse** dot animates along an edge when an event flows
  (colour by event class).
- **Reduced-motion / mobile / no-canvas:** the constellation degrades to the Grid
  automatically; pulses become a brief node highlight.
- Built with SVG (not canvas) so nodes are real DOM = focusable + screen-reader
  labelled; ≤ ~15 nodes so perf is trivial.

### 5.4 Agent Tile (enhanced card) — replaces `AgentCard.svelte`

```
┌─────────────────────────────────────────────┐
│  ◉ TriggerAgent                  ● running   │  ◉ = icon inside status ring
│  creates render jobs                          │  ● status pill (dot + label)
│  ▁▂▁▄▂▆▃▁  ← 20-event activity sparkline (gold)│
│  ─────────────────────────────────────────── │
│  Did     start_render · A_57   2m ago         │
│  Reacts  ui.trigger, cron, reject             │
│  Score   ◍◍◍◍◌  0.82   (gold micro-gauge)      │
│  Circuit ✓ closed (blue)  |  ⚠ half (orange) | ✕ open (red)
└─────────────────────────────────────────────┘
hover → lift + gold rim + ≤3° tilt   ·   click → Detail sheet
```

New vs. today's card: **status ring** around the icon, **activity sparkline**,
**outcome-score micro-gauge** (gold), a clearer **circuit gauge**, hover lift +
gold rim, and click-to-expand. Enter with stagger; FLIP when re-sorted by status
(tripped → healing → running → idle).

### 5.5 Agent Detail sheet

Slide-over from the right (desktop) / sheet up (mobile), backdrop blur, spring-in:

```
┌──────────────────────────────── ✕ ┐
│ ◉ VisualQAAgent          ● running │
│ validates reel vs. voiceover       │
│ ┌ Circuit ───────────────────────┐ │
│ │  ✓ CLOSED   fails 0/3   ▁▁▁     │ │  state machine + recent fails
│ └────────────────────────────────┘ │
│ Outcome score   0.82  ▁▃▅▇  (gold) │  trend line
│ Timeline                            │
│  ● qa_pass     27.3s         2m     │  per-agent event stream
│  ● qa_pass     ok            5m     │  (vertical, colour-coded dots, stagger)
│  ● stage_error timeout       1h     │
│ Subscribes: render_done             │  relationship chips
│ Emits: qa_pass, qa_fail             │
└────────────────────────────────────┘
```

Close on ✕ / Esc / backdrop / swipe-down. All data is already on the agent
object + bus events (`recent_events(job_id)` / per-agent filter).

### 5.6 States

- **Empty:** "No agents reporting — start the backend with `run.py ai-team`."
  (centered, dim, mono code chip — exists today, restyle).
- **Loading:** skeleton tiles (`Skeleton.svelte`) shimmer once.
- **Offline (no backend):** vitals bar shows **DEGRADED**, tiles show last-known
  + a dim "offline" ribbon (the hosted site's normal remote state).

### 5.7 Data contract (already available, mostly)

`Agent { name, role, status, last_action{type,note,ts}, waits_for, subscribes,
circuit_open }` + **outcome score** from `priors` (expose via `/api/agents` if not
already). Live updates via the `live` store (polling now → SSE in Phase 1).

---

## 6. Accessibility

| Concern | Spec |
|---|---|
| **Contrast (dark)** | white text 21:1 (AAA); gold `#E8B23A` 9.7:1; orange 9.2:1; red 5.3:1 (AA); blue fill 5.0:1 → small interactive text uses `--accent-ink #4DA3FF` 7.4:1. Verified targets ≥ AA, most AAA. |
| **Contrast (light)** | gold text → `#8A6D1C` (4.6:1); never bright gold on white for text. |
| **No colour-only meaning** | every status = colour **+ icon + text** (pill label, circuit ✓/⚠/✕). Critical because we dropped green. |
| **Focus** | `:focus-visible` 3px `--accent` ring + 2px offset (global). Orchestra nodes & tiles are real, tabbable DOM with `aria-label="TriggerAgent, running, circuit closed"`. |
| **Keyboard** | full tab order; Orchestra nodes Enter/Space → sheet; sheet traps focus, Esc closes, returns focus to trigger. Arrow-key roving between tiles. |
| **Screen reader** | live regions: vitals + event feed `aria-live="polite"`; sheet `role="dialog" aria-modal`. Sparklines `aria-hidden` with an adjacent text value. |
| **Motion** | `prefers-reduced-motion` collapses all (existing `d()` + global guard); pulses/shimmer become instant. |
| **Targets** | ≥ 44px (`--touch-min`); mobile tabs 48px. |

---

## 7. Component library (reusable)

New / changed Svelte components (in `web/src/lib/components/`):

| Component | Purpose | Key props |
|---|---|---|
| `SystemVitals.svelte` | health rollup + throughput | `agents`, `events` |
| `AgentOrchestra.svelte` | SVG constellation + bus pulses | `agents`, `edges`, `onselect` |
| `AgentTile.svelte` *(replaces `AgentCard`)* | enhanced card | `agent`, `onselect` |
| `StatusRing.svelte` | animated SVG ring around an icon | `status`, `size` |
| `Sparkline.svelte` | tiny activity/score chart (gold) | `points`, `aria` |
| `Gauge.svelte` | circuit + score micro-gauge | `value`, `tone` |
| `Sheet.svelte` | slide-over / bottom-sheet shell | `open`, `side`, `onclose` |
| `AgentDetail.svelte` | sheet body: timeline + circuit + trend | `agent`, `events` |
| `Shimmer.svelte` (action) | one-shot gold sheen on milestone | `trigger` |

Reuse as-is: `Icon`, `Brand`, `StatCard`, `EventFeed`, `SyncChip`, `ThemeToggle`,
`Skeleton`, `Placeholder`, `Toast`.

---

## 8. Implementation guide (developers)

**Phased, low-risk, behind the existing token system.**

**Phase A — Aurum tokens (½ day).**
Add the `[data-theme="aurum"]` block to `tokens.css` (§2.2); set Aurum as the
default in the no-flash script (`app.html`) and the Settings theme list (add
"Aurum / Light / Dark / Auto"). Remap `--success`→`--approved`(gold) usages.
*Outcome:* whole app reskins instantly; zero component edits.

**Phase B — Motion polish (½ day).**
Add `Shimmer` action + the gold-rim hover on cards; wire number-roll where
metrics exist (StatCards). Everything else is already in `motion.ts`.

**Phase C — Agents Grid v2 (1–2 days).**
Build `StatusRing`, `Sparkline`, `Gauge`; ship `AgentTile` (replace `AgentCard`);
add `SystemVitals`. Grid-only — fully usable, no canvas yet.

**Phase D — Agent Detail sheet (1 day).**
`Sheet` + `AgentDetail` (timeline from `recent_events`, circuit + score trend).

**Phase E — Orchestra (2–3 days, progressive).**
`AgentOrchestra` SVG constellation + bus-pulse; feature-detect + reduced-motion →
fall back to Grid. Wire pulses to the Phase-1 SSE event stream when it lands.

**Backend touch-ups (small):** ensure `/api/agents` returns `subscribes`,
`waits_for`, and the per-agent **outcome score** (from `priors`); per-agent event
filter already exists via `bus.recent_events(job_id)` — add an agent filter.

**Performance:** animate only `transform`/`opacity`; SVG ≤ ~15 nodes; sparklines
are pre-sampled arrays; respect `content-visibility:auto` on off-screen tiles.

**Assets:** no images required — all gold/gradients are CSS; 3 new line icons.

---

## 9. Execution checklist

- [x] Apple-like look & feel with smooth animations — *Aurum spec, motion §3*
- [x] Agents section enhanced beyond basic — *Orchestra + Tiles + Detail §5*
- [x] Colour theme applied consistently — *semantic 6-colour map §2.1, tokens §2.2*
- [x] Accessibility included — *§6 (contrast, focus, keyboard, SR, reduced-motion)*
- [x] Deliverables scoped for developers — *components §7, phased build §8*

## 10. Conflict resolution

- **Palette vs. status convention (no green):** success/healthy remapped to
  gold (outcome) / blue (operational); **status always carries icon + label** so
  meaning survives for colour-blind users. *Accessibility wins.*
- **Gold legibility on light backgrounds:** bright gold is decorative-only;
  text-gold darkens to `#8A6D1C`. *Contrast wins over brand vibrancy.*
- **Constellation richness vs. perf/SR/reduced-motion:** Orchestra is
  progressive enhancement over a fully functional Grid; SVG DOM keeps it
  accessible. *Usability wins; the wow is additive.*
