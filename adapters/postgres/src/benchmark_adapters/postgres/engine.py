from sqlalchemy import Engine, create_engine


def create_product_engine(
    database_url: str, *, pool_size: int = 5, max_overflow: int = 0
) -> Engine:
    if not database_url.startswith(("postgresql+psycopg://", "postgresql://")):
        raise ValueError("product state requires PostgreSQL through psycopg")

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )
