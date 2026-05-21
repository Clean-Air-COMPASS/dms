from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from db.config import resolve_database_url

DATABASE_URL = resolve_database_url()
               
connect_args: dict[str, object] = {}
if DATABASE_URL.startswith("sqlite"):
                                                                
    connect_args["check_same_thread"] = False

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
    future=True,
)

                                          
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations.

    Yields a SQLAlchemy Session instance and ensures it is closed after use.
    """
    with SessionLocal() as session:
        yield session
