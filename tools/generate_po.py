#!/usr/bin/env python3
"""Generate .po files from transcriptions.json per service/locale.

Reads the transcription data and maps MP3 filenames to msgids based on
each service's gettext pattern (determined by service code analysis).

Usage: python3 generate_po.py [--dry-run]
"""
import argparse
import json
import os
import sys

JSON_PATH = os.path.join(os.path.dirname(__file__), "transcriptions.json")
PYNAB_DIR = os.path.dirname(os.path.dirname(__file__))

PO_HEADER = r"""# TTS translations from original MP3 recordings.
# Copyright (C) YEAR THE PACKAGE'S COPYRIGHT HOLDER
# This file is distributed under the same license as the PACKAGE package.
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#
msgid ""
msgstr ""
"Project-Id-Version: PACKAGE VERSION\n"
"Report-Msgid-Bugs-To: \n"
"POT-Creation-Date: 2025-01-01 00:00+0000\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"Language: %(lang)s\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"

"""


def get_text(entry):
    if isinstance(entry, dict):
        return entry.get("text", "")
    return ""


# Per-service mapping: MP3 basename -> msgid
# Determined from service code analysis of _() calls
SERVICE_MSGID_MAP = {
    "nabweatherd": {
        "sky/sunny.mp3": "sunny",
        "sky/cloudy.mp3": "cloudy",
        "sky/rainy.mp3": "rainy",
        "sky/snowy.mp3": "snowy",
        "sky/foggy.mp3": "foggy",
        "sky/stormy.mp3": "stormy",
        "today.mp3": "Today",
        "tomorrow.mp3": "Tomorrow",
        "degree.mp3": "degrees Celsius",
        "degree_f.mp3": "degrees Fahrenheit",
    },
    "nabairqualityd": {
        "bad.mp3": "Bad",
        "moderate.mp3": "Moderate",
        "good.mp3": "Good",
    },
    "nab8balld": {
        # 8-ball uses direct text -> no filename mapping needed
        # msgids are the English answer strings
    },
    "nabmastodond": {
        "proposal_received.mp3": "Pairing request received",
        "proposal_refused.mp3": "Pairing request refused",
        "proposal_accepted.mp3": "Pairing request accepted",
        "pairing_cancelled.mp3": "Pairing cancelled",
        "setup.mp3": "Setup",
    },
}

SERVICE_SENTENCE_TEMPLATES = {
    "nabweatherd": {
        "msgid": "%(type)s it will be %(weather)s, %(temp)d %(unit)s.",
        "msgstr_key": None,  # no MP3 -> use same msgid as msgstr for source, empty for target
    },
    "nabairqualityd": {
        "msgid": "The air quality is %(quality)s today.",
    },
    "nabclockd": {
        "msgid": "It is %(hour)d o'clock.",
    },
}

# These services also need TTS entries but don't have direct MP3-to-msgid mapping
# They use _() with the English text as msgid directly
# nabclockd: just the sentence template, hour is int
# nabd: no _() used for TTS
# nabsurprised: uses JSON file, migrating later


def extract_weather_classes(weather_class_value, entries_by_filename):
    """Extract the sky condition transcriptions that map to weather classes.

    The weather service maps MeteoFrance classes to these 6 values:
    sunny, cloudy, rainy, snowy, foggy, stormy.
    """
    sky_files = {}
    for full_path, entry in entries_by_filename.items():
        fname = full_path.rsplit("/", 1)[-1]
        if fname.endswith(".mp3"):
            # Check if it matches a sky/*.mp3 pattern
            parts = full_path.split("/")
            if "sky" in parts:
                sky_idx = parts.index("sky")
                basename = parts[sky_idx + 1].replace(".mp3", "")
                text = get_text(entry)
                if text:
                    sky_files[basename] = text
    return sky_files


def ensure_po_dir(service, locale):
    """Create locale directory if needed, return path."""
    po_dir = os.path.join(PYNAB_DIR, service, "locale", locale, "LC_MESSAGES")
    os.makedirs(po_dir, exist_ok=True)
    return po_dir


def write_po_file(po_path, lang, entries, dry_run=False):
    """Write a .po file with the given msgid->msgstr entries.

    entries: list of (msgid, msgstr) tuples, preserving order.
    """
    lines = [PO_HEADER % {"lang": lang or ""}]
    for msgid, msgstr in entries:
        if not msgid:
            continue
        # Escape quotes
        msgid_esc = msgid.replace('"', '\\"')
        msgstr_esc = msgstr.replace('"', '\\"')
        lines.append(f'msgid "{msgid_esc}"\n')
        lines.append(f'msgstr "{msgstr_esc}"\n\n')

    content = "".join(lines)
    if dry_run:
        print(f"  [DRY RUN] Would write {len(entries)} entries to {po_path}")
        return
    with open(po_path, "w") as f:
        f.write(content)
    print(f"  Wrote {len(entries)} entries to {po_path}")


def _relative_path(full_path, service, locale):
    """Strip service/sounds/locale/service/ prefix to get relative path."""
    prefix = f"{service}/sounds/{locale}/{service}/"
    if full_path.startswith(prefix):
        return full_path[len(prefix):]
    return full_path


