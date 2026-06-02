// Shapes returned by the Python stdlib API (server.py). Kept deliberately loose
// where the backend is loose; these mirror _draft_payload, RUNNER.health(),
// bus.recent_events(), and the /api/health + /api/qwen/status responses.

export interface LastAction {
  type?: string;
  note?: string;
  ts?: number;
}

export interface Agent {
  name: string;
  status?: 'idle' | 'running' | 'healing' | 'error' | string;
  role?: string;
  last_action?: LastAction | null;
  waits_for?: string;
  circuit_open?: boolean;
  score?: number; // outcome score (0..1) from priors; exposed by /api/agents when available
}

export interface Draft {
  id: string;
  pipeline: string;
  pl: string;
  topic: string;
  category: string;
  cat: string;
  title: string;
  script: string;
  status: 'pending' | 'approved' | 'rejected' | 'published' | 'failed' | string;
  scheduled_for: string;
  slot: string;
  video_path: string;
  thumb_path: string;
  video_url: string;
  thumb_url: string;
  voice: string;
}

export interface BusEvent {
  job_id?: string | null;
  agent: string;
  type: string;
  note?: string;
  data?: unknown;
  ts: number;
}

export interface Health {
  ok: boolean;
  hunyuan?: boolean;
  engine?: string;
  ffmpeg?: boolean;
  hunyuan_status?: unknown;
  autopost?: unknown;
}

export interface QwenStatus {
  online: boolean;
  model?: string;
}

export interface RenderEventsResponse {
  job?: { id?: string; kind?: string; status?: string; attempts?: number } | null;
  events?: BusEvent[];
}

export interface Trend {
  topic: string;
  source: string;
  score?: number;
  prior_score?: number;
}
