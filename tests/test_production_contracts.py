from __future__ import annotations

import json
import unittest
from pathlib import Path

from pipelines.common import autopost, db, hunyuan_video


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
        self.assertIn("installed", health)
        self.assertIn("workflow", health["installed"])

    def test_autopost_queues_and_writes_local_manifest(self):
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

    def test_dashboard_contains_live_operability_surfaces(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        required = [
            "/api/drafts",
            "/api/autopost/run",
            "Live agent mesh",
            "Trace stream",
            "agentpulse",
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
