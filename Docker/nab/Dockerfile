FROM python:3.9-bullseye

RUN apt-get update && apt-get install -y \
    postgresql-client gettext \
    libmpg123-dev libasound2-dev \
    wireless-tools sudo

COPY Docker/nab/*.sh /usr/local/bin/

# Fake systemd-time-wait-sync.service needed by nabclockd
RUN mkdir -p /run/systemd/timesync/ && touch /run/systemd/timesync/synchronized

# Naively fake systemctl, used to check if the SSH service is active
RUN ln -s /bin/false /bin/systemctl

# Make /var/log/ writable for service log files, /run for PID files
RUN chmod a+w /var/log /run

# Set timezone
RUN echo "Europe/Paris" > /etc/timezone
RUN ln -fs /usr/share/zoneinfo/Europe/Paris /etc/localtime

RUN groupadd -g 1000 pi
RUN useradd -u 1000 -g pi -m -s /bin/bash tagtagtag
RUN echo "tagtagtag ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/010_tagtagtag-nopasswd

RUN mkdir -p /opt/pynab /opt/venv
RUN chown tagtagtag:pi /opt/pynab /opt/venv

USER tagtagtag

WORKDIR /opt/pynab

ENV VIRTUAL_ENV=/opt/venv
RUN python3.9 -m venv ${VIRTUAL_ENV}
ENV PATH=${VIRTUAL_ENV}/bin:${PATH}

COPY requirements-runtime.txt /tmp/requirements-runtime.txt
# Remove ASR/NLU/hardware/platform-specific deps not needed in Docker
RUN grep -v -e 'git+https' -e 'snips' -e 'kaldi' -e 'pyalsaaudio' -e 'rpi-ws281x' -e 'RPi.GPIO' -e 'smbus2' -e 'nfc' -e 'ndef' -e 'num2words' -e 'docopt' \
    /tmp/requirements-runtime.txt > /tmp/requirements_docker.txt

RUN ${VIRTUAL_ENV}/bin/pip install wheel
RUN ${VIRTUAL_ENV}/bin/pip install -r /tmp/requirements_docker.txt

ENV NABD_HOST=pynab
ENV NABD_PORT_NUMBER=10543

EXPOSE 8000
EXPOSE 10543
