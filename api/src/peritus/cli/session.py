"""Local session cache for the Python CLI.

The CLI logs in via the API's ``/auth`` endpoints (email OTP) and caches the
resulting session so subsequent commands know who the user is. The refresh token
is a long-lived credential, so the file is written owner-only (0600).
"""

import contextlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def session_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "peritus" / "session.json"


@dataclass
class Session:
    access_token: str
    refresh_token: str
    expires_at: int
    user_id: str
    email: str


def load() -> Session | None:
    path = session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return Session(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=int(data.get("expires_at", 0)),
            user_id=data["user_id"],
            email=data.get("email", ""),
        )
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def save(session: Session) -> None:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(session), indent=2))
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def clear() -> None:
    with contextlib.suppress(FileNotFoundError):
        session_path().unlink()


def current_user_id() -> str | None:
    """The signed-in user's id (for stamping ownership on locally-built experts)."""
    session = load()
    return session.user_id if session else None
