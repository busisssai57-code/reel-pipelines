import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/**
 * Static SPA build. adapter-static + fallback => one client-routed app that
 * drops onto Cloudflare Pages / GitHub Pages exactly like the old dashboard/.
 * All data is fetched at runtime from the local Python API (baseUrl override
 * via ?api= / localStorage 'reel.apiBase'), so there is nothing to prerender.
 *
 * GitHub Pages project sites live under a subpath: build with
 *   BASE_PATH=/reel-pipelines npm run build
 * Cloudflare Pages (bta.pages.dev) serves at root, so BASE_PATH stays empty.
 */
/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: 'build',
      assets: 'build',
      fallback: 'index.html',
      precompress: false,
      strict: false
    }),
    paths: {
      base: process.env.BASE_PATH ?? ''
    }
  }
};

export default config;
