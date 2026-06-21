import asyncio
import getopt
import logging
import signal
import sys
import traceback

from lockfile import AlreadyLocked, LockFailed
from lockfile.pidlockfile import PIDLockFile

from nabcommon import nablogging


_SERVICE_CLASSES = None


def _import_services():
    global _SERVICE_CLASSES
    if _SERVICE_CLASSES is not None:
        return _SERVICE_CLASSES
    logger = logging.getLogger(__name__)
    _imports = [
        ("nab8balld.nab8balld", "Nab8Balld"),
        ("nabairqualityd.nabairqualityd", "NabAirqualityd"),
        ("nabbookd.nabbookd", "NabBookd"),
        ("nabclockd.nabclockd", "NabClockd"),
        ("nabiftttd.nabiftttd", "NabIftttd"),
        ("nabmastodond.nabmastodond", "NabMastodond"),
        ("nabmqttd.nabmqttd", "NabMqttd"),
        ("nabradio.nabradio", "NabRadio"),
        ("nabsurprised.nabsurprised", "NabSurprised"),
        ("nabtaichid.nabtaichid", "NabTaichid"),
        ("nabttsd.nabttsd", "NabTtsd"),
        ("nabweatherd.nabweatherd", "NabWeatherd"),
        ("nabwebhook.nabwebhook", "NabWebhook"),
    ]
    _SERVICE_CLASSES = []
    for module_name, cls_name in _imports:
        try:
            mod = __import__(module_name, fromlist=[cls_name])
            cls = getattr(mod, cls_name)
            _SERVICE_CLASSES.append(cls)
        except ImportError as e:
            logger.warning("Service %s unavailable: %s", cls_name, e)
    return _SERVICE_CLASSES


class NabCore:
    def __init__(self):
        self.services = []
        self._nabd = None
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
        loop.create_task(
            asyncio.start_server(
                self._nabd.service_loop,
                "127.0.0.1",
                10543,
            )
        )

    async def _connect_service(self, svc):
        outgoing = asyncio.Queue()
        svc._outgoing = outgoing
        svc.loop = asyncio.get_event_loop()
        channel = self._nabd.register_service(
            type(svc).__name__, outgoing
        )
        svc._incoming = channel.incoming
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
            for svc in self.services:
                if svc._outgoing:
                    svc._outgoing = None
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
