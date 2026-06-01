# Reel Pipeline — Review & Approval Dashboard
## Cross-Device & Cross-Network UI Blueprint

**Project:** Reel Pipeline Review Dashboard (web companion to the Discord approval loop)
**Target users:** Content reviewer / operator approving the weekly batch (21 drafts × 2 pipelines = 42 reels), plus an admin who monitors the schedule and asset licenses.
**Platform constraints:** Web app, must run on desktop, tablet, mobile, and low-power "edge" devices (old Android, kiosk browsers); usable on offline / slow / intermittent mobile-data networks; backend is the existing Python service + `state.db`.
**Accessibility target:** WCAG 2.2 AA, full keyboard operability, screen-reader support. `[FILL: any stricter legal standard, e.g. EN 301 549]`

> **Conflict-resolution rule (applies throughout):** Constraints/do-nots > required outputs > examples/references > preferences. Where two rules collide, accessibility and offline-resilience win over visual polish.

---

## 1. Information Architecture & Navigation

```
Dashboard (weekly status)
├── Review Queue
│   ├── Pipeline A — Synthetic-Visual  (21 drafts)
│   └── Pipeline B — Stock-Footage     (21 drafts)
├── Schedule (approved reels across the week)
├── Drafts archive (filter: status, category, week)
└── Settings
    ├── Voices & rotation
    ├── Music library
    ├── API keys & licenses log
    └── Discord / notification sync
```

**Primary task flow:** Dashboard → Review Queue (per pipeline) → open draft → Approve (→ auto-schedule) or Reject (→ new proposition generated → re-enters queue) → repeat until cycle complete → Schedule confirms 42 slots filled.

**Navigation pattern by breakpoint**
- **Desktop/tablet-landscape:** persistent left sidebar (icons + labels) + top context bar (week selector, cycle-progress meter, sync status).
- **Mobile/tablet-portrait:** bottom tab bar (Dashboard · Queue · Schedule · More); top bar collapses to title + sync chip.
- **Edge/very-narrow:** bottom tabs become 4 icons only; secondary items move under "More".

Every nav item is a real link (`<a href>`/router link) so it works without JS and is crawlable/restorable after a connection drop. Current location exposed via `aria-current="page"`.

---

## 2. Wireframes (visual descriptions)

### 2.1 Dashboard (desktop)
```
┌────────────────────────────────────────────────────────────────────┐
│ [≡] Reel Pipeline      Week 2026-W23 ▾     ◖ Cycle 28/42 ◗   ● Synced │
├──────────┬─────────────────────────────────────────────────────────┤
│ ▣ Dash   │  WEEKLY REVIEW                                            │
│ ▤ Queue  │  ┌───────────────┐  ┌───────────────┐                    │
│ ▦ Sched  │  │ Pipeline A    │  │ Pipeline B    │                    │
│ ▧ Archive│  │ 14 ✅ 2 ❌ 5 ⏳ │  │ 14 ✅ 1 ❌ 6 ⏳ │                    │
│ ⚙ Settings│  │ [Review →]    │  │ [Review →]    │                    │
│          │  └───────────────┘  └───────────────┘                    │
│          │  Next Monday post: in 3d 4h   ·   Failures: 0             │
│          │  Recent activity ───────────────────────────────────     │
│          │  • B_312 approved → Wed 09:00   • A_287 rejected → regen  │
└──────────┴─────────────────────────────────────────────────────────┘
```

### 2.2 Review Queue + draft card (mobile)
```
┌──────────────────────────┐
│ ‹ Pipeline B   6 left ⏳   │
│ ◖ Cycle 28/42 ◗   ● offline│
├──────────────────────────┤
│ ┌──────────────────────┐ │
│ │  [▶ thumbnail 9:16]  │ │  ← poster image first; tap to stream video
│ │  cat: history        │ │
│ │  "The Library of      │ │
│ │   Timbuktu"           │ │
│ │  voice: bf_emma       │ │
│ │  ▁▁▁ script preview ▁ │ │
│ │ ┌────────┐ ┌────────┐ │ │
│ │ │✅Approve│ │❌Reject │ │ │
│ │ └────────┘ └────────┘ │ │
│ └──────────────────────┘ │
│ (swipe ←/→ between drafts)│
├──────────────────────────┤
│ ▣Dash ▤Queue ▦Sched ⋯More │
└──────────────────────────┘
```

### 2.3 Draft detail / player (any device)
```
┌───────────────────────────────────────┐
│ ‹ Back     B_312 · history · bf_emma   │
│ ┌───────────────┐  Title, topic         │
│ │  9:16 player  │  Script (full)         │
│ │  poster→video │  Music: epic_cinematic │
│ │  captions on  │  Assets & licenses ▾   │
│ └───────────────┘   - pexels  (Pexels L.)│
│  ◀ prev   next ▶    - archive (CC-BY)    │
│ ┌─────────┐ ┌─────────┐ ┌────────────┐  │
│ │✅Approve │ │❌Reject  │ │ ↻ Re-render │  │
│ └─────────┘ └─────────┘ └────────────┘  │
│  Schedule slot (on approve): Wed 09:00  │
└───────────────────────────────────────┘
```

