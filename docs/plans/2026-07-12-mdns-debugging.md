# mDNS Auto-Discovery + Debugging Skill Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded IP addresses with mDNS auto-discovery and create an opencode debugging skill for pynab.

**Architecture:** Create a helper module that reads the Pi's serial number and returns `nabaztag-<serial>.local`. Update TTS address defaults to use this with env override. Create a debugging skill capturing patterns from this session.

**Tech Stack:** Python, avahi-daemon, opencode skills

---

## File Structure

| File | Purpose |
|------|---------|
| `nabcommon/mDNS.py` | Helper to get Pi's mDNS hostname from serial number |
| `nabttsd/models.py` | TTS model - update default |
| `nabttsd/views.py` | TTS views - update default |
| `nabttsd/migrations/0002_auto_*.py` | Migration to update default |
| `nabd/sound.py` | Sound module - update default |
| `.opencode/skills/pynab-debugging/SKILL.md` | Debugging skill |

---

## Task 1: Create mDNS helper module

**Files:**
- Create: `nabcommon/mDNS.py`

- [ ] **Step 1: Write the mDNS helper**

```python
# nabcommon/mDNS.py
import os
import re


def get_pi_serial() -> str | None:
    """Read Pi serial number from /proc/cpuinfo or device tree."""
    # Try /proc/cpuinfo first (works on older Pi OS)
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    return line.split(":")[1].strip()
    except FileNotFoundError:
        pass
    
    # Try device tree (works on newer Pi OS)
    try:
        with open("/sys/firmware/devicetree/base/serial-number", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        pass
    
    return None


def get_mdns_hostname(prefix: str = "nabaztag") -> str | None:
    """Get mDNS hostname in format prefix-serial.local."""
    serial = get_pi_serial()
    if serial:
        return f"{prefix}-{serial}.local"
    return None


def get_tts_addr(default: str = "pi4.local:8765") -> str:
    """Get TTS address with mDNS auto-discovery and env override.
    
    Priority:
    1. TTS_ADDR environment variable
    2. mDNS auto-discovery (nabaztag-<serial>.local:8765)
    3. Provided default fallback
    """
    # Check env override first
    env_addr = os.environ.get("TTS_ADDR")
    if env_addr:
        return env_addr
    
    # Try mDNS auto-discovery
    mdns_host = get_mdns_hostname()
    if mdns_host:
        return f"{mdns_host}:8765"
    
    # Fallback to default
    return default
```

- [ ] **Step 2: Verify helper works locally**

Run: `python3 -c "from nabcommon.mDNS import get_tts_addr; print(get_tts_addr())"`
Expected: Returns `pi4.local:8765` (local machine has no Pi serial)

- [ ] **Step 3: Commit**

```bash
git add nabcommon/mDNS.py
git commit -m "feat: add mDNS auto-discovery helper for Pi hostname"
```

---

## Task 2: Update TTS address defaults

**Files:**
- Modify: `nabttsd/models.py:10`
- Modify: `nabttsd/views.py:28`
- Modify: `nabd/sound.py:60`

- [ ] **Step 1: Update nabttsd/models.py**

Change line 10 from:
```python
tts_addr = models.CharField(default="pi4.local:8765", max_length=256)
```
To:
```python
from nabcommon.mDNS import get_tts_addr
tts_addr = models.CharField(default=get_tts_addr("pi4.local:8765"), max_length=256)
```

- [ ] **Step 2: Update nabttsd/views.py**

Change line 28 from:
```python
config.tts_addr = request.POST.get("tts_addr", "pi4.local:8765")
```
To:
```python
from nabcommon.mDNS import get_tts_addr
config.tts_addr = request.POST.get("tts_addr", get_tts_addr("pi4.local:8765"))
```

- [ ] **Step 3: Update nabd/sound.py**

Change line 60 from:
```python
cfg.get("tts_addr", "pi4.local:8765")
```
To:
```python
from nabcommon.mDNS import get_tts_addr
cfg.get("tts_addr", get_tts_addr("pi4.local:8765"))
```

- [ ] **Step 4: Run tests**

Run: `pytest nabttsd/tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nabttsd/models.py nabttsd/views.py nabd/sound.py
git commit -m "feat: use mDNS auto-discovery for TTS address default"
```

---

## Task 3: Create pynab-debugging skill

**Files:**
- Create: `.opencode/skills/pynab-debugging/SKILL.md`

- [ ] **Step 1: Create skill directory**

```bash
mkdir -p .opencode/skills/pynab-debugging
```

- [ ] **Step 2: Write the skill**

```markdown
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
git push fl <branch>
ssh pi@nabaztag.local "cd /opt/pynab && git pull && sudo systemctl restart nabcore && sudo systemctl restart nabweb"
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
```

- [ ] **Step 3: Commit**

```bash
git add .opencode/skills/pynab-debugging/SKILL.md
git commit -m "feat: add pynab debugging skill for opencode"
```

---

## Verification

After all tasks:
1. Run existing tests: `pytest nabttsd/tests/ nabd/tests/ -v`
2. Check mDNS helper works on Pi: `python3 -c "from nabcommon.mDNS import get_tts_addr; print(get_tts_addr())"`
3. Verify skill loads in opencode
