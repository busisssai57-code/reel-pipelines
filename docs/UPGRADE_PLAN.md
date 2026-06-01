# Reel Studio — Pipeline & UI Upgrade Plan
### Apple-inspired, motion-first rebuild + full pipeline upgrade

**Status:** Proposed · **Owner:** UI/UX + Systems · **Date:** 2026-06-01
**Decisions locked:** (1) Rebuild the dashboard as a **component app** (SvelteKit, see §5.2). (2) **Full scope** — UI + real-time backend + pipeline capability upgrades + multi-user/auth + PWA/offline.

> Conflict-resolution order (from the brief, applied throughout): **Constraints/do-nots > required outputs > examples/references > preferences.** Where rules collide, **accessibility, offline-resilience, and "runs on any PC" win over visual polish.** Motion is layered on top of a fully-functional, reduced-motion-safe baseline — never a prerequisite for using the product.

---

## 1. Executive Summary

Reel Studio already ships a working autonomous reel-production system (Python stdlib backend, SQLite, event bus, 12 agents, local Qwen/Kokoro/Whisper/Hunyuan, FFmpeg) and **two** divergent front-ends:

- `dashboard/index.html` — the **operator dashboard** (1,556 lines, dark-only, vanilla JS). Live agents, Queen/Qwen chat, render ring, niche/fact-check/review. But: 3.5s polling, full-`innerHTML` re-render every tick, a broken web-font, no light mode, no reduced-motion, a non-advancing render ring, and a **dead Drafts view** (DOM exists, no `updateDrafts()`).
- `dashboard/bta-site/index.html` — the **public showcase** (~40 KB, light+dark, system fonts, accessible). Implements the `UI_BLUEPRINT.md` IA (Queue / Schedule / Drafts) but lacks the live agent/queen/render surfaces.

This plan **unifies both into a single SvelteKit app** with a real Apple-grade motion system, replaces polling with **Server-Sent Events (SSE)** over the existing event bus, fixes the correctness bugs, and adds the pipeline capabilities the system has outgrown its UI for (auth/roles, scheduling, distribution, quality gates, PWA/offline, observability).

**The thesis:** *animation without live data is theater.* The single highest-leverage change is SSE + keyed/diffed rendering — only then do entrance/exit/FLIP/spring animations represent real state instead of decorating a poll.

---

## 2. Scope & Non-Goals

### In scope
1. **Front-end rebuild** — one SvelteKit app replacing both HTML files; static export to Cloudflare Pages + GitHub Pages (deploy flow unchanged).
2. **Apple design language** — tokens, light/dark, materials/vibrancy, depth, type, iconography (§6).
3. **Motion system** — named transitions, spring physics, shared-element/hero morphs, list FLIP, scroll choreography, reduced-motion parity (§7).
4. **Real-time transport** — SSE endpoint on the stdlib server; live agents, render progress, event feed (§5.1).
5. **Pipeline upgrades** — new/upgraded agents, expanded quality gates, distribution hardening, scheduler (§5.4).
6. **Auth & multi-user** — operator vs. admin roles, sessions, audit log, replacing the single `REEL_API_KEY` (§5.3).
7. **PWA / offline** — app-shell caching, offline approve/reject action queue, background sync (§5.5).
8. **Accessibility** — WCAG 2.2 AA, keyboard, SR, reduced-motion (§10).
9. **Observability** — structured logs, persisted agent timeline, metrics (§5.4).

### Non-goals (this cycle)
- Replacing the ML engines (Qwen/Kokoro/Whisper/Hunyuan stay; all AI remains **local**).
- Migrating off SQLite or off the stdlib HTTP server to a web framework (we extend, not replace).
- Native mobile apps (PWA covers mobile).
- Changing the Discord approval loop's contract (the web UI stays a **parallel front-end to the same cycle**, never a second source of truth).

---

## 3. Current-State Assessment (grounded in code)

| Area | Today | Problem | Plan ref |
|---|---|---|---|
| Transport | `setInterval` 500 ms (render) / 3.5 s (dash) / 5 s (views) polling | Wasteful, laggy, races; can't drive real-time motion | §5.1 SSE |
| Rendering | `el.innerHTML = rows.map(...)` every poll | DOM thrash, scroll jump, lost focus, **un-animatable** lists | §5.2 keyed/FLIP |
| Render ring | `updateProgress(events)` reads `events[stage]` | API returns `{job, events:[…]}` → stages never advance (**bug**) | §9 Render |
| Drafts view | `#draftsList` in DOM | **No `updateDrafts()` — view is dead** | §9 Drafts |
| Fonts | `<link>` to "SF Pro Display" on Google Fonts | Google doesn't host SF Pro → **broken**; Windows users get Segoe UI | §6.3 |
| Theming | `color-scheme: dark` only | No light mode; Apple is adaptive | §6.2 |
| Motion | `fadeInUp`, `pulse`, `spin`, `slideUp`, `feedIn` | No view transitions, springs, shared-element, list motion | §7 |
| a11y | Emoji-as-icons, no landmarks, no `aria-current`, no focus mgmt, no reduced-motion | Fails WCAG 2.2 AA; blueprint demands AA | §10 |
| Auth | Single `REEL_API_KEY`, CORS `*` | No roles; anonymous can trigger renders when tunneled | §5.3 |
| Two UIs | dashboard vs bta-site drift | Divergent IA, double maintenance | §5.2 unify |

