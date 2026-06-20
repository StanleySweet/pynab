# In-Process nabd Communication Design

## Problem

All 13 service daemons communicate with nabd over TCP loopback (port 10543), even though
nabcore now runs everything in a single process. This wastes ~120MB RSS on per-process
interpreter overhead that's already eliminated, but the TCP layer still adds:
- JSON serialization/deserialization at both ends for every packet
- Kernel TCP/IP stack overhead (loopback)
- Unnecessary complexity: the protocol layer is fine, but the transport doesn't need
  to be TCP anymore

## Current Architecture

```
Service ──TCP──→ nabd:  self.writer.write(json.dumps(packet).encode("utf8"))
nabd ──TCP──→ Service:  write_packet(response, writer) → writer.write(...)
```

Each service has `reader`/`writer` (asyncio.StreamReader/StreamWriter). nabd's
`service_writers` dict maps `StreamWriter → List[str]` (events). The `writer` object
serves double duty as both the transport handle for sending responses AND the identity
of the connected service.

## Target Architecture

Replace TCP with two `asyncio.Queue` per service:

```
Service ──Queue──→ nabd:  await self._send_to_nabd({"type": "command", ...})
nabd ──Queue──→ Service:  channel.incoming.put_nowait(packet_dict)
```

## Key Design Decisions

1. **No proxy objects** — clean break from TCP. `client_loop` reads `dict` from
   queue (not JSON bytes from stream). `send_to_nabd` takes `dict` (not bytes).
2. **`ServiceChannel` replaces `StreamWriter` as connection identity** — a dataclass
   holding `incoming: asyncio.Queue` + `events: List[str]`. nabd's `service_writers`
   dict and `interactive_service_writer` become `service_channels` / `interactive_channel`.
3. **Dual-mode TCP + queues during migration** — nabd keeps the TCP `service_loop`
   running alongside new `register_service()` so migrated and non-migrated services
   coexist.

## Changes

### nabd.py

- Add `ServiceChannel` dataclass: `incoming: asyncio.Queue`, `events: List[str]`
- Replace `self.service_writers: Dict[StreamWriter, List[str]]` with `self.service_channels: Dict[ServiceChannel, ServiceChannel]` (identity → self)
- Actually: since `ServiceChannel` contains `events`, just track `Set[ServiceChannel]`
- Or: `service_channels: Dict[int, ServiceChannel]` keyed by service instance id
- Replace `interactive_service_writer: Optional[StreamWriter]` → `interactive_channel: Optional[ServiceChannel]`
- Replace `idle_queue: Deque[Tuple[ServicePacket, StreamWriter]]` → `Deque[Tuple[ServicePacket, ServiceChannel]]`
- Add `register_service(svc: NabService) -> ServiceChannel` — creates a channel, stores it, returns it
- Modify all `process_*_packet(self, packet, writer)` → `process_*_packet(self, packet, channel)`
- Replace `write_packet(response, writer)` → `channel.incoming.put_nowait(response)`
- Keep TCP `service_loop()` for backward compat — translates TCP reader/writer into a `ServiceChannel`

### NabService (nabcommon/nabservice.py)

- Add `_outgoing: asyncio.Queue` (service→nabd) and `_incoming: asyncio.Queue` (nabd→service)
- Add `async def _send_to_nabd(self, packet_dict)` — puts on `_outgoing`
- Add `async def _receive_from_nabd(self) -> dict` — gets from `_incoming`
- Modify `client_loop` — send mode packet via `_send_to_nabd()`, receive loop via `_receive_from_nabd()`
- Modify `send_wakeup` — use `_send_to_nabd({"type": "wakeup"})`
- Keep `self.writer`/`self.reader` as backward-compat attributes (removed in final commit)

### NabInfoService (nabcommon/nabservice.py)

- Modify `perform()` — replace `self.writer.write(info_packet.encode("utf8"))` with
  `await self._send_to_nabd(packet_dict)` using dict construction

### Nabd (nabd.py's `run`/stop methods)

- Remove TCP server creation (in final commit)
- Add method-based registration: `nabd.register_service(svc) → channel`

### Nabcore (nabcore.py)

- `_start_nabd()` — no TCP server; call `self._nabd.register_service(svc)` instead
- `_connect_service()` — create queues, wire to svc and nabd, start tasks
- Cleanup: iterate channels instead of writers

### Service migration (per-service commits)

Each service's `self.writer.write(some_encoded_json_string)` becomes:

```python
# Before
self.writer.write(b'{"type":"command","sequence":[...]}\r\n')
await self.writer.drain()

# After
await self._send_to_nabd({
    "type": "command",
    "sequence": [...],
})
```

Similarly for `self.writer.write(packet.encode("utf8") + b"\r\n")` and
`self.writer.write(packet.encode())`.

`await self.writer.drain()` is no longer needed (queues don't need flow control).

## Migration Order (per service, by complexity)

1. nabtaichid (1 call) — simplest
2. nabradio (2 calls)
3. nabairqualityd (2 calls)
4. nabmqttd (1 call)
5. nabsurprised (1 call)
6. nab8balld (5 calls)
7. nabmastodond (4 calls)
8. nabclockd (6 calls)
9. nabweatherd (7 calls)
10. nabbookd (9 calls)

After all services migrated: remove TCP server, remove `self.writer`/`self.reader` from NabService.

## Backward Compatibility

During migration, nabd's TCP `service_loop` remains active. Non-migrated services
still connect via TCP. Migrated services use queues. Both paths converge at
`process_packet()`.

## Verification

- `python -m flake8` passes after each commit
- All 13 services' event subscription packets are sent on connect
- nabd broadcasts events to both queue-based and TCP-based services
- State transitions and idle queue work identically
