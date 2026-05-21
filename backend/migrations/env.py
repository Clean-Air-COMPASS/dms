from __future__ import annotations
from logging.config import fileConfig
from sqlalchemy import create_engine, pool
from alembic import context

                     
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

                                    
from db.config import resolve_database_url              
from models import Base              
target_metadata = Base.metadata

def get_url() -> str:
                                                                         
    return resolve_database_url()

def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,                        
        compare_server_default=True
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = create_engine(
        get_url(),
        poolclass=pool.NullPool,
        pool_pre_ping=True
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
