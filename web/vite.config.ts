import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 5173,
    // Convenience for local dev: proxy /api and /media to the Python server so
    // the dev app talks to the real backend without CORS gymnastics.
    proxy: {
      '/api': 'http://127.0.0.1:8787',
      '/media': 'http://127.0.0.1:8787'
    }
  }
});
