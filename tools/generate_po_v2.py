#!/usr/bin/env python3
"""Generate .po files for nabsurprised and nab8balld missing locales."""
import json
import os

PYNAB = os.path.dirname(os.path.dirname(__file__))


PO_HEADER = """# TTS translations from original MP3 recordings.
# Copyright (C) YEAR THE PACKAGE'S COPYRIGHT HOLDER
# This file is distributed under the same license as the PACKAGE package.
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#
msgid ""
msgstr ""
"Project-Id-Version: PACKAGE VERSION\\n"
"Report-Msgid-Bugs-To: \\n"
"POT-Creation-Date: 2025-01-01 00:00+0000\\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"
"Language-Team: LANGUAGE <LL@li.org>\\n"
"Language: %(lang)s\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"

"""


def write_po(path, lang, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [PO_HEADER % {"lang": lang}]
    for msgid, msgstr in entries:
        msgid_e = msgid.replace('"', '\\"')
        msgstr_e = msgstr.replace('"', '\\"')
        lines.append(f'#: tts\nmsgid "{msgid_e}"\nmsgstr "{msgstr_e}"\n\n')
    with open(path, "w") as f:
        f.write("".join(lines))
    print(f"  Wrote {len(entries)} entries to {path}")


def generate_nabsurprised():
    print("=== nabsurprised ===")
    # Read answers_text.json
    answers_path = os.path.join(PYNAB, "nabsurprised", "answers_text.json")
    with open(answers_path) as f:
        answers = json.load(f)

    locales = ["fr_FR", "en_US", "en_GB", "de_DE", "es_ES", "it_IT", "ja_JP", "pt_BR"]

    for locale in locales:
        locale_data = answers.get(locale, {})
        po_dir = os.path.join(PYNAB, "nabsurprised", "locale", locale, "LC_MESSAGES")
        po_path = os.path.join(po_dir, "django.po")

        # Read existing .po if it exists (preserve UI translations), or start fresh
        existing_lines = []
        seen_tts = set()
        if os.path.exists(po_path):
            with open(po_path) as f:
                existing_lines = f.readlines()
            # Find existing TTS entries to avoid duplicating
            i = 0
            while i < len(existing_lines):
                if existing_lines[i].startswith("#: tts"):
                    # Skip this entry
                    # Find the msgid line and msgstr line
                    msgid_line = existing_lines[i+1] if i+1 < len(existing_lines) else ""
                    if msgid_line.startswith("msgid "):
                        msgid = msgid_line.split('"')[1]
                        seen_tts.add(msgid)
                    i += 4  # skip comment/msgid/msgstr/blank
                else:
                    i += 1

        # Build TTS entries
        po_entries = []
        for type_name in ["surprise", "carrot", "birthday", "autopromo", "02-14"]:
            texts = locale_data.get(type_name, [])
            if not texts and locale == "fr_FR":
                # fallback for fr_FR - shouldn't happen
                continue
            if not texts:
                # For non-FR locales, use "Surprise!" as default for surprise type
                if type_name == "surprise":
                    # Check if locale has ANY text at all, else skip
                    if not locale_data:
                        continue
                    texts = ["Surprise!"]
                else:
                    continue
            for i, text in enumerate(texts):
                msgid = f"SURPRISE_{type_name}_{i}"
                if msgid in seen_tts:
                    continue
                po_entries.append((msgid, text))

        if not existing_lines:
            # New .po file
            write_po(po_path, locale, po_entries)
        elif po_entries:
            # Append to existing .po
            with open(po_path, "a") as f:
                for msgid, msgstr in po_entries:
                    msgid_e = msgid.replace('"', '\\"')
                    msgstr_e = msgstr.replace('"', '\\"')
                    f.write(f'#: tts\nmsgid "{msgid_e}"\nmsgstr "{msgstr_e}"\n\n')
            print(f"  Added {len(po_entries)} TTS entries to {po_path}")
        else:
            print(f"  {po_path}: no new TTS entries needed")


if __name__ == "__main__":
    generate_nabsurprised()
