from __future__ import annotations

import json
import threading
import tempfile
import urllib.request
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

from pipelines.common import autopost, config, db, ffmpeg_build, hunyuan_video, media_fetch, music, quality
import server


ROOT = Path(__file__).resolve().parents[1]


class ProductionContracts(unittest.TestCase):
    def tearDown(self):
        autopost.init()
        with db.conn() as c:
            c.execute("DELETE FROM publish_jobs WHERE draft_id IN (SELECT id FROM drafts WHERE topic LIKE 'test:%')")
            c.execute("DELETE FROM drafts WHERE topic LIKE 'test:%'")

    def test_hunyuan_health_contract_is_machine_readable(self):
        health = hunyuan_video.health()
        self.assertEqual(health["engine"], "Hunyuan Video")
        self.assertIn("available", health)
        self.assertIn("models_ready", health)
        self.assertIn("installed", health)
        self.assertIn("min_bytes", health)
        self.assertIn("workflow", health["installed"])

    def test_quality_autofix_produces_shippable_script_contract(self):
        spec = quality.autofix_script_spec({"title": "rocks", "beats": [
            {"text": "Rocks are interesting.", "image_prompt": "macro rock"}
        ]}, "rocks")
        report = quality.score_script_spec(spec)
        self.assertTrue(report["checks"]["hook_first_8_words"])
        self.assertTrue(report["checks"]["title_power"])
        self.assertTrue(report["checks"]["beat_count"])
        self.assertTrue(report["checks"]["visual_prompts"])
        self.assertGreaterEqual(report["word_count"], 75)

    def test_quality_autofix_places_hook_in_opening_words(self):
        spec = quality.autofix_script_spec({"title": "ancient roads", "full_script": (
            "In the deserts of Mali, a city once held thousands of manuscripts on astronomy, law, and medicine. "
            "Scholars traveled for months to reach its libraries. "
            "When danger came, families hid the books in the sand to save them."
        )}, "ancient roads")
        report = quality.score_script_spec(spec)
        self.assertTrue(report["checks"]["hook_first_8_words"])

    def test_finalize_mixes_generated_music_with_voice(self):
        if not (Path(config.FFMPEG).exists() and Path(config.FFPROBE).exists()):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            visual = work / "visual.mp4"
            vo = work / "vo.wav"
            ass = work / "subs.ass"
            out = work / "out.mp4"
            ffmpeg_build._run([
                "-f", "lavfi", "-i", f"color=c=black:s={config.WIDTH}x{config.HEIGHT}:d=1",
                "-c:v", config.VIDEO_CODEC, "-pix_fmt", "yuv420p", visual,
            ])
            ffmpeg_build._run([
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=48000",
                vo,
            ])
            ass.write_text(
                "[Script Info]\nScriptType: v4.00+\n"
                f"PlayResX: {config.WIDTH}\nPlayResY: {config.HEIGHT}\n\n"
                "[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Main,Arial,64,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,2,2,80,80,220,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.00,Main,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            track = music.pick_track("epic")
            self.assertIsNotNone(track)
            ffmpeg_build.finalize(visual, vo, ass, track, out)
            self.assertTrue(out.exists())
            self.assertGreater(ffmpeg_build.probe_duration(out), 0.5)

    def test_dashboard_supports_head_requests(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            port = httpd.server_address[1]
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("text/html", resp.headers.get("Content-Type", ""))
                self.assertGreater(int(resp.headers.get("Content-Length", "0")), 1000)
        finally:
            httpd.shutdown()
            thread.join(timeout=5)
            httpd.server_close()

    def test_media_fetch_respects_provider_budget(self):
        old_budget = media_fetch.PROVIDER_BUDGET_SECONDS
        try:
            media_fetch.PROVIDER_BUDGET_SECONDS = -1
            clips = media_fetch.fetch_footage(["slow provider"], draft_id=0, want=1)
            self.assertEqual(clips, [])
        finally:
            media_fetch.PROVIDER_BUDGET_SECONDS = old_budget

    def test_archive_media_is_opt_in_for_offline_default(self):
        self.assertFalse(config.ARCHIVE_MEDIA_ENABLED)
        self.assertEqual(media_fetch.archive_videos("public domain road", rows=1), [])

    def test_autopost_queues_and_writes_local_manifest(self):
        old_logs = config.LOGS
        try:
            with tempfile.TemporaryDirectory() as td:
                config.LOGS = Path(td)
                db.init()
                draft_id = db.add_draft(
                    "A",
                    "test: autopost",
                    "science",
                    "Autopost contract",
                    "A short script for the publish queue.",
                )
                db.update_draft(draft_id, status="approved", scheduled_for="")
                job_id = autopost.queue_draft(draft_id, provider="local_manifest")
                self.assertIsInstance(job_id, int)
                result = autopost.run_once(limit=1)
                self.assertEqual(result["processed"], 1)
                draft = db.get_draft(draft_id)
                self.assertEqual(draft["status"], "published")
                self.assertTrue((config.LOGS / "autopost-manifest.jsonl").exists())
        finally:
            config.LOGS = old_logs

    def test_dashboard_contains_live_operability_surfaces(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        # Structural surfaces (endpoints + DOM ids) the live dashboard must wire,
        # kept resilient to UI copy changes: the drafts list, the live agent-status
        # mesh, and the real-time event/trace stream feed.
        required = [
            "/api/drafts",
            "/api/agents",
            "/api/events",
            "eventStream",
        ]
        missing = [token for token in required if token not in html]
        self.assertEqual(missing, [])

    def test_hunyuan_workflow_template_is_valid_after_substitution(self):
        workflow = hunyuan_video._build_workflow(
            "test prompt",
            frames=8,
            fps=8,
            w=256,
            h=448,
            seed=123,
            steps=4,
        )
        self.assertIsInstance(workflow, dict)
        self.assertIn("VHS_VideoCombine", json.dumps(workflow))


if __name__ == "__main__":
    unittest.main()
