// Pure client-rendered SPA: data comes from the local API at runtime, so there
// is nothing to server-render or prerender. adapter-static emits the fallback.
export const ssr = false;
export const prerender = false;
