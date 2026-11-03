import os
from pathlib import Path
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Ensure src/ is on Python search path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from startup_agent.config.settings import Settings
from startup_agent.database.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set model metadata for autogenerate
target_metadata = Base.metadata

# Set dynamic sqlalchemy.url from Settings if not explicitly overridden
settings = Settings.load()
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Ensure target database directory exists if using SQLite
    db_url = config.get_main_option("sqlalchemy.url")
    if db_url and db_url.startswith("sqlite:///"):
        sqlite_file_path = db_url.replace("sqlite:///", "")
        if sqlite_file_path and sqlite_file_path != ":memory:":
            Path(sqlite_file_path).parent.mkdir(parents=True, exist_ok=True)

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = db_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
