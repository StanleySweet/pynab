import logging
import logging.handlers
import os
import sys


_handling_exception = False


def _excepthook(exc_type, exc_value, exc_traceback):
    global _handling_exception
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    if _handling_exception:
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    _handling_exception = True
    try:
        logging.critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_traceback)
    _handling_exception = False


def setup_asyncio_logging(loop):
    def _asyncio_exception_handler(loop, context):
        exc = context.get("exception")
        if exc:
            logging.critical(
                "Unhandled exception in asyncio task: %s",
                context.get("message", ""),
                exc_info=exc,
            )
        else:
            logging.error(
                "Asyncio error: %s",
                context.get("message", ""),
            )
        loop.default_exception_handler(context)

    loop.set_exception_handler(_asyncio_exception_handler)


def setup_logging(daemon):
    logdir = os.environ.get("LOGDIR", "/var/log/")
    loglevel = os.environ.get("LOGLEVEL", "INFO")
    formatter = logging.Formatter(
        f"%(asctime)s [%(levelname)s] {daemon}: %(message)s"
    )
    logger = logging.getLogger()
    log_handler = logging.handlers.WatchedFileHandler(
        f"{logdir}/{daemon}.log"
    )
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)
    try:
        logger.setLevel(loglevel)
    except ValueError:
        loglevel = "DEBUG"
        logger.setLevel(loglevel)
    if loglevel == "DEBUG":
        logging.debug("debug logging enabled")
    sys.excepthook = _excepthook
    logging.info(f"started with log level {loglevel}")