### 2.4 Schedule
```
Week grid: Mon–Sun columns × time rows. Each approved reel = a chip
(color = category, badge = A/B). Drag to reschedule (keyboard: focus chip,
Enter to pick up, arrows to move, Enter to drop). Empty slots show "⏳ open".
```

---

## 3. Component Inventory

| Component | Purpose / states | Key a11y |
|---|---|---|
| **Top app bar** | week selector, cycle-progress meter, sync chip | `role="banner"`; live region on sync change |
| **Side nav / bottom tabs** | primary routes | `nav` landmark, `aria-current`, 44px targets |
| **Cycle-progress meter** | 0–42 approved+scheduled | `role="progressbar"` + text "28 of 42" |
| **Sync status chip** | Synced / Syncing / Offline / Queued(n) | text label, not color-only; `aria-live="polite"` |
| **Pipeline summary card** | counts ✅/❌/⏳, "Review" CTA | heading + descriptive link text |
| **Draft card** | poster, category tag, title, voice, script preview, Approve/Reject | each card a list item; buttons labeled "Approve {title}" |
| **Video player** | poster-first, lazy `<video>`, burned-in captions always visible | native controls, keyboard, captions toggle, no autoplay-with-sound |
| **Approve button** | idle → pending(spinner) → done(scheduled); optimistic, queued offline | `aria-busy`, disabled-after, result announced |
| **Reject button** | idle → pending → "regenerating proposition…" → new card appears | confirm on mobile (undo toast instead of dialog) |
| **Re-render button** | re-runs FFmpeg build for that draft | progress + ETA, cancelable |
| **Category tag** | history/geography/science/default | text + shape, not color-only |
| **Asset/license list** | source + license per asset | `<table>` or definition list, scope headers |
| **Schedule chip** | reel in a time slot, draggable | keyboard reorder, slot announced |
| **Toast / undo** | reversible actions (reject, reschedule) | `role="status"`, 10s dwell, focusable action |
| **Modal** | destructive confirm only (e.g. purge week) | focus-trap, ESC, return focus, `aria-modal` |
| **Empty/skeleton/error states** | per list & player | skeletons not spinners; error has retry |
| **Forms (Settings)** | voices, keys, music | label-for, inline validation, error summary |

**Design tokens (theming):**
```
--space: 4 8 12 16 24 32 48        (8px base scale)
--radius: 6 / 12 / pill
--font: system-ui stack (no web-font fetch on first paint)
--type: 14 / 16 / 20 / 28 (fluid clamp on viewport)
--touch-min: 44px
--color: roles → bg, surface, text, text-muted, accent, success, danger, warning
         category → history #2A4D6E · geography #2F6E4A · science #6E2A2A · default #444
--contrast: all text ≥ 4.5:1; large text & UI borders ≥ 3:1
```
Categories must always pair color with a text label and/or icon shape so they are not color-only signals.

---

## 4. Responsive Rules by Breakpoint

| Token | Range | Layout |
|---|---|---|
| `xs` edge/mobile | ≤ 599px | single column; bottom tabs; one draft card full-width; player full-width 9:16; actions stacked or 2-up |
| `sm` large phone | 600–904px | single column, wider cards; queue 1–2 cards |
| `md` tablet | 905–1239px | left rail collapses to icons; queue 2-up grid; detail = player + meta side-by-side |
| `lg` desktop | 1240–1799px | full sidebar + content; queue 3-up; schedule week-grid full |
| `xl` wide | ≥ 1800px | max content width 1440px centered; queue 4-up |

**Rules**
- Mobile-first CSS; enhancements layered up with `min-width` queries.
- Fluid type/space via `clamp()`; no fixed pixel layouts that overflow at 320px.
- Reel previews keep strict **9:16 aspect-ratio box** (`aspect-ratio:9/16`) at every size to match the 1080×1920 output.
- Grid via CSS Grid `auto-fit, minmax(280px, 1fr)` so card count adapts without breakpoint math.
- Respect `prefers-reduced-motion` (disable swipe/auto transitions, Ken-Burns-style autoplay) and `prefers-color-scheme` (dark/light).
- Orientation-independent: portrait and landscape both usable; no "rotate your device" walls.
- Honor `prefers-reduced-data` / Save-Data header → see §6.

---

## 5. Accessibility (WCAG 2.2 AA)

