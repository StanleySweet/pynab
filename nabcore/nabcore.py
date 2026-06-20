import asyncio
import getopt
import logging
import signal
import sys
import traceback

from lockfile import AlreadyLocked, LockFailed
from lockfile.pidlockfile import PIDLockFile

from nabcommon import nablogging
from nabcommon.nabservice import NabRecurrentService, NabService


_SERVICE_CLASSES = None


def _import_services():
    global _SERVICE_CLASSES
    if _SERVICE_CLASSES is not None:
        return _SERVICE_CLASSES
    from nab8balld.nab8balld import Nab8Balld
    from nabairqualityd.nabairqualityd import NabAirqualityd
    from nabbookd.nabbookd import NabBookd
    from nabclockd.nabclockd import NabClockd
    from nabiftttd.nabiftttd import NabIftttd
    from nabmastodond.nabmastodond import NabMastodond
    from nabmqttd.nabmqttd import NabMqttd
    from nabradio.nabradio import NabRadio
    from nabsurprised.nabsurprised import NabSurprised
    from nabtaichid.nabtaichid import NabTaichid
    from nabttsd.nabttsd import NabTtsd
    from nabweatherd.nabweatherd import NabWeatherd
    from nabwebhook.nabwebhook import NabWebhook
    _SERVICE_CLASSES = [
        Nab8Balld,
        NabAirqualityd,
        NabBookd,
        NabClockd,
        NabIftttd,
        NabMastodond,
        NabMqttd,
        NabRadio,
        NabSurprised,
        NabTaichid,
        NabTtsd,
        NabWeatherd,
        NabWebhook,
    ]
    return _SERVICE_CLASSES


class NabCore:
    def __init__(self):
        self.services = []
        self._nabd = None
        self._nabd_server = None
        from nabcommon import settings as nab_settings

        nab_settings.configure("nabcore", orm=False, translations=True)
        for cls in _import_services():
            self.services.append(cls())

        registry = {type(svc).__name__: svc for svc in self.services}
        for svc in self.services:
            if hasattr(svc, "_set_service_registry"):
                svc._set_service_registry(registry)

    def _signal_handler(self, sig, frame):
        loop = asyncio.get_event_loop()
        for svc in self.services:
            loop.call_soon_threadsafe(
                lambda s=svc: loop.create_task(s.reload_config())
            )
        if self._nabd:
            loop.call_soon_threadsafe(
                lambda: loop.create_task(self._nabd.reload_config())
            )

    async def _start_nabd(self):
        from nabd.nabd import Nabd
        from nabcommon import hardware

        hardware_platform = hardware.device_model()
        if hardware.is_pi_zero(hardware_platform):
            from nabd.nabio_hw import NabIOHW

            nabiocls = NabIOHW
        else:
            from nabd.nabio_virtual import NabIOVirtual

            nabiocls = NabIOVirtual
        self._nabd = Nabd(nabiocls())
        loop = asyncio.get_event_loop()
        self._nabd.loop = loop
        self._nabd.nabio.bind_button_event(loop, self._nabd.button_callback)
        self._nabd.nabio.bind_ears_event(loop, self._nabd.ears_callback)
        self._nabd.nabio.bind_rfid_event(loop, self._nabd.rfid_callback)
        loop.create_task(self._nabd.idle_worker_loop())
        self._nabd_server = await asyncio.start_server(
            self._nabd.service_loop,
            host=NabService.HOST,
            port=NabService.PORT_NUMBER,
        )

    async def _connect_service(self, svc):
        retry = 10
        while retry > 0:
            try:
                reader, writer = await asyncio.open_connection(
                    svc.HOST, svc.PORT_NUMBER
                )
                svc.reader = reader
                svc.writer = writer
                svc.loop = asyncio.get_event_loop()
                break
            except ConnectionRefusedError:
                retry -= 1
                await asyncio.sleep(1)
        if retry == 0:
            name = type(svc).__name__
            logging.critical("Could not connect %s to nabd, exiting", name)
            raise RuntimeError(f"Connection failed for {name}")
        asyncio.create_task(svc.client_loop())
        svc.start_service_loop(asyncio.get_event_loop())

    def run(self):
        loop = asyncio.get_event_loop()
        nablogging.setup_asyncio_logging(loop)
        signal.signal(signal.SIGUSR1, self._signal_handler)

        try:
            loop.run_until_complete(self._start_nabd())
        except Exception:
            logging.critical(
                "Failed to start nabd: %s", traceback.format_exc()
            )
            sys.exit(1)

        results = loop.run_until_complete(
            asyncio.gather(
                *(self._connect_service(svc) for svc in self.services),
                return_exceptions=True,
            )
        )
        failed = sum(1 for r in results if isinstance(r, Exception))
        if failed == len(self.services):
            logging.critical("All services failed to connect to nabd, exiting")
            sys.exit(1)

        for svc in self.services:
            if hasattr(svc, "setup_listener"):
                loop.run_until_complete(svc.setup_listener())

        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if self._nabd:
                loop.run_until_complete(self._nabd.stop_idle_worker())
                for writer in self._nabd.service_writers.copy():
                    writer.close()
                    loop.run_until_complete(writer.wait_closed())
            for svc in self.services:
                if svc.writer:
                    svc.writer.close()
            if self._nabd_server:
                self._nabd_server.close()
            loop.run_until_complete(
                asyncio.gather(
                    *(
                        svc.stop_service_loop()
                        for svc in self.services
                        if hasattr(svc, "stop_service_loop")
                    ),
                    return_exceptions=True,
                )
            )
            loop.close()

    @classmethod
    def main(cls, argv):
        nablogging.setup_logging("nabcore")
        pidfilepath = "/run/nabcore.pid"
        usage = (
            "nabcore [options]\n"
            " -h                   display this message\n"
            " --pidfile=<pidfile>  define pidfile (default = /run/nabcore.pid)\n"
        )
        try:
            opts, args = getopt.getopt(argv, "h", ["pidfile="])
        except getopt.GetoptError:
            print(usage)
            exit(2)
        for opt, arg in opts:
            if opt == "-h":
                print(usage)
                exit(0)
            elif opt == "--pidfile":
                pidfilepath = arg
        pidfile = PIDLockFile(pidfilepath, timeout=-1)
        try:
            with pidfile:
                NabCore().run()
        except AlreadyLocked:
            msg = f"nabcore already running? (pid={pidfile.read_pid()})"
            print(msg)
            logging.critical(msg)
            exit(1)
        except LockFailed:
            msg = f"Cannot write pid file to {pidfilepath}, please fix permissions"
            print(msg)
            logging.critical(msg)
            exit(1)
        except Exception:
            msg = f"Unhandled error: {traceback.format_exc()}"
            print(msg)
            logging.critical(msg)
            exit(3)


if __name__ == "__main__":
    NabCore.main(sys.argv[1:])
