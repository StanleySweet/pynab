#!/bin/bash
# -
# Do needed inits, then run nabcore (all services in one process) and nabweb.
set -e

# Do inits
echo "Doing Pynab inits..."
/usr/local/bin/run-inits.sh

# Start nabcore (all service daemons in a single process)
echo "Starting nabcore..."
ln -sf /dev/stdout /var/log/nabcore.log
/opt/venv/bin/python3 -m nabcore.nabcore &
NABCORE_PID=$!

# Start nabweb
echo "Starting nabweb..."
while :
do
    /usr/local/bin/run-webserver.sh &
    wait $!
done
