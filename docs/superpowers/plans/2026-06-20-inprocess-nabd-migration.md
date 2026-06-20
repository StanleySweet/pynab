# In-Process nabd Communication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace TCP loopback between service daemons and nabd with in-process asyncio.Queue communication.

**Architecture:** Each service gets `_outgoing`/`_incoming` asyncio.Queue. Nabd replaces `StreamWriter` with `ServiceChannel` (holds `incoming: asyncio.Queue` + `events: List[str]`). `client_loop` reads from `_incoming` queue. All `self.writer.write(...)` → `await self._send_to_nabd(dict)`. TCP server kept for backward compat until all migrated.

**Tech Stack:** Python 3.9+, asyncio, json

---

### Task 1: Infrastructure — nabd ServiceChannel + NabService queue methods + nabcore wiring

**Files:**
- Modify: `nabd/nabd.py`
- Modify: `nabcommon/nabservice.py`
- Modify: `nabcore/nabcore.py`

**Key changes:**
1. **nabd.py**: Add `ServiceChannel` dataclass. Replace `service_writers: Dict[StreamWriter, List[str]]` with `service_channels: Dict[int, ServiceChannel]`. Replace `interactive_service_writer` with `interactive_channel`. Change `IdleQueueItem` writer type. Refactor ALL `process_*_packet` methods to take `channel` instead of `writer`. `write_packet` puts dict on `channel.incoming`. `service_loop` wraps TCP in a `ServiceChannel`. Add `register_service(name, outgoing_queue) → ServiceChannel`.
2. **nabservice.py**: Add `_outgoing`/`_incoming` queues (default None). Add `_send_to_nabd(dict)` / `_receive_from_nabd() → dict`. `client_loop` branches: if queues present, use queue-based packet receive; else TCP. `send_wakeup` similarly. `NabInfoService.perform` branches.
3. **nabcore.py**: `_connect_service` creates queues, calls `nabd.register_service()`, starts client_loop. TCP server kept.

- [ ] **Step 1: Refactor nabd.py — add ServiceChannel, replace all writer→channel, add register_service**

```python
# Add near top:
class ServiceChannel:
    def __init__(self, incoming: asyncio.Queue, name: str = ""):
        self.incoming = incoming
        self.events: List[str] = []
        self.name = name
```

Change `IdleQueueItem = Tuple[ServicePacket, asyncio.StreamWriter]` → `IdleQueueItem = Tuple[ServicePacket, ServiceChannel]`

In `__init__`: replace `service_writers`/`interactive_service_writer` with `service_channels`/`interactive_channel`. Change all method signatures. Add `register_service`. `service_loop` wraps TCP in ServiceChannel + forward task.

- [ ] **Step 2: Refactor nabservice.py — add queue methods, branch client_loop/send_wakeup**

In `NabService.__init__`: add `self._outgoing: Optional[asyncio.Queue] = None`, `self._incoming: Optional[asyncio.Queue] = None`. Add `_send_to_nabd(dict)` / `_receive_from_nabd()`. `client_loop` checks `self._incoming` — if set, reads from queue; else TCP. Same for `send_wakeup`.

- [ ] **Step 3: Refactor NabInfoService.perform** — branch on queue mode

- [ ] **Step 4: Wire nabcore.py** — create queues, register services, no TCP connect

```python
async def _connect_service(self, svc):
    svc._outgoing = asyncio.Queue()
    svc._incoming = asyncio.Queue()
    svc.loop = asyncio.get_event_loop()
    channel = self._nabd.register_service(type(svc).__name__, svc._outgoing)
    svc._svc_channel = channel
    asyncio.create_task(svc.client_loop())
    svc.start_service_loop(asyncio.get_event_loop())
```

- [ ] **Step 5: Run lint and commit**

```bash
python -m ruff check nabd/nabd.py nabcommon/nabservice.py nabcore/nabcore.py
git add -A && git commit -m "refactor: replace TCP with asyncio.Queue-based in-process nabd communication

- Add ServiceChannel to nabd replacing StreamWriter for all service interactions
- Add _send_to_nabd/_receive_from_nabd to NabService base class
- NabService.client_loop supports both queue and TCP modes
- NabService.send_wakeup and NabInfoService.perform branch on queue mode
- nabcore wires services to nabd via queues instead of TCP
- TCP server kept for backward compat during per-service migration"
```

