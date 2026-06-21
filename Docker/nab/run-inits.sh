#!/bin/bash
# -
# Run the DB migrations, then compile localization messages
set -e

SELF="Init"

echo "${SELF}: running DB model migrations..."
/opt/venv/bin/python3 /opt/pynab/manage.py migrate

echo "${SELF}: updating localization messages..."
all_locales="-l fr_FR -l de_DE -l en_US -l en_GB -l it_IT -l es_ES -l ja_jp -l pt_BR -l de -l en -l es -l fr -l it -l ja -l pt"
/opt/venv/bin/python3 /opt/pynab/manage.py compilemessages ${all_locales}
