#!/usr/bin/env python
"""Single entrypoint for both reel pipelines.

Examples:
  py run.py a "Why the ocean is salty"        # one Pipeline A reel
  py run.py b "The siege of Constantinople"    # one Pipeline B reel (or "" to auto-pick)
  py run.py batch                              # generate 21 drafts per pipeline (this week)
  py run.py batch --pipeline A --n 5           # 5 drafts for Pipeline A
  py run.py bot                                # run Discord approval bot + scheduler
  py run.py bot --post-now                     # post the weekly review immediately
  py run.py check                              # environment / dependency check
"""
from __future__ import annotations
import argparse, logging, sys
from pathlib import Path


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Automated open-source reel pipelines")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("a"); pa.add_argument("topic")
    pb = sub.add_parser("b"); pb.add_argument("topic", nargs="?", default="")
    pbatch = sub.add_parser("batch")
    pbatch.add_argument("--pipeline", choices=["A", "B"], default=None)
    pbatch.add_argument("--n", type=int, default=None)
    pbot = sub.add_parser("bot"); pbot.add_argument("--post-now", action="store_true")
    pserve = sub.add_parser("serve")
    pserve.add_argument("--port", type=int, default=8787)
    pserve.add_argument("--no-open", action="store_true", help="don't open the browser")
    pval = sub.add_parser("validate")
    pval.add_argument("video", help="rendered MP4 to inspect")
    pval.add_argument("--workflow", help="optional workflow card path")
    sub.add_parser("check")

    args = ap.parse_args()

    if args.cmd == "a":
        from pipelines import pipeline_a
        print(pipeline_a.produce(args.topic))
    elif args.cmd == "b":
        from pipelines import pipeline_b
        print(pipeline_b.produce(args.topic))
    elif args.cmd == "batch":
        from pipelines import batch
        if args.pipeline:
            print(batch.generate_week(args.pipeline, args.n))
        else:
            print(batch.generate_all_weeks())
    elif args.cmd == "bot":
        from pipelines import approval_bot
        sys.argv = ["approval_bot"] + (["--post-now"] if args.post_now else [])
        approval_bot.main()
    elif args.cmd == "serve":
        import threading, webbrowser, shutil
        url = f"http://127.0.0.1:{args.port}"
        if not shutil.which("ffmpeg"):
            print("WARNING: ffmpeg not found on PATH — renders will fail at export.")
            print("  Install: winget install Gyan.FFmpeg  (then restart this shell)")
        if not args.no_open:
            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        print(f"Opening the Studio at {url}  (same-origin: real renders, no mixed-content)")
        import pipelines  # ensure package importable
        import server
        server.main(args.port)
    elif args.cmd == "validate":
        from pipelines.common import quality
        report = quality.validate_export(Path(args.video), Path(args.workflow) if args.workflow else None)
        print(report)
        sys.exit(0 if report["passed"] else 2)
    elif args.cmd == "check":
        import check_env
        check_env.main()


if __name__ == "__main__":
    main()