**Backend strengths to preserve & exploit:** the event bus (`pipelines/common/bus.py`) already records every agent action with timestamps and supports per-job event streams — SSE is a thin wrapper over `bus.recent_events()`. The `supervisor.run_stage()` self-correction/fallback pattern and circuit breakers give us rich state worth visualizing (retries, healing, breaker-open). Graceful degradation is already the house style — the UI must mirror it (offline/empty/error states, never blank).

---

## 4. Target Environment & Personas (filled inputs)

**Target platform/environment**
- Modern evergreen browsers (Chromium, Safari 18+, Firefox). **Primary operator on Windows 11** (note the repo's **cp1252 footgun** — any new Python must force UTF-8; see `reel-pipelines-windows-utf8`).
- **Static hosting:** Cloudflare Pages (`bta.pages.dev`, direct-upload via `wrangler`) + GitHub Pages (`deploy.yml`). Build output must be fully static.
- **Backend:** local Python stdlib `server.py` on `127.0.0.1:8787`; optionally exposed via Cloudflare quick-tunnel. API base overridable via `?api=` / `localStorage.apiBase` — **preserve this contract.**
- Must serve tablet/mobile and remote/low-bandwidth viewers (blueprint requirement).

**Current pipeline tech stack**
- Python 3.11 stdlib `ThreadingHTTPServer`; SQLite `state.db`; custom event bus; 12 agents; Qwen via Ollama; Kokoro TTS; Whisper timing; Hunyuan/Stable Diffusion; FFmpeg; Pixabay/Pexels/Archive.org; Discord bot (discord.py + APScheduler); YouTube Data API v3 + TikTok Content Posting API. Front-end: single-file vanilla HTML/CSS/JS, polling.

**Personas**
1. **Operator / Reviewer** (primary) — approves the weekly batch (21×2 = 42 drafts), watches renders, chats with the Queen. Wants speed, keyboard flow, zero ambiguity on async state. Often on a second screen / tablet.
2. **Admin / Monitor** — agent health, circuit breakers, schedule, asset licenses, distribution status, settings/keys. Wants observability and control.
3. **Autonomous-system overseer** — trusts the loop but supervises trends, fact-checks, reviewer gates, patches. Wants a live, legible "what is the system doing right now."
4. **Remote / public viewer** (showcase on `bta.pages.dev`) — sees a premium animated shell with offline-safe states when the local backend isn't reachable.

---

## 5. Architecture Overview (the big upgrades)

```
                         ┌──────────────────────────────────────────────┐
   Browser (PWA)         │  SvelteKit app  (adapter-static → Pages)      │
   ┌───────────────┐     │  • routes = views (View Transitions API)     │
   │ Service Worker│◄────┤  • stores: live (SSE), session, prefs        │
   │ app-shell +   │     │  • motion layer (svelte/motion, flip, xfade) │
   │ IndexedDB queue│    │  • a11y baseline + reduced-motion parity      │
   └──────┬────────┘     └───────────────┬──────────────────────────────┘
          │ background sync               │ fetch (REST) + EventSource (SSE)
          ▼                               ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  Python stdlib server.py  (extended, still no web framework)       │
   │  • GET /api/stream         ← NEW: SSE over the event bus           │
   │  • auth: session + roles   ← NEW: replaces single REEL_API_KEY     │
   │  • existing REST endpoints (drafts/agents/render/approve/…)        │
   └───────────────┬──────────────────────────────┬─────────────────────┘
                   ▼                               ▼
            event bus (bus.py)              SQLite state.db
                   ▼                          (+ schedule, audit,
        12 agents · supervisor · circuit        sessions tables)
        breakers · pipelines A/B · FFmpeg
```

### 5.1 Real-time transport — SSE replaces polling
- **New endpoint** `GET /api/stream` (and `GET /api/render/{job}/stream`) on the stdlib server. SSE (`text/event-stream`) is a perfect fit for `ThreadingHTTPServer` — one long-lived thread per client writing `data: {json}\n\n`; no new dependency, works through the Cloudflare tunnel, auto-reconnects natively via `EventSource`.
- The handler tails the event bus (a `queue.Queue` per subscriber fed by `bus.emit`) and streams: `agent_status`, `event`, `render_stage`, `draft_changed`, `qwen_status`, `heartbeat` (15 s keep-alive).
- **Fallback:** if SSE fails (proxy buffering, no backend), the client transparently falls back to today's polling. `EventSource`'s built-in retry handles tunnel restarts.
- **Impact:** every animation becomes truthful — agents pulse when *actually* running, the event feed slides in on *real* emission, the render ring advances on *real* stage events. Removes ~17 polls/min/client.

### 5.2 Front-end stack — **SvelteKit + `adapter-static`** (recommended)
**Why SvelteKit specifically for this repo (not generic React):**
1. **`adapter-static` → pure static output** — drops onto Cloudflare Pages / GitHub Pages exactly like today's `dashboard/`. The `wrangler pages deploy` flow, the `?api=`/`localStorage` override, and the offline-shell story all survive. (`deploy.yml` changes from "copy HTML" to "build then copy `build/`".)
2. **Smallest runtime** — Svelte compiles away; ~10–20 KB vs React+Motion's ~40–60 KB. Directly serves the blueprint's "low-power edge devices / usable on 3G" budget.
3. **Best-in-class built-in motion** — this is the decisive factor for "premium animated":
   - `svelte/animate`'s **`flip`** → automatic list reordering/insert/remove animation. **Directly fixes** the "full-innerHTML can't animate lists" problem.
   - `svelte/motion`'s **`spring`/`tweened`** → physics for the render ring, stat counters, gauges, the cycle-progress meter.
   - `svelte/transition` (`fade`/`fly`/`scale`) + **`crossfade`** → shared-element / hero morphs (a draft card morphing into the detail player; a trend row morphing into the render studio).
   - **`onNavigate` + View Transitions API** → route-level cross-fades/slides with one helper and automatic fallback.
4. **Keyed `{#each}`** gives stable identity → no DOM thrash, no scroll jump, focus preserved, and entrance/exit animations "for free."

**Alternative (swap path):** **React + Vite + Motion (Framer Motion)** if the team standardizes on React. `layoutId` → shared-element; `AnimatePresence` → exit anims. Larger bundle; otherwise the design tokens, motion specs, and API contract in this doc are framework-agnostic and port 1:1.

**App structure (SvelteKit):**
```
web/
├── svelte.config.js          # adapter-static, prerender shell
├── src/
│   ├── lib/
│   │   ├── tokens.css         # design tokens (§6) — single source of truth
│   │   ├── motion.ts          # spring presets, easings, viewTransition()
│   │   ├── api.ts             # REST client (keeps baseUrl override)
│   │   ├── stream.ts          # SSE client + polling fallback (§5.1)
│   │   ├── stores/            # live.ts, session.ts, prefs.ts
│   │   └── components/        # design-system primitives (§8)
│   └── routes/
│       ├── +layout.svelte     # shell: sidebar/topbar/bottom-tabs, theme, SW
│       ├── +page.svelte       # Dashboard
│       ├── render/  agents/  drafts/  trends/  niche/
│       ├── factcheck/  review/  queen/  schedule/  settings/
└── static/  (icons, manifest.webmanifest, offline fallback)
```
The existing `dashboard/` is kept until parity is reached, then replaced by `web/build/`.

### 5.3 Backend evolution — extend the stdlib server, don't replace it
- **Auth & roles (replaces single `REEL_API_KEY`):** add `sessions` + `users` tables; `POST /api/auth/login` issues an HTTP-only cookie; middleware maps session→role. **Roles:** `viewer` (read-only, what remote showcase visitors get), `operator` (approve/reject/render), `admin` (settings, distribution, patches, purge). Mutations require ≥ operator. Keeps `REEL_API_KEY` as a machine-to-machine bearer for the Discord bot/CLI. **Audit log** table records who actioned which draft (reconciles with Discord).
- **API contract:** keep all existing endpoints; add `/api/stream`, `/api/auth/*`, `/api/schedule`, `/api/audit`. Document an OpenAPI-style table so UI and bot share one contract (mirrors `db.py`/`approval_bot.py`).
- **CORS:** tighten from `*` to an allow-list (local origin + the Pages origin + active tunnel) once auth lands, so a tunneled backend can't be driven anonymously.
- **UTF-8 discipline:** any new console output / file read forces `encoding="utf-8"` (repo cp1252 footgun). SSE writes are explicitly UTF-8 encoded.

### 5.4 Pipeline capability upgrades
- **New / upgraded agents** (follow the `agents.py` dataclass + circuit-breaker pattern):
  - **HookOptimizerAgent** — rewrites the first 3 s hook via Qwen; A/B two variants.
  - **ThumbnailABAgent** — generates 2–3 poster variants (extends `thumbnails.py`), tracks pick rate.
  - **ComplianceAgent** — gate before autopost: music license present in `assets`, caption safe-area, no flashing > 3×/s, duration band.
  - **SchedulerOptimizerAgent** — best-time-to-post from `engagement_metrics`, feeds the new Schedule view.
- **Quality gates (expand `quality.py`):** LUFS loudness normalization, leading/trailing silence trim, caption safe-area within 1080×1920, b-roll variety check, hard duration band. Gate `autopost.run_once()` on pass.
- **Distribution hardening:** retry/backoff on YouTube/TikTok posting, per-platform metadata templates, add Instagram Reels path; surface per-platform status in the UI.
- **Observability:** persist the agent action timeline (the bus is currently in-memory for recent events) to a `agent_events` table for history; structured JSON logs; a `/api/metrics` summary (renders/day, approval rate, mean render time, breaker trips).
- **Render queue:** explicit concurrency cap + priority (interactive render > batch) so the UI's "Start render" never starves the weekly batch; expose queue depth + ETA.

### 5.5 PWA / offline (realizes `UI_BLUEPRINT.md` §6)
- **Service Worker:** cache-first app shell; stale-while-revalidate for drafts/posters; `preload="none"` video, range-request streaming.
- **Offline action queue:** approve/reject taps while offline → IndexedDB with optimistic "Queued ⏳" state → **Background Sync** flushes on reconnect → reconcile against server truth (server wins; non-blocking "updated elsewhere" notice).
- **Idempotency:** approve/reject carry draft id + action token so retried queued actions can't double-schedule.
- **Adaptive media:** honor `navigator.connection.effectiveType` / `saveData` → poster-only on 2g/Save-Data.

### 5.6 Deployment (unchanged surface)
- `npm run build` → `web/build/` (static). Cloudflare: `wrangler pages deploy web/build --project-name=bta`. GitHub Pages: `deploy.yml` builds then publishes `web/build/`.
- Local: `run.py serve` serves `web/build/` at `127.0.0.1:8787` (swap `DASH` path) so "open the dashboard" still works offline.
- **Live features still require the local backend** (Python + Ollama) reachable, per `reel-studio-deploy`; remote viewers get the animated shell + offline states unless a tunnel is up.

---

## 6. Design Language (Apple-inspired)

**Principles:** deference (content first — the 9:16 reel is the hero), clarity (legible type, generous space, unambiguous state), depth (translucent materials + soft shadows establish hierarchy and continuity through motion). High contrast, minimal chrome, no skeuomorphism.

### 6.1 Design tokens (single source of truth — `tokens.css`)
```
/* Spacing — 8pt grid */     --sp-1:4  --sp-2:8  --sp-3:12  --sp-4:16  --sp-5:24  --sp-6:32  --sp-7:48  --sp-8:64
/* Radius */                 --r-sm:8  --r-md:12  --r-lg:20  --r-xl:28  --r-pill:999
/* Elevation (light) */      --e-1:0 1px 2px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.06)
                             --e-2:0 4px 12px rgba(0,0,0,.10), 0 16px 48px rgba(0,0,0,.12)
/* Type scale (fluid) */     --t-caption:13  --t-body:15/17  --t-title3:20  --t-title2:24  --t-title1:28  --t-large:34  --t-display:clamp(34,5vw,56)
/* Touch */                  --touch-min:44px
/* Motion */                 see §7
```

### 6.2 Color — adaptive light **and** dark (Apple system palette)
| Role | Light | Dark |
|---|---|---|
| `bg` (base) | `#f5f5f7` | `#000000` |
| `surface` / grouped | `#ffffff` | `#1c1c1e` |
| `surface-2` (raised) | `#fbfbfd` | `#2c2c2e` |
| `label` (primary text) | `rgba(0,0,0,.85)` | `rgba(255,255,255,.92)` |
| `label-2` (secondary) | `rgba(0,0,0,.55)` | `rgba(255,255,255,.55)` |
| `label-3` (tertiary) | `rgba(0,0,0,.35)` | `rgba(255,255,255,.35)` |
| `separator` | `rgba(0,0,0,.10)` | `rgba(255,255,255,.10)` |
| `accent` (systemBlue) | `#007aff` | `#0a84ff` |
| `success` (systemGreen) | `#34c759` | `#30d158` |
| `warning` (systemOrange) | `#ff9500` | `#ff9f0a` |
| `danger` (systemRed) | `#ff3b30` | `#ff453a` |
| Category | history `#2a4d6e` · geography `#2f6e4a` · science `#6e2a2a` · default `#444b58` | (same, paired with text/icon — never color-only) |

Default to `prefers-color-scheme`; allow a manual override in Settings (persist in `prefs` store). Verify every pair ≥ 4.5:1 (text) / ≥ 3:1 (UI borders) in **both** themes.

### 6.3 Typography — fix the broken font
- **Stack:** `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Inter var", "Segoe UI", system-ui, sans-serif`.
- Apple devices render genuine **SF**; **self-host Inter (variable, SIL OFL)** as the cross-platform near-match so the operator's **Windows 11** machine and Android get an SF-like face instead of Segoe UI. **Remove the dead Google-Fonts `<link>`.** Self-hosting also keeps first paint dependency-free (no blocking fetch) and works offline.
- Numerals: enable `font-variant-numeric: tabular-nums` for counters/metrics so animated numbers don't jitter.

### 6.4 Materials & depth (vibrancy)
- Translucent surfaces: `background: color-mix(in srgb, var(--surface) 80%, transparent); backdrop-filter: blur(20px) saturate(180%)`. Tiers: ultraThin / thin / regular for sidebar, topbar, modals, popovers. Fallback solid color when `backdrop-filter` unsupported.
- Hairline borders (`--separator`) + soft elevation, not hard boxes. Sidebar/topbar are sticky vibrant chrome over scrolling content.

### 6.5 Iconography
- Replace emoji-as-semantic-icons (nav, status) with an **SF-Symbols-style inline-SVG set** (stroke 1.5–2, rounded). Emoji may stay decoratively but every nav item gets a real labeled icon + visible text label. Status uses **icon + text + color** (never color-only).

### 6.6 Grid & layout
- ≥ `lg`: vibrant left sidebar (icons+labels, `aria-current`) + sticky top context bar (week selector, cycle meter, sync chip, theme toggle, account). Content max-width 1440px centered.
- `md`: sidebar collapses to icon rail.
- ≤ `sm`: bottom tab bar (Dashboard · Render · Drafts · Agents · More); top bar = title + sync chip. Every nav item is a real route (`<a href>`) — works without JS, restorable after a drop.

---

## 7. Motion & Animation System (detailed specs)

**Doctrine:** animate **transform** and **opacity** only (GPU-composited, 60/120fps); never animate layout/`top`/`width` in hot paths (FLIP handles position). Motion is **functional** — it shows *where things came from and went* (continuity), *what changed* (entrance/exit), and *system status* (live pulses). Everything below has a **reduced-motion** equivalent (§7.5).

### 7.1 Motion tokens
```
/* Durations */   --d-micro:120ms  --d-fast:200ms  --d-base:320ms  --d-slow:420ms  --d-hero:520ms  (UI never > 550ms)
/* Easings */     --e-standard:cubic-bezier(.4,0,.2,1)
                  --e-decelerate:cubic-bezier(0,0,.2,1)     /* entrances */
                  --e-accelerate:cubic-bezier(.4,0,1,1)     /* exits */
                  --e-emphasized:cubic-bezier(.2,0,0,1)     /* hero/shared-element */
/* Springs (svelte/motion) */
   spring-snappy   { stiffness:.2,  damping:.9 }   /* toggles, taps, segmented control */
   spring-smooth   { stiffness:.12, damping:.85 }  /* render ring, meters, counters */
   spring-bouncy   { stiffness:.16, damping:.6 }   /* success confirmations, badges */
```

### 7.2 Named transitions (the catalogue)
| # | Where | Technique | Spec |
|---|---|---|---|
| T1 | **Route / view change** | View Transitions API via `onNavigate` | cross-fade 200ms; lateral routes slide ±12px; respects reduced-motion |
| T2 | **Card → detail (hero)** | `crossfade` / shared-element | draft poster morphs into the player; `--e-emphasized` 520ms |
| T3 | **List insert/remove/reorder** | `animate:flip` + `transition:fade\|fly` | new draft flies in (y:8, fade), removed scales+fades out; flip 320ms standard |
| T4 | **Event feed** | enter `fly` from top (y:-6) + fade | staggered 30ms per item; live on SSE emit |
| T5 | **Render ring** | `spring-smooth` on stroke-dashoffset | progress eases on real `render_stage` events; pulse halo while running |
| T6 | **Stage stepper** | active stage scale 1→1.04 + accent ring; done = check draw-on | check uses SVG path dash 240ms |
| T7 | **Agent status** | running = soft breathing pulse (opacity 1↔.6, 2s); healing = amber shimmer; error = single shake (one 6px, no loop) | maps to bus `agent_status` |
| T8 | **Stat counters** | `tweened` count-up | 600ms `--e-standard`, tabular-nums |
| T9 | **Cycle meter (0–42)** | `spring-smooth` width + gradient sweep | announces "28 of 42" to SR |
| T10 | **Toast / undo** | slide-up + fade, spring-bouncy in, accelerate out | 10s dwell, focusable action |
| T11 | **Modal / sheet** | scale .96→1 + backdrop blur fade | focus-trap; ESC; return focus |
| T12 | **Skeleton load** | shimmer sweep (translateX gradient) | replaces spinners; sized to content (CLS≈0) |
| T13 | **Queen chat** | user msg fly-right, bot msg fly-left + typing dots | dots = 3-phase opacity loop |
| T14 | **Button press** | scale .98 active; primary lifts y:-1 hover | `--d-micro` |
| T15 | **Approve success** | green check burst (scale+fade ring) + card flips to "scheduled" | spring-bouncy; the satisfying moment |

### 7.3 Scroll & ambient
- Sticky vibrant headers; subtle parallax on the showcase hero (disabled on reduced-motion / Save-Data). CSS **scroll-driven animations** (`animation-timeline: view()`) to fade/raise cards as they enter — no JS scroll listeners.
- Showcase-only: the existing animated gradient sweep from `bta-site` (kept, `prefers-reduced-motion`-gated).

### 7.4 Performance rules
- Only `transform`/`opacity` animate in steady state; `will-change` applied transiently then removed. Target **60fps** (120fps on ProMotion). No animation blocks input (INP budget §11). Stagger caps at ~8 items to avoid long tails. `content-visibility:auto` for long lists.

### 7.5 Reduced-motion parity (non-negotiable)
- `@media (prefers-reduced-motion: reduce)`: replace movement with **instant or ≤100ms opacity** changes; disable FLIP translation, hero morphs (instant swap), parallax, shimmer (static placeholder), looped pulses (static colored dot + text). The product is **fully usable and equally legible** with motion off. Wire a global `reducedMotion` store so JS-driven springs also short-circuit.

---

## 8. Component Library

Built as Svelte primitives in `lib/components/`, each delivered with **all states** (idle / hover / focus / active / pending / done / error / empty / skeleton / offline) and **a11y annotations baked in**, so QA verifies each independently.

| Component | Purpose | States / motion | Key a11y |
|---|---|---|---|
| `AppShell` | sidebar/topbar/bottom-tabs, theme, SW reg | route transitions (T1) | landmarks `banner/nav/main`, skip-link |
| `NavItem` | route link | active morph, `aria-current` | real `<a>`, 44px, icon+label |
| `SyncChip` | SSE state: Live/Reconnecting/Offline/Queued(n) | LED pulse (live only) | `aria-live=polite`, text not color-only |
| `CycleMeter` | 0–42 approved+scheduled | spring width (T9) | `role=progressbar` + "28 of 42" |
| `StatCard` | dashboard counts | count-up (T8) | labeled, tabular-nums |
| `AgentCard` | agent status/role/last-action/breaker | status motion (T7) | status = icon+text+color |
| `EventFeedItem` | bus event row | enter fly+fade (T4) | list semantics, time as `<time>` |
| `DraftCard` | poster, category, title, voice, script, actions | hero source (T2), insert/remove (T3) | list item; "Approve {title}" |
| `VideoPlayer` | poster-first, lazy `<video>`, burned-in captions | hero target (T2) | native controls, keyboard, no autoplay-sound |
| `RenderRing` | live progress | spring stroke (T5) | `role=progressbar`, % text |
| `StageStepper` | 6-stage pipeline | active/done motion (T6) | ordered list, current announced |
| `ApproveButton` | idle→pending→scheduled | success burst (T15), optimistic+queued | `aria-busy`, result announced |
| `RejectButton` | idle→pending→"regenerating…" | undo toast | confirm via undo, not dialog |
| `Toast/Undo` | reversible actions | slide (T10) | `role=status`, focusable, 10s |
| `Modal/Sheet` | destructive confirm, detail | scale+blur (T11) | focus-trap, ESC, `aria-modal` |
| `Skeleton` | loading | shimmer (T12) | `aria-hidden`, sized |
| `Segmented` | filters (status/pipeline) | thumb slide | radiogroup, arrow keys |
| `ScheduleChip` | reel in time slot | drag/keyboard reorder | slot announced |
| `QueenChat` | Qwen conversation | msg + typing (T13) | log `aria-live`, labeled input |
| `EmptyState` | no data | fade-in | descriptive + CTA |
| `ErrorState` | failed fetch/media | — | inline + **Retry**, never blank |

---

## 9. UI/UX Specs per View (example states + wireframes)

Unifies the operator surfaces (`dashboard`) with the showcase IA (`bta-site`). Routes: **Dashboard · Render · Drafts · Agents · Trends · Niche · Fact-Check · Review · Queen · Schedule · Settings.**

### 9.1 Dashboard (overview)
```
┌ Reel Studio ───────────  Week 2026-W23 ▾   ◖ 28/42 ◗   ● Live   ☾  ◐ ─┐
│ ▣ Dashboard │  OVERVIEW                                                │
│ ▶ Render    │  ┌Total─┐ ┌Pending┐ ┌Appr─┐ ┌Publ─┐   ← count-up (T8)   │
│ ▦ Drafts    │  │  42  │ │   6   │ │ 28  │ │ 8   │                     │
│ ✦ Agents    │  └──────┘ └───────┘ └─────┘ └─────┘                     │
│ ↗ Trends    │  AI AGENTS (live)        RENDER QUEUE                    │
│ ◎ Niche     │  ┌AgentCard ·pulse┐ …    depth 2 · next ETA 0:28        │
│ ✓ Fact-Check│  RECENT ACTIVITY ──────── (SSE, fly-in T4)              │
│ ⚖ Review    │  • B_312 approved → Wed 09:00   • A_287 → regen         │
│ ♛ Queen     │  • QwenCoder patched media_fetch.py                     │
│ ▤ Schedule  │                                                         │
│ ⚙ Settings  │                                                         │
└─────────────┴─────────────────────────────────────────────────────────┘
```
Live: stat cards count-up on change; agent cards pulse on real status; activity feed streams via SSE.

### 9.2 Render (the hero animated flow)
```
 START PRODUCTION
 ┌ Topic ───────────────────────┐   ┌──────── 9:16 live preview ───────┐
 │ Why the ocean is salty        │   │        ╭─────────────╮            │
 └───────────────────────────────┘   │        │   ◖ 64% ◗   │  ← T5 ring │
 Visual: (Auto) (Stock) (Hybrid)     │        ╰─────────────╯            │
 [ ▶ Start Render ]  ← lift/press    │  Music · subtitles · export       │
 STAGES  ① Script✓ ② TTS✓ ③ Visuals◌ │  frame fades in on first key (T6) │
         ④ Subs ⑤ Music ⑥ Export     └───────────────────────────────────┘
 TIMELINE (SSE)  09:42:01 script done · 09:42:08 tts done · …
```
**Fixes the ring bug:** ring + stepper bind to real `render_stage` SSE events (not the mis-read `events[stage]`). Stage check draws on (T6); ring eases via spring (T5). On done → success burst → "Open in Drafts" (hero T2).

### 9.3 Drafts (fix the dead view + real player)
```
 GENERATED VIDEOS         [All ▾][A|B][pending|approved|published]  ← Segmented
 ┌DraftCard┐ ┌DraftCard┐ ┌DraftCard┐ …   ← keyed grid, FLIP on filter (T3)
 │ 9:16    │ │ 9:16    │   poster-first, lazy video, burned-in caps
 │ poster  │ │ ▶       │   [✓ Approve] [✗ Reject]   approve→burst (T15)
 │ history │ │ science │   tap → hero morph to player (T2)
 └─────────┘ └─────────┘
```
Implement the missing `updateDrafts()` as a `DraftCard` grid bound to the drafts store; approve/reject optimistic + offline-queued (§5.5).

### 9.4 Agents
Grid of `AgentCard`s: name, role, **last action + relative time** (from bus), **next: waits-for**, **circuit breaker** (closed/open icon+text). Running = breathing pulse; healing = amber shimmer; error = one shake then static error chip. Live via SSE `agent_status`.

### 9.5 Trends / Niche / Fact-Check / Review
- **Trends:** table → "Produce" morphs the row into the Render studio (hero) with topic prefilled.
- **Niche:** ranked cards with transparent criteria breakdown; "Run Niche Research" → optimistic running state.
- **Fact-Check:** claims table with verdict badges (supported/uncertain/contradicted) — icon+text+color.
- **Review (QA gate):** reviewer findings; redos **gated** (flag → you approve). Approve-redo / dismiss with undo toast.

### 9.6 Queen (Qwen) chat
Bubble log (user right, bot left), typing dots while awaiting, online/offline header chip. Offline → graceful "start Ollama" hint (backend already returns this). `aria-live` log; Enter to send; Shift+Enter newline.

### 9.7 Schedule (new — realizes blueprint §2.4)
Week grid Mon–Sun × time rows; approved reels = category-colored chips (A/B badge). Drag to reschedule; **keyboard:** focus chip → Enter pick up → arrows move → Enter drop; slot changes announced. Empty slots "⏳ open." Backed by new `/api/schedule`.

### 9.8 Settings (new)
Account/role, theme override, **reduced-motion override**, API base, voices & rotation, music library, API keys & **license log**, distribution targets, Discord sync. Programmatic labels, inline + summarized validation.

---

## 10. Accessibility (WCAG 2.2 AA)

- **Keyboard:** every action operable; visible focus ring ≥ 3:1 (never removed); logical order; roving tabindex in draft grid/carousel; arrow-keys in Schedule; ESC closes overlays; **no traps**.
- **Screen readers:** landmarks (`banner/nav/main/contentinfo`); queue as ordered list with position ("Draft 5 of 21"); approve/reject + sync/offline announced via `aria-live=polite`; player exposes native controls + captions.
- **Captions:** reel subtitles are **burned in** (always visible) → caption presence guaranteed; script text shown on detail as transcript equivalent.
- **Targets & spacing:** ≥ 44×44px; spacing prevents mis-taps (2.5.8).
- **Color & contrast:** never color-alone (category/status carry text+icon); text ≥ 4.5:1, UI/borders ≥ 3:1, verified in **both** themes.
- **Forms:** label-for, inline + summarized errors, instructions before inputs, errors not color-only.
- **Motion/flashing:** honor reduced-motion (§7.5); no flashing > 3×/s (also a ComplianceAgent gate).
- **Resilience:** real `<a>` routes + standard form POST fallback for approve/reject so the basic flow works with JS disabled / after a drop.
- **New 2.2 criteria:** Focus Not Obscured (sticky headers must not cover focused elements — scroll-padding), Dragging Movements (Schedule drag has a keyboard alternative), Target Size, Consistent Help (Queen/help reachable consistently).

---

## 11. Performance Targets & Budgets

| Metric | Target | Notes |
|---|---|---|
| **FCP** (3G, mid mobile) | < 1.8 s | system-font first paint, inlined critical CSS, prerendered shell |
| **LCP** | < 2.5 s | poster (not video) is LCP; `preload="none"` video |
| **INP** | < 200 ms | motion never blocks input; transform/opacity only |
| **CLS** | < 0.1 (≈0) | sized skeletons, explicit media width/height, `aspect-ratio:9/16` |
| **Initial JS** | < 90 KB gz | Svelte runtime + app; route-split; lazy player & Schedule |
| **Frame rate** | 60 fps (120 on ProMotion) | composited animations, capped stagger |
| **TTI without video bytes** | interactive before any reel downloads | poster-first queue |
| **SSE overhead** | 1 stream/client + 15s heartbeat | replaces ~17 polls/min/client |

Budgets enforced in CI (Lighthouse + bundle-size check in `deploy.yml`).

---

## 12. Milestones & Timeline

Phased so value ships continuously and the current UI keeps working until parity. Estimates assume ~1 FE + ~0.5 BE.

| Phase | Theme | Key deliverables | Exit criteria |
|---|---|---|---|
| **P0 — Foundations** (wk 1) | Stand up the app + tokens | SvelteKit + `adapter-static` scaffold; `tokens.css` (light/dark); self-hosted Inter; motion presets; CI bundle/Lighthouse budgets; deploy `web/build` to a Pages preview alongside the old dashboard | New shell deploys; old dashboard untouched; tokens verified ≥ AA both themes |
| **P1 — Real-time core** (wk 2) | SSE + truthful state | `GET /api/stream` on stdlib server; `stream.ts` + polling fallback; live stores; **fix render-ring/stepper bug**; keyed/FLIP lists | Agents pulse on real status; ring advances on real events; no DOM thrash |
| **P2 — Operator parity** (wk 3–4) | Replace operator dashboard | Dashboard, Render (hero flow), Agents, Trends, Niche, Fact-Check, Review, Queen — full motion + a11y + states; **implement Drafts view + VideoPlayer** | Feature-parity with `dashboard/index.html`; old file retired |
| **P3 — Pipeline upgrades** (wk 5–6) | Capability + quality | Quality gates in `quality.py`; ComplianceAgent gate; HookOptimizer/ThumbnailAB agents; distribution retry/backoff + status; `/api/metrics`; persisted agent timeline | Gated autopost; new agents visible & circuit-broken; metrics endpoint live |
| **P4 — Scheduling & auth** (wk 7) | Control + multi-user | Schedule view + `/api/schedule` + SchedulerOptimizer; auth/roles + sessions + audit log; CORS allow-list | Roles enforced; viewer/operator/admin verified; Discord reconciliation |
| **P5 — PWA / offline** (wk 8) | Resilience | Service Worker (shell + SWR data); IndexedDB offline approve/reject queue + Background Sync + idempotency; adaptive media | Approve offline → syncs on reconnect; installable PWA; passes Lighthouse PWA |
| **P6 — Showcase & polish** (wk 9) | Public face + QA | Merge `bta-site` polish into one app (public `viewer` role + offline shell); motion QA pass; reduced-motion audit; a11y audit (axe + manual SR/keyboard) | bta.pages.dev unified; reduced-motion parity; AA sign-off |

**Dependency notes:** P1 unblocks all live motion; P2 can't retire the old file until parity; auth (P4) should land before widening tunnel exposure; PWA (P5) depends on the stable API contract from P1–P4.

---

## 13. Risks & Compatibility Considerations

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Build step vs. "open the HTML" simplicity** | Med | `adapter-static` → pure static; `run.py serve` serves `web/build`; document one `npm run build`; keep old `dashboard/` until P2 exit |
| **View Transitions API support gaps** (older Safari/Firefox) | Med | Progressive enhancement: `onNavigate` no-ops to instant route swap; never a functional dependency |
| **SSE buffered/blocked by proxy or tunnel** | Med | 15s heartbeat; `EventSource` auto-retry; transparent **polling fallback** preserved |
| **`backdrop-filter` unsupported** | Low | Solid-color fallback via `@supports` |
| **Windows cp1252 footgun** in new Python (SSE/auth) | Med | Force `encoding="utf-8"` on all I/O; SSE bytes UTF-8 encoded; covered by `verify_build.py` |
| **Anonymous renders when tunneled** (CORS `*`, empty key) | High (security) | Auth/roles (P4) + CORS allow-list before widening exposure; viewer role is read-only |
| **Motion regressions / jank on low-power devices** | Med | Composited-only animations; reduced-motion + Save-Data downgrades; frame-budget QA on an old Android |
| **Two-UI drift continues during migration** | Med | Freeze `bta-site`/`dashboard` features at P0; all new work in `web/`; unify at P6 |
| **Scope creep (full upgrade is large)** | High | Strict phase exits; each phase independently shippable; P1+P2 alone already replace today's UI |
| **GitHub Pages base-path** for project sites | Low | Set SvelteKit `paths.base`; test both Cloudflare (root) and Pages (subpath) |
| **Discord/web double-action races** | Med | Server is source of truth; idempotency tokens; "updated elsewhere" reconcile notice |

---

## 14. Deliverables Checklist

- [ ] `web/` SvelteKit app (adapter-static), deploying to Cloudflare Pages + GitHub Pages
- [ ] `tokens.css` design-token system (light/dark, motion) + self-hosted Inter
- [ ] `motion.ts` (spring presets, easings, `viewTransition()` helper) + reduced-motion store
- [ ] Component library (§8) with all states + a11y annotations + a living style page
- [ ] SSE endpoint + `stream.ts` client with polling fallback; render-ring/stepper bug fixed
- [ ] Implemented Drafts view + accessible VideoPlayer (poster-first, burned-in captions)
- [ ] Schedule view + `/api/schedule`; auth/roles + sessions + audit log; CORS allow-list
- [ ] Pipeline upgrades: quality gates, ComplianceAgent, Hook/Thumbnail agents, distribution hardening, `/api/metrics`, persisted agent timeline
- [ ] PWA: Service Worker, offline action queue, background sync, idempotency, adaptive media
- [ ] Updated `deploy.yml` (build → publish) with Lighthouse + bundle-size budgets
- [ ] Accessibility audit (axe + manual keyboard/SR) at AA; reduced-motion parity audit
- [ ] Updated docs: this plan + API contract table + `PROJECT_STRUCTURE.md` refresh

---

## 15. Open Questions / Decisions Needed

1. **Framework confirm:** SvelteKit (recommended) vs React+Vite+Motion — confirm before P0 (swap path documented).
2. **Auth model depth:** simple session + 3 roles (proposed) vs. full multi-user accounts with invites?
3. **Low-bitrate proxy renders** for previews on mobile/3G, or stream the final 1080×1920 via range requests only? (Affects ComfyUI/FFmpeg work + §5.5.)
4. **Brand:** lock the exact accent + logo. Current shows two accents (`#0071e3` dashboard, `#4f6df5` bta-site) — pick one system blue (proposed `#007aff`/`#0a84ff`).
5. **Public exposure default:** should `bta.pages.dev` ship a baked-in tunnel API base, or always require `?api=`/login (recommended for safety)?
6. **Stricter a11y/legal standard** beyond WCAG 2.2 AA (e.g., EN 301 549)?

---

*Cross-refs: `docs/UI_BLUEPRINT.md` (IA, offline, a11y foundations realized here), `PROJECT_STRUCTURE.md` (current modules/endpoints), `CLAUDE.md` (architecture patterns), memory `reel-studio-deploy` (hosting/tunnel) & `reel-pipelines-windows-utf8` (cp1252).*
