# Skill: pynab-debugging

# Pynab Debugging

## Overview

Debugging guide for pynab services on Raspberry Pi. Covers common failure patterns, signal handling, PID files, and service communication.

**Announce at start:** "I'm using the pynab-debugging skill to troubleshoot."

---

## Service Architecture

```
nabcore.service (PID: /run/nabcore.pid)
├── nabd (TCP 127.0.0.1:10543)
├── All service daemons (weather, airquality, taichi, surprise, etc.)
└── In-process asyncio.Queue communication

nabweb.service (gunicorn)
├── Django WSGI app
└── Shares SQLite with configd

configd.service (Unix socket)
└── /tmp/pynab-config.sock
```

---

## Common Error Patterns

### 1. `TypeError: 'str' object is not callable` (type shadowing)

**Symptom:** Crash in `NabInfoService.perform` / `perform_additional`

**Cause:** `type` parameter shadows builtin `type()`

**Fix:** Rename parameter to `message_type` in:
- `nabcommon/nabservice.py`
- Subclass overrides (`nabweatherd`, `nabairqualityd`)

**Verify:** `grep -r "def perform.*\btype\b" nab*/` should return nothing

---

### 2. `ProgrammingError: no such column: force_next_performance`

**Symptom:** MQTT triggers fail with SQLite error

**Cause:** `set_async` called with nonexistent column

**Fix:** Remove `force_next_performance` from `set_async` calls in `nabmqttd/nabmqttd.py`

**Verify:** `grep -n "force_next_performance" nabmqttd/nabmqttd.py` should return nothing

---

### 3. Service doesn't restart after code change

**Symptom:** Old code still running after edit

**Cause:** nabweb.service caches Python imports in gunicorn workers

**Fix:**
```bash
sudo systemctl restart nabcore
sudo systemctl restart nabweb
```

**Verify:** `sudo systemctl status nabcore nabweb` shows recent restart

---

### 4. `signal_daemon` PID file not found

**Symptom:** `FileNotFoundError: [Errno 2] No such file or directory: '/run/nabd.pid'`

**Cause:** Services run in-process under nabcore, no separate PID file

**Fix:** `signal_daemon` falls back to `/run/nabcore.pid`

**Verify:** Check `nabcommon/nabservice.py:155-167` has fallback logic

---

### 5. Config not visible to configd

**Symptom:** Web UI changes don't appear in service

**Cause:** gunicorn cached old config in memory

**Fix:** Restart nabweb after Django ORM writes to SQLite

**Verify:**
```python
# Test configd reads from SQLite directly:
sqlite3 /opt/pynab/data/pynab.db "UPDATE nabweatherd SET frequency='15min' WHERE id=1;"
# Then check configd returns updated value:
curl http://localhost/api/config/nabweatherd/
```

---

### 6. Taichi/Surprise "Now" button doesn't trigger

**Symptom:** Click "Now" but nothing happens

**Cause:** `next_performance_date` set to `now` but `compute_next` checks `saved_date < now` — microsecond truncation makes equal timestamps fail

**Fix:** Use `now - timedelta(seconds=1)` (past date)

**Verify:** Check `nabtaichid/views.py:30` and `nabsurprised/views.py:30`

---

### 7. TTS voice ignored

**Symptom:** Always uses default voice, config ignored

**Cause:** `sound.py:66` hardcoded `"voice": "default"` instead of reading config

**Fix:** Read voice from config:
```python
voice = cfg.get("voice", "fr_FR-upmc-medium")
msg = json.dumps({"voice": voice, "text": text})
```

**Verify:** Check `nabd/sound.py:66` reads from config

---

## Signal Handling

### SIGUSR1 (reload config)
- Sent to `nabcore` → propagates to all services
- Sent to individual services if running standalone
- Use: `kill -USR1 $(cat /run/nabcore.pid)`

### PID File Locations
- `nabcore`: `/run/nabcore.pid`
- Services: `/run/<service>.pid` (may not exist if running in-process)
- Always fall back to `/run/nabcore.pid`

---

## Deployment Commands

### Deploy code to Pi
```bash
git push origin fl
ssh pi@Nabaztag.local "cd /opt/pynab && git fetch stan && git checkout fl && git pull stan fl && sudo systemctl restart nabcore && sudo systemctl restart nabweb"
```

### Check service status
```bash
sudo systemctl status nabcore nabweb configd
sudo journalctl -u nabcore -n 50 --no-pager
```

### Test configd
```bash
# Read config
echo '{"id":1,"op":"get","table":"nabweatherd"}' | socat - UNIX-CONNECT:/tmp/pynab-config.sock

# Write config
echo '{"id":1,"op":"set","table":"nabweatherd","data":{"frequency":"15min"}}' | socat - UNIX-CONNECT:/tmp/pynab-config.sock
```

### Test nabd
```bash
# Send command
echo '{"type":"command","command":"ears","args":{"left":10,"right":10}}' | nc -w 1 127.0.0.1 10543
```

---

## Debugging Checklist

1. **Check logs:** `sudo journalctl -u nabcore -n 100 --no-pager`
2. **Check PID files:** `ls -la /run/*.pid`
3. **Check services:** `sudo systemctl status nabcore nabweb configd`
4. **Check config:** `echo '{"id":1,"op":"get","table":"nabweatherd"}' | socat - UNIX-CONNECT:/tmp/pynab-config.sock`
5. **Check SQLite:** `sqlite3 /opt/pynab/data/pynab.db ".tables"`
6. **Check mDNS:** `avahi-browse -a | grep -i nab`