- **Keyboard:** every action reachable and operable by keyboard; visible focus ring (≥3:1, not removed); logical tab order; roving tabindex within the draft carousel; ESC closes overlays; arrow-key navigation in the schedule grid. No keyboard traps.
- **Screen readers:** semantic landmarks (`banner`, `nav`, `main`, `contentinfo`); queue as an ordered list with position ("Draft 5 of 21"); Approve/Reject results announced via `aria-live="polite"`; sync/offline state announced; player exposes native controls + captions.
- **Captions:** the reel's subtitles are **burned in** (always visible, no toggle needed) — satisfies caption presence regardless of player chrome; also provide the script text on the detail view as an equivalent transcript.
- **Targets & spacing:** interactive targets ≥ 44×44px; adequate spacing to prevent mis-taps (WCAG 2.5.8).
- **Color & contrast:** never rely on color alone (category, status use text/icon too); text ≥ 4.5:1, UI/icon/borders ≥ 3:1; verify in dark and light themes.
- **Forms:** programmatic labels, inline + summarized errors, error text not color-only, instructions before inputs.
- **Motion/flashing:** honor reduced-motion; no content flashes > 3×/sec.
- **Resilience:** functional with JS disabled at a basic level (server-rendered queue + standard form POST for Approve/Reject as a fallback path).
- **Status visibility:** every async action shows pending/success/error state to all users (visual + SR + not-color-only).

---

## 6. Performance & Offline / Low-Bandwidth Optimizations

**Network-adaptive loading**
- **Poster-first, video-on-demand:** lists show a lightweight JPEG poster (`thumb_path`); the `<video>` element is `preload="none"` and only fetches on explicit play. Never autoplay reels in the queue.
- **Adaptive media:** detect `navigator.connection.effectiveType` and `saveData`; on `2g`/`slow-2g`/Save-Data → show poster only, defer video, hide non-critical imagery, fetch lower-bitrate proxy if available.
- **Pagination / virtualization:** render the 21-card queue with windowing; fetch metadata first, media lazily as cards enter the viewport (IntersectionObserver).
- **Range requests:** stream reel previews via HTTP range so seeking/partial play works on flaky links; resume on reconnect.

**Offline & intermittent connectivity**
- **PWA + Service Worker:** app shell + last-fetched queue metadata + posters cached (cache-first for shell, stale-while-revalidate for data) so the reviewer can browse drafts offline.
- **Offline action queue:** Approve/Reject taps while offline are recorded locally (IndexedDB) with optimistic UI ("Queued ⏳"); a Background Sync flushes them to the Python backend on reconnect, then reconciles status. Reject's "new proposition" generation is server-side, so it shows "will generate when online".
- **Conflict handling:** if the same draft was actioned via Discord meanwhile, the server is source of truth; client shows a non-blocking "updated elsewhere" notice and refreshes that card.
- **Idempotency:** Approve/Reject calls carry the draft id + action token so a retried queued action can't double-apply or double-schedule.

**Payload & rendering budget**
- System-font stack (no blocking web-font download); critical CSS inlined; defer non-critical JS.
- Images: responsive `srcset`/`sizes`, modern formats (WebP/AVIF) with JPEG fallback, explicit width/height to avoid layout shift (CLS≈0).
- Skeleton placeholders sized to content; spinners only for short waits.
- Targets: usable First Contentful Paint on 3G; interactive without the video bytes; total initial JS kept small (route-split, lazy player).
- Graceful failure: any failed media/API shows an inline error with **Retry**, never a blank card; matches the backend's "fallbacks degrade gracefully" philosophy.

---

## 7. Implementation Notes (low-friction for developers)

- **Stack-agnostic spec.** Reference build: a component-driven framework (React/Vue/Svelte) + a token-based CSS layer (CSS variables or utility framework), or plain progressive-enhancement HTML — the design tokens (§3) and breakpoints (§4) are the contract.
- **Backend integration:** read `state.db` via a thin Python API (`/drafts?week=&pipeline=&status=`, `/draft/{id}`, `POST /draft/{id}/approve`, `POST /draft/{id}/reject`, `/schedule?week=`, `/assets/{draft_id}`). These mirror the existing `db.py` functions and the `approval_bot.py` actions, so the web UI and Discord loop stay in sync against one source of truth.
- **Parity with Discord:** Approve = `status=approved` + scheduled slot (`_next_slot`); Reject = `status=rejected` + `batch.regenerate_one`. The dashboard is an alternative front-end to the same cycle, not a second system.
- **Deliver components with their states** (idle/pending/done/error/empty/skeleton/offline) and a11y annotations baked in, so QA can verify each independently.

---

### Open placeholders (fill before final sign-off)
- `[FILL: stricter accessibility/legal standard, if any]`
- `[FILL: branding — logo, exact brand palette, font if a brand font is mandated]`
- `[FILL: auth model — single operator vs. multi-user roles/permissions]`
- `[FILL: whether a low-bitrate proxy render is produced for previews, or only the final 1080×1920 MP4]`
