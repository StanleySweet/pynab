#!/usr/bin/env python3
"""Re-run Whisper on corrected files to verify transcriptions."""
import json
import os
import time

PYNAB = os.path.dirname(os.path.dirname(__file__))
WHISPER_ENV = "/tmp/whisper_env/bin/python"
MODEL_PATH = "/Users/stan/Models/whisper/ggml-large-v3-turbo.bin"

FIXES = {
    "nabweatherd/fr_FR/sky/sunny.mp3": "ensoleillé",
    "nabweatherd/fr_FR/sky/cloudy.mp3": "nuageux",
    "nabweatherd/fr_FR/sky/showery.mp3": "averses",
    "nabweatherd/fr_FR/degree.mp3": "degrés",
    "nabweatherd/fr_FR/temp/-1.mp3": "moins un",
    "nabweatherd/fr_FR/temp/-2.mp3": "moins deux",
    "nabweatherd/fr_FR/temp/-7.mp3": "moins sept",
    "nabweatherd/fr_FR/temp/-9.mp3": "moins neuf",
    "nabweatherd/fr_FR/temp/-12.mp3": "moins douze",
    "nabweatherd/fr_FR/temp/-13.mp3": "moins treize",
    "nabweatherd/fr_FR/temp/-22.mp3": "moins vingt-deux",
    "nabweatherd/fr_FR/temp/-23.mp3": "moins vingt-trois",
    "nabweatherd/it_IT/sky/snowy.mp3": "Neve",
    "nabweatherd/it_IT/sky/foggy.mp3": "Nebbia",
    "nabweatherd/it_IT/temp/-2.mp3": "meno due",
    "nabweatherd/it_IT/temp/6.mp3": "Sei",
    "nabweatherd/it_IT/temp/18.mp3": "Diciotto",
    "nabweatherd/it_IT/temp/33.mp3": "Trentatré",
    "nabweatherd/it_IT/temp/48.mp3": "quarantotto",
}

TRANSCRIBE_PY = """
import json,sys,time
from pywhispercpp.model import Model
model = Model("%(model)s", n_threads=8)
files = %(files_json)s
results = {}
for lang,fp in files:
    try:
        segs = model.transcribe(fp, language=lang)
        text = " ".join(s.text for s in segs).strip()
        results[fp] = text
    except Exception as e:
        results[fp] = f"ERROR:{e}"
    time.sleep(0.5)
print(json.dumps(results, ensure_ascii=False))
"""

def main():
    # Build file list with language codes
    files = []
    file_paths = []
    for key in sorted(FIXES.keys()):
        parts = key.split("/")
        svc, loc = parts[0], parts[1]
        rel = "/".join(parts[2:])
        lang = "fr" if loc.startswith("fr") else "it"
        fp = os.path.join(PYNAB, svc, "sounds", loc, svc, rel)
        files.append([lang, fp])
        file_paths.append((key, lang, fp))

    py_code = TRANSCRIBE_PY % {
        "model": MODEL_PATH,
        "files_json": json.dumps(files),
    }

    import subprocess
    proc = subprocess.run(
        [WHISPER_ENV, "-c", py_code],
        capture_output=True, text=True, timeout=300,
    )

    if proc.returncode != 0:
        print(f"Whisper error: {proc.stderr}")
        sys.exit(1)

    try:
        results = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        print(f"JSON parse error. stdout:\n{proc.stdout}")
        print(f"stderr:\n{proc.stderr}")
        sys.exit(1)

    # Compare
    match = 0
    mismatch = 0
    for key, correction in sorted(FIXES.items()):
        parts = key.split("/")
        svc, loc = parts[0], parts[1]
        rel = "/".join(parts[2:])
        fp = os.path.join(PYNAB, svc, "sounds", loc, svc, rel)
        whisper_text = results.get(fp, "")
        if whisper_text.lower() == correction.lower():
            status = "MATCH"
            match += 1
        else:
            status = "MISMATCH"
            mismatch += 1
        print(f"{status:9s} | {key:50s} | correction={correction!r:30s} | whisper={whisper_text!r}")

    print(f"\n{match} match, {mismatch} mismatch out of {len(FIXES)}")


if __name__ == "__main__":
    main()
