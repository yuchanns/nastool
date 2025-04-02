import socket
import warnings

from twisted.internet import ssl, tcp
from twisted.internet.base import ReactorBase


warnings.filterwarnings("ignore")


def get_run_config():
    from multiprocessing import cpu_count
    from typing import Literal, TypedDict, Union, cast

    from config import Config

    """
    Get runtime configuration
    """
    args = TypedDict(
        "FlaskRunArgs",
        {
            "host": str,
            "port": int,
            "debug": bool,
            "ssl_context": Union[tuple[str, str], Literal["adhoc"], None],
            "process_num": int,
        },
        total=True,
    )(
        {
            "host": "::",
            "port": 3000,
            "debug": False,
            "ssl_context": None,
            "process_num": cpu_count(),
        }
    )

    app_conf = Config().get_config("app")
    if app_conf:
        web_host = app_conf.get("web_host")
        web_port = str(app_conf.get("web_port", "")).strip()
        if web_port.isdigit():
            args["port"] = int(web_port)
        if web_host is not None:
            args["host"] = cast(str, web_host.replace("[", "").replace("]", ""))
        ssl_cert = app_conf.get("ssl_cert")
        ssl_key = app_conf.get("ssl_key")
        if ssl_cert is not None and ssl_key is not None:
            _ssl_cert = cast(str, ssl_cert)
            _ssl_key = cast(str, ssl_key)
            if _ssl_cert != "" and _ssl_key != "":
                args["ssl_context"] = (_ssl_cert, _ssl_key)
        args["debug"] = True if app_conf.get("debug") else False
        process_num = app_conf.get("process_num")
        if process_num is not None and process_num > 0:
            args["process_num"] = min(process_num, args["process_num"])

    return args


def init_system():
    import log

    from app.db import init_data, init_db, update_db
    from check_config import check_config, update_config
    from version import APP_VERSION

    # Configuration
    log.console("NAStool 当前版本号：%s" % APP_VERSION)
    # Initialize database
    init_db()
    # Update database
    update_db()
    # Initialize data
    init_data()
    # Upgrade configuration file
    update_config()
    # Check configuration file
    check_config()


def start_service():
    import log

    from app.brushtask import BrushTask
    from app.helper import ChromeHelper, DisplayHelper, IndexerHelper
    from app.rsschecker import RssChecker
    from app.scheduler import run_scheduler
    from app.speedlimiter import SpeedLimiter
    from app.sync import run_monitor
    from app.torrentremover import TorrentRemover

    log.console("开始启动服务...")
    # Start virtual display
    DisplayHelper()
    # Start scheduler service
    run_scheduler()
    # Start monitoring service
    run_monitor()
    # Start brush task service
    BrushTask()
    # Start custom RSS service
    RssChecker()
    # Start auto torrent removal service
    TorrentRemover()
    # Start playback speed limit service
    SpeedLimiter()
    # Load indexer configuration
    IndexerHelper()
    # Initialize browser
    ChromeHelper().init_driver()


class ReusablePort(tcp.Port):
    def __init__(self, port, factory, reuse=False, **kwargs):
        super().__init__(port, factory, **kwargs)
        self.reuse = reuse

    def createInternetSocket(self):
        s = super().createInternetSocket()
        if self.reuse:
            import sys

            platform = sys.platform
            if platform in ("linux", "darwin") or "bsd" in platform:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            elif platform == "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            else:
                raise RuntimeError(f"Unsupported platform: {platform}")
        return s


class ReusableSSLPort(ssl.Port):
    def __init__(self, port, factory, ctxFactory, reuse=False, **kwargs):
        super().__init__(port, factory, ctxFactory, **kwargs)
        self.reuse = reuse

    def createInternetSocket(self):
        s = super().createInternetSocket()
        if self.reuse:
            import sys

            platform = sys.platform
            if platform in ("linux", "darwin") or "bsd" in platform:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            elif platform == "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            else:
                raise RuntimeError(f"Unsupported platform: {platform}")
        return s


def run_server(config, typed_reactor: ReactorBase):
    from twisted.web.server import Site
    from twisted.web.wsgi import WSGIResource

    from web.main import App

    # Initialize Twisted WSGI server for handling web requests
    # Twisted provides better performance and scalability compared to Flask's default server
    App.debug = config["debug"]
    resource = WSGIResource(typed_reactor, typed_reactor.getThreadPool(), App)
    if config["ssl_context"] is None:
        listener = ReusablePort(
            config["port"],
            Site(resource),
            reuse=True,
        )
    else:
        from twisted.internet import ssl

        factory = ssl.DefaultOpenSSLContextFactory(
            config["ssl_context"][0],
            config["ssl_context"][1],
        )
        listener = ReusableSSLPort(
            config["port"],
            Site(resource),
            factory,
            reuse=True,
        )

    listener.startListening()
    typed_reactor.run()
    log.info("reactor stopped, exiting...")


if __name__ == "__main__":
    import signal
    import sys

    from multiprocessing import Event, Process

    import log

    # Create an event to notify child processes to exit
    shutdown_event = Event()
    processes = []

    def run_server_wrapper(config, shutdown_event):
        try:
            from typing import cast

            from twisted.internet import reactor
            from twisted.internet.base import ReactorBase

            typed_reactor = cast(ReactorBase, reactor)

            def check_shutdown():
                if shutdown_event.is_set():
                    log.info(f"Stopping process {Process().name}...")
                    typed_reactor.stop()
                else:
                    typed_reactor.callLater(10, check_shutdown)

            typed_reactor.callLater(10, check_shutdown)

            run_server(config, typed_reactor)
        except Exception as e:
            log.error(f"Process error: {str(e)}")
            sys.exit(1)

    init_system()
    start_service()
    config = get_run_config()

    for i in range(config["process_num"]):
        p = Process(
            target=run_server_wrapper,
            args=(config, shutdown_event),
            name=f"NASTool-{i + 1}",
        )
        processes.append(p)
        p.start()

    log.info(f"Started {config['process_num']} server processes")
    log.info(f"Starting server on port {config['port']}")

    signal.sigwait([signal.SIGINT, signal.SIGTERM])
    shutdown_event.set()

    for p in processes:
        p.join()
