# Reel Studio Deployment Guide

## Local Deployment

The dashboard runs on your local machine at **http://127.0.0.1:8787**

```powershell
# Start the server
py run.py serve

# Then open in browser:
# http://127.0.0.1:8787
```

---

## GitHub Pages Deployment (bta.pages.dev)

The dashboard HTML/CSS/JS can be deployed to GitHub Pages for remote access.

### Setup (One-time)

1. **Enable GitHub Pages in repository settings:**
   - Go to Settings → Pages
   - Under "Build and deployment":
     - Source: GitHub Actions
     - Save

2. **Configure custom domain (optional):**
   - In Settings → Pages → Custom domain: `bta.pages.dev`
   - Add DNS CNAME record pointing to `<username>.github.io`

### Automatic Deployment

The workflow in `.github/workflows/deploy.yml` automatically:
- Deploys the `dashboard/` directory to GitHub Pages on every push to `main`
- Makes it accessible at `https://bta.pages.dev` (or your GitHub Pages URL)

### API Configuration for Remote Access

When accessing the dashboard from **https://bta.pages.dev**, you have two options:

#### Option 1: Direct Local API (Recommended for Testing)
The dashboard auto-detects local API at `http://127.0.0.1:8787` and falls back to mock data if unavailable.

**Requirements:**
- Server running locally on port 8787
- Browser allows localhost access (may require CORS configuration)

#### Option 2: Proxied API (Production)
Point the dashboard to a public API endpoint:

Edit the dashboard's `detect()` function to use your production endpoint:

```javascript
async function detect() {
  try {
    const r = await fetch('https://api.yourdomain.com/api/health');
    // ... rest of detection logic
  } catch (e) {}
  return false;
}
```

Or set an environment variable during build:

```bash
API_URL=https://api.yourdomain.com npm run build
```

#### Option 3: Browser-Based Local Tunnel
Use a service like Cloudflare Tunnel to expose your local server:

```bash
# Install cloudflare-tunnel
npm install -g @cloudflare/wrangler

# Create tunnel
wrangler tunnel create reel-studio

# Route tunnel to local server
wrangler tunnel route create http://127.0.0.1:8787 reel-studio.yourdomain.com
```

---

## Deployment Status

### Current Setup
- ✅ Dashboard deployed to GitHub Pages
- ✅ CORS headers enabled on API server
- ✅ All buttons fully functional
- ✅ Real-time event polling active
- ✅ Mock data fallback included

### GitHub Pages URL
```
https://bta.pages.dev
```

### Local API
```
http://127.0.0.1:8787
```

---

## Button Functionality

All dashboard buttons are fully functional:

| Button | Action | API Endpoint |
|--------|--------|--------------|
| Approve | Mark draft approved, schedule publish | POST `/api/drafts/{id}/approve` |
| Reject | Mark rejected, trigger regeneration | POST `/api/drafts/{id}/reject` |
| Start Render | Begin new reel generation | POST `/api/render` |
| Save (Settings) | Persist configuration | POST `/api/settings` |
| Test Connection | Verify backend health | GET `/api/health` |
| Refresh | Reload all data | GET `/api/*` |

---

## Testing Remote Access

To test the dashboard from a remote location:

```bash
# 1. Start local server
cd D:\reel-pipelines
py run.py serve

# 2. In another terminal, open the remote URL
# https://bta.pages.dev

# 3. Dashboard will try to reach:
# http://127.0.0.1:8787/api/health

# 4. If inaccessible from remote, will use mock data
```

---

## Troubleshooting

### Dashboard loads but buttons don't work
- Check browser console for CORS errors
- Verify server is running: `curl http://127.0.0.1:8787/api/health`
- Ensure API_KEY is set if `REEL_API_KEY` is configured

### GitHub Pages not updating
- Check `.github/workflows/deploy.yml` is present
- Verify GitHub Pages is enabled in Settings
- Wait 2-3 minutes after push; check Actions tab for workflow status

### API calls from remote fail
- This is expected when accessing GitHub Pages from external network
- Use Option 3 (tunnel) or deploy your API server publicly
- Dashboard has built-in fallback to mock data
