import os
import sys
import time
import warnings

from typing import Literal, TypedDict, Union, cast

from twisted.internet import endpoints, reactor
from twisted.internet.base import ReactorBase
from twisted.web.server import Site
from twisted.web.wsgi import WSGIResource
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import log

from app.brushtask import BrushTask
from app.db import init_data, init_db, update_db
from app.helper import ChromeHelper, DisplayHelper, IndexerHelper
from app.rsschecker import RssChecker
from app.scheduler import restart_scheduler, run_scheduler
from app.speedlimiter import SpeedLimiter
from app.sync import restart_monitor, run_monitor
from app.torrentremover import TorrentRemover
from app.utils import ConfigLoadCache
from app.utils.commons import INSTANCES
from check_config import check_config, update_config
from config import Config
from version import APP_VERSION
from web.main import App


warnings.filterwarnings("ignore")

# 运行环境判断
is_windows_exe = getattr(sys, "frozen", False) and (os.name == "nt")
if is_windows_exe:
    # 托盘相关库
    import threading

    from windows.trayicon import NullWriter, TrayIcon

    # 初始化环境变量
    os.environ["NASTOOL_CONFIG"] = os.path.join(
        os.path.dirname(sys.executable), "config", "config.yaml"
    ).replace("\\", "/")
    os.environ["NASTOOL_LOG"] = os.path.join(
        os.path.dirname(sys.executable), "config", "logs"
    ).replace("\\", "/")
    try:
        config_dir = os.path.join(os.path.dirname(sys.executable), "config").replace(
            "\\", "/"
        )
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
    except Exception as err:
        print(str(err))
else:
    NullWriter = None
    TrayIcon = None
    threading = None


class FlaskRunArgs(TypedDict, total=False):
    host: str
    port: int
    debug: bool
    threaded: bool
    use_reloader: bool
    ssl_context: Union[tuple[str, str], Literal["adhoc"], None]


def get_run_config():
    """
    获取运行配置
    """
    args: FlaskRunArgs = {
        "host": "::",
        "port": 3000,
        "debug": False,
        "ssl_context": None,
    }

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
            args["ssl_context"] = (_ssl_cert, _ssl_key)
        args["debug"] = True if app_conf.get("debug") else False

    return args


def init_system():
    # 配置
    log.console("NAStool 当前版本号：%s" % APP_VERSION)
    # 数据库初始化
    init_db()
    # 数据库更新
    update_db()
    # 数据初始化
    init_data()
    # 升级配置文件
    update_config()
    # 检查配置文件
    check_config()


def start_service():
    log.console("开始启动服务...")
    # 启动虚拟显示
    DisplayHelper()
    # 启动定时服务
    run_scheduler()
    # 启动监控服务
    run_monitor()
    # 启动刷流服务
    BrushTask()
    # 启动自定义订阅服务
    RssChecker()
    # 启动自动删种服务
    TorrentRemover()
    # 启动播放限速服务
    SpeedLimiter()
    # 加载索引器配置
    IndexerHelper()
    # 初始化浏览器
    if not is_windows_exe:
        ChromeHelper().init_driver()


def monitor_config():
    class _ConfigHandler(FileSystemEventHandler):
        """
        配置文件变化响应
        """

        def __init__(self):
            FileSystemEventHandler.__init__(self)

        def on_modified(self, event):
            if (
                not event.is_directory
                and os.path.basename(event.src_path) == "config.yaml"
            ):
                # 10秒内只能加载一次
                if ConfigLoadCache.get(event.src_path):
                    return
                ConfigLoadCache.set(event.src_path, True)
                log.console(
                    "进程 %s 检测到配置文件已修改，正在重新加载..." % os.getpid()
                )
                time.sleep(1)
                # 重新加载配置
                Config().init_config()
                # 重载singleton服务
                for instance in INSTANCES.values():
                    if hasattr(instance, "init_config"):
                        instance.init_config()
                # 重启定时服务
                restart_scheduler()
                # 重启监控服务
                restart_monitor()

    # 配置文件监听
    _observer = Observer(timeout=10)
    _observer.schedule(
        _ConfigHandler(), path=Config().get_config_path(), recursive=False
    )
    _observer.daemon = True
    _observer.start()


# 系统初始化
init_system()

# 启动服务
start_service()

# 监听配置文件变化
monitor_config()

# 本地运行
if __name__ == "__main__":
    # Windows启动托盘
    if is_windows_exe and NullWriter is not None:
        homepage = Config().get_config("app").get("domain")
        if not homepage:
            homepage = "http://localhost:%s" % str(
                Config().get_config("app").get("web_port")
            )
        log_path = os.environ.get("NASTOOL_LOG")

        sys.stdout = NullWriter()
        sys.stderr = NullWriter()

        def traystart():
            if TrayIcon is None:
                return
            TrayIcon(homepage, log_path)

        if (
            threading is not None
            and len(
                os.popen("tasklist| findstr %s" % os.path.basename(sys.executable), "r")
                .read()
                .splitlines()
            )
            <= 2
        ):
            p1 = threading.Thread(target=traystart, daemon=True)
            p1.start()

    # Initialize Twisted WSGI server for handling web requests
    # Twisted provides better performance and scalability compared to Flask's default server
    typed_reactor = cast(ReactorBase, reactor)
    config = get_run_config()
    App.debug = config["debug"]
    resource = WSGIResource(typed_reactor, typed_reactor.getThreadPool(), App)
    if config["ssl_context"] is None:
        endpoint = endpoints.TCP4ServerEndpoint(
            typed_reactor, config["port"], interface=config["host"]
        )
    else:
        from twisted.internet import ssl

        factory = ssl.DefaultOpenSSLContextFactory(
            config["ssl_context"][0],
            config["ssl_context"][1],
        )
        endpoint = endpoints.SSL4ServerEndpoint(
            typed_reactor, config["port"], factory, interface=config["host"]
        )
    endpoint.listen(Site(resource))
    log.info(f"Starting server on port {config['port']}")
    typed_reactor.run()
