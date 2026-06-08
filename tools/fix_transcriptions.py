#!/usr/bin/env python3
"""Fix known-bad Whisper transcriptions in transcriptions.json.

French weather short clips and Italian weather errors where Whisper
misheard single-word audio on very short (<1.3s) clips.
"""
import json
import os

JSON_PATH = os.path.join(os.path.dirname(__file__), "transcriptions.json")

CORRECTIONS = {
    # French weather - sky conditions
    "nabweatherd/fr_FR/sky/sunny.mp3": "ensoleillé",
    "nabweatherd/fr_FR/sky/cloudy.mp3": "nuageux",
    "nabweatherd/fr_FR/sky/showery.mp3": "averses",
    "nabweatherd/fr_FR/sky/foggy.mp3": "brouillard",
    # French weather - degree unit
    "nabweatherd/fr_FR/degree.mp3": "degrés",
    # French weather - negative temps (whisper mishears "moins" as "moi" or "moins en")
    "nabweatherd/fr_FR/temp/-1.mp3": "moins un",
    "nabweatherd/fr_FR/temp/-2.mp3": "moins deux",
    "nabweatherd/fr_FR/temp/-7.mp3": "moins sept",
    "nabweatherd/fr_FR/temp/-9.mp3": "moins neuf",
    "nabweatherd/fr_FR/temp/-12.mp3": "moins douze",
    "nabweatherd/fr_FR/temp/-13.mp3": "moins treize",
    "nabweatherd/fr_FR/temp/-16.mp3": "moins seize",
    "nabweatherd/fr_FR/temp/-17.mp3": "moins dix-sept",
    "nabweatherd/fr_FR/temp/-19.mp3": "moins dix-neuf",
    "nabweatherd/fr_FR/temp/-21.mp3": "moins vingt et un",
    "nabweatherd/fr_FR/temp/-22.mp3": "moins vingt-deux",
    "nabweatherd/fr_FR/temp/-23.mp3": "moins vingt-trois",
    "nabweatherd/fr_FR/temp/-24.mp3": "moins vingt-quatre",
    # Italian weather - sky conditions
    "nabweatherd/it_IT/sky/snowy.mp3": "Neve",
    "nabweatherd/it_IT/sky/foggy.mp3": "Nebbia",
    # Italian weather - number errors
    "nabweatherd/it_IT/temp/-2.mp3": "meno due",
    "nabweatherd/it_IT/temp/6.mp3": "Sei",
    "nabweatherd/it_IT/temp/18.mp3": "Diciotto",
    "nabweatherd/it_IT/temp/33.mp3": "Trentatré",
    "nabweatherd/it_IT/temp/48.mp3": "quarantotto",
}

def main():
    with open(JSON_PATH) as f:
        data = json.load(f)

    fixed = 0
    for key, correct_text in CORRECTIONS.items():
        service, locale, *rest = key.split("/")
        filename = "/".join(rest)
        full_path = f"{service}/sounds/{locale}/{service}/{filename}"
        try:
            entry = data["services"][service][locale][full_path]
            old_text = entry.get("text", "")
            if old_text != correct_text:
                entry["text"] = correct_text
                print(f"FIXED [{service}/{locale}] {filename}: {old_text!r} -> {correct_text!r}")
                fixed += 1
            else:
                print(f"  OK  [{service}/{locale}] {filename}: already correct")
        except KeyError:
            print(f"  ??? [{service}/{locale}] {filename}: not found in transcriptions.json")

    # Fix air quality swapped labels (pt_BR and it_IT)
    # pt_BR: bad.mp3 has good text, good.mp3 has bad text, moderate.mp3 copies bad.mp3
    aq_swaps = {
        ("nabairqualityd", "pt_BR"): {
            "bad.mp3": "Hum, a qualidade do ar não está muito boa hoje. Podemos dizer que está péssima.",
            "good.mp3": "Maravilha! Hoje o ar está fresco e limpo!",
        },
        ("nabairqualityd", "it_IT"): {
            "bad.mp3": "Beh, oggi la qualità dell'aria non è che sia un gran che... anzi, si può dire che faccia proprio schifo.",
            "good.mp3": "Oh che bello, oggi l'aria è pulita!",
        },
    }
    for (service, locale), fixes in aq_swaps.items():
        for filename, correct_text in fixes.items():
            full_path = f"{service}/sounds/{locale}/{service}/{filename}"
            try:
                entry = data["services"][service][locale][full_path]
                old_text = entry.get("text", "")
                if old_text != correct_text:
                    entry["text"] = correct_text
                    print(f"SWAP [{service}/{locale}] {filename}: {old_text!r} -> {correct_text!r}")
                    fixed += 1
                else:
                    print(f"  OK  [{service}/{locale}] {filename}: already correct")
            except KeyError:
                print(f"  ??? [{service}/{locale}] {filename}: not found")

    with open(JSON_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nDone: {fixed} entries fixed")

if __name__ == "__main__":
    main()
