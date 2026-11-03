"""One loopback-origin policy for middleware and CORS, including Vite fallback ports."""

from urllib.parse import urlsplit
from fastapi.middleware.cors import CORSMiddleware

LOOPBACK_HOSTS = frozenset(("localhost", "127.0.0.1", "::1"))


def local_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        return (
            parsed.scheme in ("http", "https")
            and parsed.hostname in LOOPBACK_HOSTS
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and not any(c.isspace() for c in origin)
        )
    except (ValueError, TypeError):
        return False


class LocalCORSMiddleware(CORSMiddleware):
    def is_allowed_origin(self, origin: str) -> bool:
        return local_origin(origin)
