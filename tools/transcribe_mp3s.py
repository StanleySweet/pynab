"""Batch-transcribe all pynab MP3s with whisper-cpp (Metal on M1).

Resume-safe: saves progress after each batch. Re-run to continue.

Thermal safety: 0.5s cooldown between files + 5s cooldown every 20 files.
This keeps the fanless M1 Air from overheating.

Usage:
  /tmp/whisper_env/bin/python3 tools/transcribe_mp3s.py
"""

import json
import logging
import multiprocessing
import os
import subprocess
import time
from pathlib import Path

PYNAB_ROOT = "/Users/stan/Dev/pynab"
MODEL_PATH = "/Users/stan/Models/whisper/ggml-large-v3-turbo.bin"
OUTPUT = os.path.join(os.path.dirname(__file__), "transcriptions.json")
MIN_SPEECH_DURATION = 0.8
MAX_WORKERS = 1
FILES_PER_SAVE = 10
COOLDOWN_EVERY = 20
COOLDOWN_SECS = 5.0

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

SERVICES = [
    "nabsurprised", "nabweatherd", "nabairqualityd", "nabclockd",
    "nabbookd", "nabmastodond", "nabd", "nab8balld", "nabradio",
]

SKIP_RELPREFIXES = [
    "nabd/sounds/en_US/",
    "nabradio/sounds/fr_FR/nabradio/jingles",
]


def discover_files():
    files = []
    for service in SERVICES:
        sounds = os.path.join(PYNAB_ROOT, service, "sounds")
        if not os.path.isdir(sounds):
            continue
        for root, dirs, fnames in os.walk(sounds):
            parts = Path(root).relative_to(sounds).parts
            locale = parts[0] if (parts and "_" in parts[0]) else ""
            for fn in sorted(fnames):
                if not fn.lower().endswith(".mp3"):
                    continue
                abspath = os.path.join(root, fn)
                relpath = os.path.relpath(abspath, PYNAB_ROOT)
                if any(relpath.startswith(p) for p in SKIP_RELPREFIXES):
                    continue
                files.append((service, locale, relpath, abspath))
    return files


def get_duration(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def lang_for_locale(locale):
    if not locale:
        return None
    return locale.split("_")[0]


# --- Worker process ---
_model = None
_cooldown_counter = 0

def worker_init():
    global _model
    from pywhispercpp.model import Model
    import warnings
    warnings.filterwarnings("ignore")
    _model = Model(MODEL_PATH, n_threads=1)

def transcribe_one(args):
    global _model, _cooldown_counter
    service, locale, relpath, abspath = args
    dur = None
    try:
        dur = get_duration(abspath)
        if dur is not None and dur < MIN_SPEECH_DURATION:
            return service, locale, relpath, None, dur
    except:
        pass

    lang = lang_for_locale(locale)
    if lang:
        try:
            _model._params.language = lang
        except Exception:
            pass

    try:
        segments = _model.transcribe(abspath)
        text = " ".join(s.text.strip() for s in segments if s.text.strip())
        result = (service, locale, relpath, text or None, dur)
    except Exception:
        result = (service, locale, relpath, None, dur)

    # Thermal management
    time.sleep(0.5)
    _cooldown_counter += 1
    if _cooldown_counter >= COOLDOWN_EVERY:
        _cooldown_counter = 0
        time.sleep(COOLDOWN_SECS)

    return result


def save_progress(results, total_all, done_count, elapsed):
    transcribed = sum(
        1 for s in results.values() for l in s.values()
        for e in l.values() if e.get("text")
    )
    short = sum(
        1 for s in results.values() for l in s.values() for e in l.values()
        if e.get("duration") is not None and e["duration"] < MIN_SPEECH_DURATION
    )
    summary = {
        "total": total_all,
        "transcribed": transcribed,
        "skipped_short": short,
        "failed": total_all - transcribed - short,
        "elapsed_seconds": round(elapsed, 1),
    }
    out = {"summary": summary, "services": results}
    tmp = OUTPUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    os.replace(tmp, OUTPUT)
    return summary


def main():
    all_files = discover_files()
    logging.info("Discovered %d MP3 files across %d services", len(all_files), len(SERVICES))

    total_all = len(all_files)

    # Load previous progress
    done_set = set()
    results = {s: {} for s in SERVICES}
    if os.path.exists(OUTPUT):
        with open(OUTPUT) as f:
            prev = json.load(f)
        for svc, locs in prev["services"].items():
            for loc, files in locs.items():
                for relpath in files:
                    done_set.add((svc, loc, relpath))
                results.setdefault(svc, {})[loc] = files
        logging.info("Resuming with %d already-done files", len(done_set))

    todo = [f for f in all_files if (f[0], f[1], f[2]) not in done_set]
    logging.info("Remaining: %d files", len(todo))

    if not todo:
        logging.info("All done!")
        save_progress(results, total_all, total_all, 0)
        return

    done = len(done_set)
    start = time.time()
    if os.path.exists(OUTPUT):
        with open(OUTPUT) as f:
            start = time.time() - json.load(f)["summary"].get("elapsed_seconds", 0)

    mp_ctx = multiprocessing.get_context("spawn")

    try:
        with mp_ctx.Pool(MAX_WORKERS, initializer=worker_init) as pool:
            it = pool.imap_unordered(transcribe_one, todo, chunksize=1)
            for service, locale, relpath, text, dur in it:
                done += 1
                if locale not in results[service]:
                    results[service][locale] = {}
                entry = {"duration": round(dur, 2) if dur else None}
                if text:
                    entry["text"] = text
                results[service][locale][relpath] = entry

                if done % 20 == 0:
                    elapsed = time.time() - start
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (total_all - done) / rate if rate > 0 else 0
                    logging.info(
                        "[%d/%d] %.0f%%  eta=%.0fs  fails=%d",
                        done, total_all, 100 * done / total_all, eta,
                        total_all - done,
                    )

                if done % FILES_PER_SAVE == 0:
                    elapsed = time.time() - start
                    save_progress(results, total_all, done, elapsed)
    except Exception:
        elapsed = time.time() - start
        save_progress(results, total_all, done, elapsed)
        logging.error("Crashed at %d/%d - progress saved", done, total_all)
        raise

    elapsed = time.time() - start
    summary = save_progress(results, total_all, total_all, elapsed)
    files_per_min = summary["transcribed"] / (elapsed / 60) if elapsed > 0 else 0
    logging.info(
        "Done: %d/%d transcribed (%d short, %d failed) in %.1fs (%.0f files/min)",
        summary["transcribed"], summary["total"],
        summary["skipped_short"], summary["failed"], elapsed, files_per_min,
    )


if __name__ == "__main__":
    main()
