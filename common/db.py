"""
common/db.py
--------------------------------------------------------------------------------
Single place for .env loading and PostgreSQL connections.

Importing this module:
  1. Loads <repo root>/.env (without overriding variables already set).
  2. Normalises the variable names so every script finds its settings.
     Accepted spellings, first match wins:
        DB_HOST      | DB_HOST1      | POSTGRES_HOST
        DB_PORT      | DB_PORT1      | POSTGRES_PORT
        DB_NAME      | DB_NAME1      | POSTGRES_DB
        DB_USER      | DB_USER1      | POSTGRES_USER
        DB_PASSWORD  | DB_PASSWORD1  | POSTGRES_PASSWORD
        DB_SCHEMA    | DB_SCHEMA1    (default: validate)
     After loading, both the DB_* and POSTGRES_* names are set, so scripts
     that still read either spelling keep working.
  3. If MSP_READ_ONLY=1, adds `-c default_transaction_read_only=on` to
     PGOPTIONS. libpq applies that to EVERY connection made by this process,
     so any INSERT/UPDATE/DELETE/DDL fails. Use it for verification runs.
--------------------------------------------------------------------------------
"""
import os
from pathlib import Path

import psycopg2

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
ENV_PATH = ROOT_DIR / ".env"

_ALIASES = {
    "HOST":     ("DB_HOST", "DB_HOST1", "POSTGRES_HOST"),
    "PORT":     ("DB_PORT", "DB_PORT1", "POSTGRES_PORT"),
    "NAME":     ("DB_NAME", "DB_NAME1", "POSTGRES_DB"),
    "USER":     ("DB_USER", "DB_USER1", "POSTGRES_USER"),
    "PASSWORD": ("DB_PASSWORD", "DB_PASSWORD1", "POSTGRES_PASSWORD"),
    "SCHEMA":   ("DB_SCHEMA", "DB_SCHEMA1"),
}
_POSTGRES_NAME = {"HOST": "POSTGRES_HOST", "PORT": "POSTGRES_PORT", "NAME": "POSTGRES_DB",
                  "USER": "POSTGRES_USER", "PASSWORD": "POSTGRES_PASSWORD"}


def load_env() -> None:
    try:
        from dotenv import load_dotenv
        if ENV_PATH.exists():
            load_dotenv(ENV_PATH, override=False)
    except ImportError:
        pass  # rely on the shell environment

    for key, names in _ALIASES.items():
        value = next((os.environ[n] for n in names if os.environ.get(n)), None)
        if key == "SCHEMA" and not value:
            value = "validate"
        if value is None:
            continue
        os.environ.setdefault(f"DB_{key}", value)
        if key in _POSTGRES_NAME:
            os.environ.setdefault(_POSTGRES_NAME[key], value)

    if os.environ.get("MSP_READ_ONLY") == "1":
        opt = "-c default_transaction_read_only=on"
        current = os.environ.get("PGOPTIONS", "")
        if opt not in current:
            os.environ["PGOPTIONS"] = f"{current} {opt}".strip()


load_env()


def db_config(dbname: str = None) -> dict:
    """Connection keyword arguments for psycopg2.connect()."""
    return {
        "host":     os.environ.get("DB_HOST"),
        "port":     int(os.environ.get("DB_PORT") or 5432),
        "dbname":   dbname or os.environ.get("DB_NAME"),
        "user":     os.environ.get("DB_USER"),
        "password": os.environ.get("DB_PASSWORD"),
    }


def db_url(dbname: str = None) -> str:
    """postgresql:// URL for libraries that want one (password URL-encoded)."""
    from urllib.parse import quote
    c = db_config(dbname)
    return (f"postgresql://{quote(c['user'] or '')}:{quote(c['password'] or '')}"
            f"@{c['host']}:{c['port']}/{c['dbname']}")


def default_schema() -> str:
    return os.environ.get("DB_SCHEMA", "validate")


def is_read_only() -> bool:
    return os.environ.get("MSP_READ_ONLY") == "1"


def get_connection(dbname: str = None, search_path: str = None, **overrides):
    """
    Open a psycopg2 connection from the .env settings.
    `overrides` may contain host/port/user/password/dbname to override .env
    (used by scripts that still accept --host/--port/... flags).
    """
    cfg = db_config(dbname)
    cfg.update({k: v for k, v in overrides.items() if v not in (None, "")})
    if search_path:
        cfg["options"] = f"-c search_path={search_path},public"
    return psycopg2.connect(**cfg)
