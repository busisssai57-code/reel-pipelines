"""Pipeline B — Topic/Anecdote -> Stock-Footage Documentary Reel.

anecdote (qwen) -> script -> ROTATED voice (Kokoro) -> visuals -> FFmpeg edit
-> category-styled subtitles -> topic-matched music -> export.

Visual source is selectable ("auto" | "hunyuan" | "footage"). Under the bus +
Supervisor: tries Hunyuan Video (lip-synced actors) behind a circuit breaker,
self-corrects, then self-heals to Archive.org/Pixabay/Pexels footage (and finally
stock/placeholder stills). Visual-QA validates the export; outcomes feed priors.
"""
from __future__ import annotations
import logging
from pathlib import Path
from .common import (config, db, bus, supervisor, qwen_client, kokoro_tts,
                     whisper_timing, subtitles, music, media_fetch, ffmpeg_build,
                     image_gen, hunyuan_video, workflow_card)

log = logging.getLogger("pipeline_b")
_hunyuan_breaker = supervisor.CircuitBreaker("hunyuan", threshold=2, cooldown=60)


def _footage_visual(spec, work, draft_id, total):
    kws = spec.get("keywords", [spec["title"]])
    clips = media_fetch.fetch_footage(kws, draft_id, want=min(6, max(3, len(kws))))
    if clips:
        return ffmpeg_build.build_visual_from_footage(clips, total, work / "viz")
    log.warning("[B] no footage; falling back to stock/placeholder stills")
    imgs = image_gen.generate_images(kws, work / "img", draft_id)
    return ffmpeg_build.build_visual_from_images(imgs, total, work / "viz")


def _hunyuan_visual(spec, work, draft_id, total, vo, job_id):
    if not hunyuan_video.is_available():
        return None
    kws = spec.get("keywords", [spec["title"]])
    per = max(1.0, total / max(1, len(kws)))
    clips = []
    for kw in kws:
        clip = hunyuan_video.render_actor_shot(
            f"{spec['title']}: {kw}, documentary footage", vo,
            seconds=per, width=540, height=960, job_id=job_id)
        if clip is None:
            return None
        clips.append(Path(clip))
    return ffmpeg_build.build_visual_from_footage(clips, total, work / "viz")


def produce(topic: str = "", draft_id: int | None = None, visual_source: str = "auto",
            job_id: str | None = None) -> dict:
    bus.init()
    log.info("[B] seed=%s source=%s", topic or "(auto anecdote)", visual_source)
    spec = qwen_client.anecdote_script(topic)
    if draft_id is None:
        draft_id = db.add_draft("B", topic or spec["title"], spec["category"],
                                spec["title"], spec["full_script"])

    job_id = bus.new_job("reel_B", {"draft_id": draft_id, "topic": topic,
                                    "visual_source": visual_source}, job_id=job_id)
    job = bus.get_job(job_id)
    bus.set_status(job_id, "running")
    work = config.OUTPUT / f"B_{draft_id}"
    work.mkdir(parents=True, exist_ok=True)

    try:
        # --- TTS with VOICE ROTATION ---
        vo, voice = kokoro_tts.synthesize(spec["full_script"], work / "vo.wav", rotate=True)
        total = ffmpeg_build.probe_duration(vo) or max(2.0, len(spec["full_script"]) / 15.0)

        # --- Visual stage: Hunyuan (self-correct) -> footage/stills (self-heal) ---
        def _execute(_job, attempt=0, **_):
            if visual_source in ("auto", "hunyuan"):
                v = supervisor.guard("hunyuan", _hunyuan_visual, spec, work, draft_id, total,
                                     vo, job_id, breaker=_hunyuan_breaker,
                                     fallback=lambda *a, **k: None)
                if v:
                    return v
                if visual_source == "hunyuan" and attempt < 1:
                    raise RuntimeError("Hunyuan Video produced no clips")
            return _footage_visual(spec, work, draft_id, total)

        visual_stage = supervisor.Stage(
            name="visual", execute=_execute,
            validate=lambda p: (Path(p).exists() and ffmpeg_build.probe_duration(p) > 0.5,
                                "empty/zero-length visual"),
            fallback=lambda _job: _footage_visual(spec, work, draft_id, total),
            max_retries=2)
        visual = supervisor.run_stage(visual_stage, job)

        # --- Category-styled subtitles ---
        words = whisper_timing.transcribe_words(vo, spec["full_script"])
        ass = subtitles.build_ass(words, spec["category"], work / "subs.ass")

        # --- Music + export ---
        track = music.pick_track(spec.get("mood", "documentary"))
        out = config.DRAFTS / f"B_{draft_id}.mp4"
        thumb = config.DRAFTS / f"B_{draft_id}.jpg"
        ffmpeg_build.finalize(visual, vo, ass, track, out, thumb)

        # --- Visual QA (self-heal to footage on failure) ---
        qa_pass, qa_note = _visual_qa(out, total)
        bus.emit(job_id, "visual_qa", "qa_pass" if qa_pass else "qa_fail", qa_note)
        if not qa_pass:
            bus.emit(job_id, "visual_qa", "self_heal", "re-assembling from footage/stills")
            visual = _footage_visual(spec, work, draft_id, total)
            ffmpeg_build.finalize(visual, vo, ass, track, out, thumb)
            qa_pass, qa_note = _visual_qa(out, total)

        db.update_draft(draft_id, video_path=str(out), thumb_path=str(thumb),
                        category=spec["category"], title=spec["title"], status="pending")

        # --- Reproducible workflow card (takeaway #1: ship the assets) ---
        spec["topic"] = topic or spec.get("title")
        try:
            workflow_card.write_card(draft_id, "B", spec, voice=voice,
                                     visual_source=visual_source, video_path=out)
        except Exception as e:
            bus.emit(job_id, "workflow_card", "stage_error", repr(e))

        bus.set_status(job_id, "done", result={"video": str(out)})

        supervisor.record_outcome(
            {"pipeline": "B", "category": spec["category"], "mood": spec.get("mood"),
             "voice": voice, "visual_source": visual_source},
            reward=1.0 if qa_pass else 0.0)

        log.info("[B] done -> %s (voice=%s qa=%s)", out, voice, qa_pass)
        return {"draft_id": draft_id, "video": str(out), "thumb": str(thumb),
                "title": spec["title"], "voice": voice, "category": spec["category"],
                "job_id": job_id, "qa": qa_pass}

    except Exception as e:
        bus.set_status(job_id, "quarantined", error=repr(e))
        bus.emit(job_id, "pipeline_b", "quarantined", repr(e))
        db.update_draft(draft_id, status="failed")
        log.exception("[B] job %s quarantined", job_id)
        raise


def _visual_qa(video: Path, target_dur: float) -> tuple[bool, str]:
    if not Path(video).exists():
        return False, "no output file"
    d = ffmpeg_build.probe_duration(video)
    if d <= 0.5:
        return False, "zero-length output"
    if target_dur and abs(d - target_dur) / target_dur > 0.15:
        return False, f"duration {d:.1f}s off target {target_dur:.1f}s"
    return True, f"ok ({d:.1f}s)"


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    produce(sys.argv[1] if len(sys.argv) > 1 else "")
