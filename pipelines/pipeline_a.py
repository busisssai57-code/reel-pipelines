"""Pipeline A — Topic -> Synthetic-Visual Reel.

topic -> script (qwen) -> local TTS (Kokoro) -> visuals -> Whisper timestamps
      -> styled subtitles -> matched music -> export.

Visuals come from a selectable source:
  - "hunyuan": Hunyuan Video text-to-video + lip-synced actor shots,
  - "images":  locally generated / stock images (Ken-Burns),
  - "auto":    Hunyuan Video when its backend is available, else images.

Runs under the bus + Supervisor: the visual stage self-corrects/retries and
self-heals to images on failure; a Visual-QA check validates the export and
triggers a heal (re-assemble from images) if the Hunyuan render is unusable.
Outcome scores feed the self-improvement priors.
"""
from __future__ import annotations
import logging
from pathlib import Path
from .common import (config, db, bus, supervisor, qwen_client, kokoro_tts,
                     whisper_timing, subtitles, music, ffmpeg_build, hunyuan_video,
                     workflow_card, quality)
from .common.image_gen import generate_images
from .common.quality import visual_qa as _visual_qa

log = logging.getLogger("pipeline_a")
_hunyuan_breaker = supervisor.CircuitBreaker("hunyuan", threshold=2, cooldown=60)


def _images_visual(spec, work, draft_id, total):
    prompts = [b["image_prompt"] for b in spec["beats"]] or [spec["title"]]
    images = generate_images(prompts, work / "img", draft_id)
    return ffmpeg_build.build_visual_from_images(images, total, work / "viz")


def _hunyuan_visual(spec, work, draft_id, total, vo, job_id):
    """Render one lip-synced actor clip per beat via Hunyuan Video; concat them.
    Returns None if the engine produced nothing (caller falls back to images)."""
    if not hunyuan_video.is_available():
        return None
    beats = spec["beats"] or [{"image_prompt": spec["title"]}]
    per = max(1.0, total / len(beats))
    clips = []
    for i, b in enumerate(beats):
        clip = hunyuan_video.render_actor_shot(
            b.get("image_prompt", spec["title"]), vo,
            seconds=per, width=540, height=960, job_id=job_id)
        if clip is None:
            return None  # bail -> self-heal to images
        clips.append(Path(clip))
    return ffmpeg_build.build_visual_from_footage(clips, total, work / "viz")


def produce(topic: str, draft_id: int | None = None, visual_source: str = "auto",
            job_id: str | None = None) -> dict:
    bus.init()
    log.info("[A] topic=%s source=%s", topic, visual_source)
    spec = quality.autofix_script_spec(qwen_client.script_for_topic(topic), topic)
    script_quality = quality.score_script_spec(spec)
    if draft_id is None:
        draft_id = db.add_draft("A", topic, spec["category"], spec["title"], spec["full_script"])

    job_id = bus.new_job("reel_A", {"draft_id": draft_id, "topic": topic,
                                    "visual_source": visual_source}, job_id=job_id)
    job = bus.get_job(job_id)
    bus.set_status(job_id, "running")
    bus.emit(job_id, "quality", "script_scored", f"score={script_quality['score']}")
    work = config.OUTPUT / f"A_{draft_id}"
    work.mkdir(parents=True, exist_ok=True)

    try:
        # --- TTS (single steady voice for synthetic reels) ---
        vo, voice = kokoro_tts.synthesize(spec["full_script"], work / "vo.wav", rotate=False)
        total = ffmpeg_build.probe_duration(vo) or max(2.0, len(spec["full_script"]) / 15.0)

        # --- Visual stage: Hunyuan Video (self-correct) -> images (self-heal) ---
        def _execute(_job, attempt=0, **_):
            want_hunyuan = visual_source in ("auto", "hunyuan")
            if want_hunyuan:
                v = supervisor.guard("hunyuan", _hunyuan_visual, spec, work, draft_id, total,
                                     vo, job_id, breaker=_hunyuan_breaker,
                                     fallback=lambda *a, **k: None)
                if v:
                    return v
                if visual_source == "hunyuan" and attempt < 1:
                    raise RuntimeError("Hunyuan Video produced no clips")
            return _images_visual(spec, work, draft_id, total)

        visual_stage = supervisor.Stage(
            name="visual", execute=_execute,
            validate=lambda p: (Path(p).exists() and ffmpeg_build.probe_duration(p) > 0.5,
                                "empty/zero-length visual"),
            fallback=lambda _job: _images_visual(spec, work, draft_id, total),
            max_retries=2)
        visual = supervisor.run_stage(visual_stage, job)

        # --- Subtitles ---
        words = whisper_timing.transcribe_words(vo, spec["full_script"])
        ass = subtitles.build_ass(words, spec["category"], work / "subs.ass")

        # --- Music + export ---
        track = music.pick_track(spec.get("mood", "documentary"))
        out = config.DRAFTS / f"A_{draft_id}.mp4"
        thumb = config.DRAFTS / f"A_{draft_id}.jpg"
        ffmpeg_build.finalize(visual, vo, ass, track, out, thumb)

        # --- Visual QA (self-heal): duration must track the voiceover ---
        qa_pass, qa_note = _visual_qa(out, total)
        bus.emit(job_id, "visual_qa", "qa_pass" if qa_pass else "qa_fail", qa_note)
        if not qa_pass:
            bus.emit(job_id, "visual_qa", "self_heal", "re-assembling from images")
            visual = _images_visual(spec, work, draft_id, total)
            ffmpeg_build.finalize(visual, vo, ass, track, out, thumb)
            qa_pass, qa_note = _visual_qa(out, total)

        db.update_draft(draft_id, video_path=str(out), thumb_path=str(thumb),
                        category=spec["category"], title=spec["title"], status="pending")

        # --- Reproducible workflow card (takeaway #1: ship the assets) ---
        spec["topic"] = topic
        try:
            card_path = workflow_card.write_card(draft_id, "A", spec, voice=voice,
                                                 visual_source=visual_source, video_path=out)
        except Exception as e:
            card_path = None
            bus.emit(job_id, "workflow_card", "stage_error", repr(e))

        export_quality = quality.validate_export(out, card_path)
        report_path = quality.write_quality_report(out, script_quality, export_quality)
        bus.emit(job_id, "quality", "export_scored",
                 f"score={export_quality['score']} report={report_path.name}")

        bus.set_status(job_id, "done", result={"video": str(out)})

        # --- Self-improvement: reward usable renders ---
        supervisor.record_outcome(
            {"pipeline": "A", "category": spec["category"], "mood": spec.get("mood"),
             "voice": voice, "visual_source": visual_source},
            reward=1.0 if qa_pass else 0.0)

        log.info("[A] done -> %s (qa=%s)", out, qa_pass)
        return {"draft_id": draft_id, "video": str(out), "thumb": str(thumb),
                "title": spec["title"], "voice": voice, "job_id": job_id, "qa": qa_pass}

    except Exception as e:
        bus.set_status(job_id, "quarantined", error=repr(e))
        bus.emit(job_id, "pipeline_a", "quarantined", repr(e))
        db.update_draft(draft_id, status="failed")
        log.exception("[A] job %s quarantined", job_id)
        raise


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    produce(sys.argv[1] if len(sys.argv) > 1 else "Why the sky is blue")
