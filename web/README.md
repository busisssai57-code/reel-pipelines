# Reel Studio — Web (SvelteKit)

Apple-inspired, motion-first rebuild of the Reel Studio dashboard. Replaces the
two legacy single-file UIs (`../dashboard/index.html` operator + `bta-site`
showcase) with one component app. **Phase 0** of `../docs/UPGRADE_PLAN.md`.

Zero runtime dependencies shipped: SvelteKit compiles to a **static** bundle
(`@sveltejs/adapter-static`) that drops onto Cloudflare Pages / GitHub Pages
exactly like the old `dashboard/`.

## Develop

```bash
npm install
npm run dev      # http://localhost:5173  (proxies /api + /media to 127.0.0.1:8787)
npm run check    # svelte-check (types/a11y)
npm run build    # -> build/  (static)
npm run preview  # serve the production build on :4173
```

Node 18+ required (built/verified on Node 24).

## Backend connection

The app fetches from the Python API (`server.py`). Base URL resolution
(unchanged contract from the old dashboard, so the hosted build keeps working
for a local user):

```
?api=<url>  >  localStorage 'reel.apiBase'  >  legacy 'apiBase'  >  http://127.0.0.1:8787
```

Set a tunnel/remote backend under **Settings → Connection** (or `?api=`).
Transport is polling today; it auto-upgrades to SSE once `GET /api/stream`
lands in Phase 1 (see `src/lib/stream.ts`).

## Deploy (static)

```bash
npm run build
# Cloudflare Pages (bta.pages.dev):
wrangler pages deploy build --project-name=bta --commit-dirty=true
# GitHub Pages project site (served under a subpath):
BASE_PATH=/reel-pipelines npm run build   # then publish build/
```

> Live agent data / renders / Qwen chat still require the **local** Python
> backend + Ollama reachable from the browser — see `../docs/UPGRADE_PLAN.md`
> and the deploy notes. The hosted site shows the animated shell + offline
> states otherwise.

## Structure

```
src/
  lib/
    styles/tokens.css   design tokens (light/dark, motion) + base reset
    styles/util.css     shared utility classes (.panel/.btn/.badge/.grid…)
    motion.ts           spring presets, easings, reduced-motion store
    api.ts              REST client (baseUrl override)
    stream.ts           SSE client + polling fallback (SSE dormant until P1)
    stores/             live (shared poller), prefs (theme), toast
    components/         Icon, Brand, StatCard, SyncChip, AgentTile, SystemVitals,
                        StatusRing, Sparkline, Gauge, EventFeed, DraftCard,
                        ThemeToggle, Skeleton, Placeholder
  routes/               +layout (AppShell) + 11 views
static/                 favicon, manifest, _redirects (CF SPA fallback)
```

## Status

Phase 0 done: shell, design system, motion layer, live Dashboard / Agents /
Drafts / Render / Queen / Trends / Settings; phase placeholders for Niche /
Fact-Check / Review / Schedule. The legacy `../dashboard/` is intentionally
left untouched until this reaches parity (Phase 2).
