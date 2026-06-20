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
    from nabbookd.nabbookd import NabBookd
    from nabiftttd.nabiftttd import NabIftttd
    from nabradio.nabradio import NabRadio
    from nabtaichid.nabtaichid import NabTaichid
    from nabttsd.nabttsd import NabTtsd
    from nabwebhook.nabwebhook import NabWebhook
    _SERVICE_CLASSES = [
        Nab8Balld,
        NabBookd,
        NabIftttd,
        NabRadio,
        NabTaichid,
        NabTtsd,
        NabWebhook,
    ]
    return _SERVICE_CLASSES


class NabCore:
    def __init__(self):
        self.services = []
        from nabcommon import settings as nab_settings

        nab_settings.configure("nabcore", orm=False, translations=True)
        for cls in _import_services():
            self.services.append(cls())

    def _signal_handler(self, sig, frame):
        loop = asyncio.get_event_loop()
        for svc in self.services:
            loop.call_soon_threadsafe(
                lambda s=svc: loop.create_task(s.reload_config())
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
        nablogging.setup_logging("nabcore")
        loop = asyncio.get_event_loop()
        nablogging.setup_asyncio_logging(loop)
        signal.signal(signal.SIGUSR1, self._signal_handler)

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
            for svc in self.services:
                if svc.writer:
                    svc.writer.close()
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