### Task 2: Migrate nabtaichid (1 writer.write call)

**File:** `nabtaichid/nabtaichid.py`

- [ ] **Step 1: Convert writer.write to _send_to_nabd**

Replace:
```python
packet = (
    '{"type":"command",'
    '"sequence":[{"choreography":"nabtaichid/taichi.chor"}],'
    '"expiration":"' + expiration.isoformat() + '"}\r\n'
)
self.writer.write(packet.encode("utf8"))
await self.writer.drain()
```
With:
```python
await self._send_to_nabd({
    "type": "command",
    "sequence": [{"choreography": "nabtaichid/taichi.chor"}],
    "expiration": expiration.isoformat(),
})
```

- [ ] **Step 2: Run lint and commit**

```bash
python -m ruff check nabtaichid/nabtaichid.py
git add -A && git commit -m "refactor(nabtaichid): migrate writer.write to _send_to_nabd"
```

### Task 3: Migrate nabradio (2 writer.write calls)

**File:** `nabradio/nabradio.py`

- [ ] **Step 1: Convert _launch_radio**

Replace:
```python
packet = (
    f'{{"type":"message",'
    f'"request_id":"nabradio",'
    f'"signature":{{"audio":["nabradio/*.mp3"]}},'
    f'"body":[{{"audio":["{streaming_url}"]}}],'
    f'"expiration":"{expiration.isoformat()}"}}\r\n'
)
self.writer.write(packet.encode("utf8"))
await self.writer.drain()
```
With:
```python
await self._send_to_nabd({
    "type": "message",
    "request_id": "nabradio",
    "signature": {"audio": ["nabradio/*.mp3"]},
    "body": [{"audio": [streaming_url]}],
    "expiration": expiration.isoformat(),
})
```

- [ ] **Step 2: Convert _stop_radio**

Replace `'{"type":"cancel","request_id":"nabradio"}\r\n'` with:
```python
await self._send_to_nabd({"type": "cancel", "request_id": "nabradio"})
```

- [ ] **Step 3: Run lint and commit**

### Task 4: Migrate nabairqualityd (2 writer.write calls)

**File:** `nabairqualityd/nabairqualityd.py`

- [ ] **Step 1: Convert perform_additional — no-data-error branch**

Replace string + writer.write with `_send_to_nabd(dict)`

- [ ] **Step 2: Convert perform_additional — today branch**

Same pattern.

- [ ] **Step 3: Run lint and commit**

```bash
python -m ruff check nabairqualityd/nabairqualityd.py
git add -A && git commit -m "refactor(nabairqualityd): migrate writer.write to _send_to_nabd"
```

### Task 5: Migrate nabsurprised (1 writer.write call)

**File:** `nabsurprised/nabsurprised.py`

- [ ] **Step 1: Convert perform**

Replace the f-string packet construction + writer.write with `_send_to_nabd(dict)`.

- [ ] **Step 2: Run lint and commit**

### Task 6: Migrate nabmqttd (1 writer.write call + rename existing _send_to_nabd)

**File:** `nabmqttd/nabmqttd.py`

nabmqttd already has a `_send_to_nabd` method (takes string, writes to TCP). This conflicts with the new base class `_send_to_nabd` (takes dict). Rename the existing one and update ALL 10 callers.

- [ ] **Step 1: Rename existing method + update all callers**

Rename method (line 381):
```python
async def _write_to_nabd(self, payload: str):
    if self.writer is None:
        return
    try:
        self.writer.write((payload + "\r\n").encode("utf-8"))
        await self.writer.drain()
    except Exception as e:
        logging.error(f"Failed to send to nabd: {e}")
```

Update all 9 callers (lines 270, 286, 301, 305, 330, 335, 378, 448, 453): replace `self._send_to_nabd(` with `self._write_to_nabd(`.

```python
# Lines 269-274, 285-289:
asyncio.run_coroutine_threadsafe(
    self._write_to_nabd(json.dumps({"type": "ears", "left": pos})),
    loop,
)
# Lines 300-305:
self._write_to_nabd(json.dumps({"type": "sleep"})), loop
# Lines 304-305:
self._write_to_nabd(json.dumps({"type": "wakeup"})), loop
# Lines 329-330:
self._write_to_nabd(json.dumps({"type": "mode", "mode": mode})),
# Lines 334-335:
self._write_to_nabd(payload), loop
# Lines 377-378:
self._write_to_nabd(packet), loop
# Lines 447-448:
await self._write_to_nabd(packet)
# Lines 452-453:
await self._write_to_nabd(packet)
```

