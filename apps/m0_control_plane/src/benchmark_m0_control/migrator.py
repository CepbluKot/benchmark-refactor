import os
from pathlib import Path

from alembic import command
from alembic.config import Config


def main() -> None:
    config_path = Path(
        os.environ.get("M0_ALEMBIC_CONFIG", "/app/adapters/postgres/alembic.ini")
    )
    if not config_path.is_file():
        raise ValueError("Alembic configuration file does not exist")
    command.upgrade(Config(str(config_path)), "head")
