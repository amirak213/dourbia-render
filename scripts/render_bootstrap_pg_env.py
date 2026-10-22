"""Derive PG_* and DOURBIA_PG_* from database URLs before uvicorn starts (Render Blueprint)."""

from __future__ import annotations

import os
import re
import sys
from urllib.parse import unquote, urlparse


def _normalize_driver(url: str) -> str:
    if not url:
        return url
    if url.startswith("postgresql+") or url.startswith("postgres+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def _plain_driver(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return re.sub(r"^(postgresql|postgres)\+[^:]+", "postgresql", url, count=1)


def _parse_postgres_url(raw: str) -> dict[str, str]:
    cleaned = re.sub(r"^postgresql\+[^:]+", "postgresql", raw.strip(), count=1)
    cleaned = re.sub(r"^postgres\+[^:]+", "postgresql", cleaned, count=1)
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ValueError(f"unsupported scheme in {raw!r}")
    db = (parsed.path or "").lstrip("/").split("/", 1)[0]
    return {
        "host": parsed.hostname or "",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": db,
    }


def _set_if_empty(key: str, value: str) -> None:
    if value and not os.environ.get(key):
        os.environ[key] = value


def _apply_url(raw: str, *, circuit: bool) -> None:
    if not raw.strip():
        return
    parts = _parse_postgres_url(raw)
    host, port = parts["host"], parts["port"]
    user, password, database = parts["user"], parts["password"], parts["database"]

    _set_if_empty("PG_HOST", host)
    _set_if_empty("PG_PORT", port)
    _set_if_empty("PG_USER", user)
    _set_if_empty("PG_PASSWORD", password)
    _set_if_empty("PG_DBNAME", database)

    _set_if_empty("DOURBIA_PG_HOST", host)
    _set_if_empty("DOURBIA_PG_PORT", port)
    _set_if_empty("DOURBIA_PG_USER", user)
    _set_if_empty("DOURBIA_PG_PASSWORD", password)
    _set_if_empty("DOURBIA_PG_DB", database)

    if circuit:
        os.environ["CIRCUIT_DATABASE_URL"] = _normalize_driver(raw.strip())
    else:
        os.environ["HISTORICAL_DATABASE_URL"] = _plain_driver(raw.strip())


def main() -> int:
    try:
        circuit = os.environ.get("CIRCUIT_DATABASE_URL", "")
        historical = os.environ.get("HISTORICAL_DATABASE_URL", "")
        _apply_url(circuit, circuit=True)
        _apply_url(historical or circuit, circuit=False)
    except Exception as exc:
        print(f"[render_bootstrap_pg_env] {exc}", file=sys.stderr)
        return 1
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
            "--host",
            "0.0.0.0",
            "--port",
            os.environ.get("PORT", "8000"),
        ],
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