- [ ] **Step 2: Run lint and commit**

### Task 7: Migrate nab8balld (5 writer.write calls)

**File:** `nab8balld/nab8balld.py`

- [ ] **Step 1: Convert setup_listener (2 packets)**

Replace both string packets with `_send_to_nabd(dict)`.

- [ ] **Step 2: Convert perform (1 packet)**

- [ ] **Step 3: Convert enter_interactive (1 packet)**

- [ ] **Step 4: Convert entered_interactive (1 packet)**

- [ ] **Step 5: Run lint and commit**

### Task 8: Migrate nabmastodond (4 writer.write calls)

**File:** `nabmastodond/nabmastodond.py`

- [ ] **Step 1: Convert send_start_listening_to_ears and send_stop_listening_to_ears**

```python
await self._send_to_nabd({"type": "mode", "mode": "idle", "events": ["ears"]})
await self._send_to_nabd({"type": "mode", "mode": "idle", "events": []})
```

- [ ] **Step 2: Convert send_ears**

```python
await self._send_to_nabd({"type": "ears", "left": left_ear, "right": right_ear})
```

- [ ] **Step 3: Convert send_toast_packet_string**

Find the `self.writer.write(packet.encode("utf8"))` in the toast/setup/error branch and convert.

- [ ] **Step 4: Run lint and commit**

### Task 9: Migrate nabclockd (6 writer.write calls)

**File:** `nabclockd/nabclockd.py`

Two patterns: byte literals and string-format packets.

- [ ] **Step 1: Convert byte literal writes**

Replace `self.writer.write(b'{"type":"sleep"}\r\n')` → `await self._send_to_nabd({"type": "sleep"})` (2 occurrences)
Replace `self.writer.write(b'{"type":"wakeup"}\r\n')` → `await self._send_to_nabd({"type": "wakeup"})` (1 occurrence)

- [ ] **Step 2: Convert string-format packets**

Replace the sleep_sound and wakeup_sound packet constructions (2 occurrences).

- [ ] **Step 3: Run lint and commit**

### Task 10: Migrate nabweatherd (7 writer.write calls)

**File:** `nabweatherd/nabweatherd.py`

- [ ] **Step 1-7: Convert each writer.write in perform_additional and set_info_animation**

Each follows the same pattern: `json.dumps(dict)` → `self.writer.write(packet.encode + b"\r\n")`. Replace with `self._send_to_nabd(dict)`.

- [ ] **Step 8: Run lint and commit**

### Task 11: Migrate nabbookd (9 writer.write calls)

**File:** `nabbookd/nabbookd.py`

- [ ] **Step 1-9: Convert each writer.write call**

Most use `.encode()` (no "utf8" arg — defaults to utf8 anyway). Same pattern: convert to dict + `_send_to_nabd`.

- [ ] **Step 10: Run lint and commit**

### Task 12: Remove TCP backward compat + self.writer/self.reader

**Files:**
- Modify: `nabd/nabd.py`
- Modify: `nabcommon/nabservice.py`
- Modify: `nabcore/nabcore.py`

- [ ] **Step 1: Remove TCP server from nabd.run() and nabcore._start_nabd()**

- [ ] **Step 2: Remove self.writer/self.reader attributes from NabService.__init__**

- [ ] **Step 3: Remove TCP branches from client_loop, send_wakeup, NabInfoService.perform**

- [ ] **Step 4: Remove service_loop TCP handler from nabd (or keep as debugging tool behind flag)**

- [ ] **Step 5: Run lint and commit**

```bash
python -m ruff check nabd/ nabcommon/ nabcore/ nabtaichid/ nabradio/ nabairqualityd/ nabsurprised/ nabmqttd/ nab8balld/ nabmastodond/ nabclockd/ nabweatherd/ nabbookd/
git add -A && git commit -m "refactor: remove TCP backward compat, self.writer, self.reader

- Remove TCP server from nabd (all services use queues now)
- Remove self.writer and self.reader from NabService base class
- Remove TCP branches from client_loop, send_wakeup, NabInfoService.perform"
```