def generate_weather_po(service, locale, entries_by_filename, lang, dry_run):
    """Generate .po for weather service. Skips if .po already exists."""
    po_path = os.path.join(ensure_po_dir(service, locale), "django.po")
    if os.path.exists(po_path):
        print(f"  SKIP {po_path} (already exists)")
        return

    msgid_map = SERVICE_MSGID_MAP["nabweatherd"]
    po_entries = []

    for full_path, entry in entries_by_filename.items():
        rel = _relative_path(full_path, service, locale)

        if rel.startswith("sky/"):
            if rel in msgid_map:
                msgid = msgid_map[rel]
            else:
                continue
        elif rel.startswith("temp/"):
            continue
        elif rel in msgid_map:
            msgid = msgid_map[rel]
        else:
            continue

        text = get_text(entry)
        if not text:
            continue
        po_entries.append((msgid, text))

    tmpl = SERVICE_SENTENCE_TEMPLATES[service]
    po_entries.insert(0, (tmpl["msgid"], ""))
    write_po_file(po_path, lang, po_entries, dry_run)


def generate_airquality_po(service, locale, entries_by_filename, lang, dry_run):
    """Generate .po for air quality. Skips if .po already exists."""
    po_path = os.path.join(ensure_po_dir(service, locale), "django.po")
    if os.path.exists(po_path):
        print(f"  SKIP {po_path} (already exists)")
        return

    msgid_map = SERVICE_MSGID_MAP["nabairqualityd"]
    po_entries = []

    for full_path, entry in entries_by_filename.items():
        rel = _relative_path(full_path, service, locale)

        if rel in msgid_map:
            msgid = msgid_map[rel]
            text = get_text(entry)
            if text:
                po_entries.append((msgid, text))

    tmpl = SERVICE_SENTENCE_TEMPLATES[service]
    po_entries.insert(0, (tmpl["msgid"], ""))
    write_po_file(po_path, lang, po_entries, dry_run)


def generate_mastodon_po(service, locale, entries_by_filename, lang, dry_run):
    """Generate .po for mastodon. Skips if .po already exists."""
    po_path = os.path.join(ensure_po_dir(service, locale), "django.po")
    if os.path.exists(po_path):
        print(f"  SKIP {po_path} (already exists)")
        return

    msgid_map = SERVICE_MSGID_MAP["nabmastodond"]
    po_entries = []

    for full_path, entry in entries_by_filename.items():
        rel = _relative_path(full_path, service, locale)

        if rel in msgid_map:
            msgid = msgid_map[rel]
            text = get_text(entry)
            if text:
                po_entries.append((msgid, text))

    write_po_file(po_path, lang, po_entries, dry_run)


def generate_8ball_po(service, locale, entries_by_filename, lang, dry_run):
    """Generate .po for 8-ball service. Uses direct English->translated mapping."""
    po_path = os.path.join(
        PYNAB_DIR, "nab8balld", "locale", locale, "LC_MESSAGES", "django.po"
    )

    # 8-ball mp3 files are named by their English answer text
    # But we can also check if the existing .po already has entries
    # and just add/verify the transcriptions

    # Check if .po already exists
    if os.path.exists(po_path):
        print(f"  SKIP {po_path} (already exists)")
        return

    # Extract English msgids from the mp3 filenames
    # 8-ball files are like: nab8balld/sounds/fr_FR/nab8balld/answers/0.mp3
    # The mapping from index to answer is in the service code
    print(f"  SKIP {po_path} (no automated mapping for 8-ball)")


GENERATORS = {
    "nabweatherd": generate_weather_po,
    "nabairqualityd": generate_airquality_po,
    "nabmastodond": generate_mastodon_po,
    "nab8balld": generate_8ball_po,
}


def main():
    parser = argparse.ArgumentParser(description="Generate .po files from transcriptions.json")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    parser.add_argument("--service", help="Only generate for this service (e.g. nabweatherd)")
    args = parser.parse_args()

    with open(JSON_PATH) as f:
        data = json.load(f)

    services = data["services"]

    for service_name in sorted(services.keys()):
        if args.service and service_name != args.service:
            continue
        if service_name not in GENERATORS:
            continue

        generator = GENERATORS[service_name]
        service_data = services[service_name]

        for locale in sorted(service_data.keys()):
            if not locale:
                continue  # skip empty-locale entries (signatures, etc.)
            entries_by_filename = service_data[locale]

            # Map locale code to language code for .po header
            lang = locale
            print(f"{service_name}/{locale}...")
            try:
                generator(service_name, locale, entries_by_filename, lang, args.dry_run)
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr)

    # Generate clock .po files (simplest - just the sentence template)
    if not args.service or args.service == "nabclockd":
        for locale in sorted(services.get("nabclockd", {}).keys()):
            if not locale:
                continue
            lang = locale
            po_path = os.path.join(
                PYNAB_DIR, "nabclockd", "locale", locale, "LC_MESSAGES", "django.po"
            )
            if os.path.exists(po_path):
                print(f"nabclockd/{locale}: SKIP (already exists)")
                continue
            os.makedirs(os.path.dirname(po_path), exist_ok=True)
            write_po_file(
                po_path, lang,
                [("It is %(hour)d o'clock.", "")],
                args.dry_run,
            )


if __name__ == "__main__":
    main()
