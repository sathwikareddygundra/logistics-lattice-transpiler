"""Turns the Modal training log into dashboard/training.json for dashboard/training.html.

Usage: python3 dashboard/training_status.py [LOG] [--once]
Reads the log every few seconds (default /tmp/train.log) until training finishes.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

OUT = Path(__file__).with_name("training.json")
PROGRESS = re.compile(r"(\d+)/(\d+) \[([\d:]+)<([\d:?]+), *([\d.]+)(s/it|it/s)")
LOSS = re.compile(r"\{'loss': ([\d.]+).*?'epoch': ([\d.]+)\}")
DONE = re.compile(r"\{'train_loss': ([\d.]+), 'seconds': (\d+), 'steps': (\d+)")


def parse(text: str) -> dict:
    text = text.replace("\r", "\n")
    prog = PROGRESS.findall(text)
    losses = [(float(a), float(b)) for a, b in LOSS.findall(text)]
    done = DONE.search(text)
    failed = "Traceback" in text or "Error" in text.split("train_loss")[0][-2000:]
    out: dict = {
        "updated": time.time(),
        "status": "finished"
        if done
        else "failed"
        if failed and not prog
        else "running"
        if prog
        else "starting",
        "losses": [
            {"step": 10 * (i + 1), "loss": loss, "epoch": ep} for i, (loss, ep) in enumerate(losses)
        ],
        "gpu": "A10G",
        "model": "Qwen/Qwen3-4B-Instruct-2507",
    }
    if prog:
        step, total, elapsed, eta, rate, unit = prog[-1]
        out |= {"step": int(step), "total": int(total), "elapsed": elapsed, "eta": eta,
                "sec_per_step": float(rate) if unit == "s/it" else round(1 / float(rate), 2)}  # fmt: skip
    if done:
        out |= {"step": int(done.group(3)), "total": int(done.group(3)), "final_loss": float(done.group(1)),
                "train_seconds": int(done.group(2))}  # fmt: skip
    return out


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    log = Path(args[0] if args else "/tmp/train.log")
    while True:
        state = (
            parse(log.read_text(errors="ignore"))
            if log.exists()
            else {"status": "starting", "updated": time.time(), "losses": []}
        )
        OUT.write_text(json.dumps(state))
        if "--once" in sys.argv or state["status"] in ("finished", "failed"):
            return
        time.sleep(3)


if __name__ == "__main__":
    main()
