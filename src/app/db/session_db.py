import os
import threading

from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from app.db.models import BaseSession
from config import Config


lock = threading.Lock()
_Engine = create_engine(
    f"sqlite:///{os.path.join(Config().get_config_path(), 'session.db')}?check_same_thread=False",
    echo=False,
    poolclass=QueuePool,
    pool_pre_ping=True,
    pool_size=50,
    pool_recycle=60 * 10,
    max_overflow=0,
)


class SessionDb:
    @staticmethod
    def init_db():
        with lock:
            BaseSession.metadata.create_all(_Engine)
