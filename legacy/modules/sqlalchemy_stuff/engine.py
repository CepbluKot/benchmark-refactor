# clickhouse-sqlalchemy helper imports
from clickhouse_sqlalchemy import get_declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from settings import settings
# ----------------- Настройка подключения -----------------
db_username = settings.TGT_DATABASE_USERNAME.get_secret_value()
db_password = settings.TGT_DATABASE_PASSWORD.get_secret_value()
CLICKHOUSE_URL = f"clickhouse://{db_username}:{db_password}@{settings.TGT_DATABASE_HOST}:{settings.TGT_DATABASE_PORT}/{settings.BENCHMARK_RESULTS_DATABASE}"
engine = create_engine(CLICKHOUSE_URL, echo=False)
Base = get_declarative_base()
Session = sessionmaker(bind=engine)