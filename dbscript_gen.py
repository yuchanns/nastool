import os

from alembic.command import revision as alembic_revision
from alembic.config import Config as AlembicConfig

from config import Config

db_version = input("请输入版本号：")
db_location = os.path.join(Config().get_config_path(), "user.db").replace("\\", "/")
script_location = os.path.join(os.path.dirname(__file__), "db_scripts").replace("\\", "/")
alembic_cfg = AlembicConfig()
alembic_cfg.set_main_option("script_location", script_location)
alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_location}")
alembic_revision(alembic_cfg, db_version, True)
