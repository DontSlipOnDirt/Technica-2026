# nessie.py
# Small client for Capital One's Nessie API (the pretend bank).
# Ported from Jacob's TypeScript nessie-mcp branch (src/nessie.ts).
# The API key stays on the server; it's added to every request as ?key=...

import logging
import os
from typing import Any, Optional

import httpx

DEFAULT_BASE_URL = "https://api.nessieisreal.com"

# httpx logs every request URL at INFO, and Nessie puts the API key in the URL.
# Keep those logs off so the key never lands in Render's logs.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class NessieApiError(Exception):
    """A Nessie request failed. The message never includes Nessie's response body.
    detail holds only Nessie's own JSON "message"/"culprit", for the server logs."""

    def __init__(self, message: str, status: int, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.detail = detail


def _error_detail(response: httpx.Response) -> str:
    """Nessie errors look like {"code": 400, "message": "...", "culprit": [...]}."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    detail = str(body.get("message") or "")
    culprit = body.get("culprit")
    if culprit:
        detail += f" ({'; '.join(map(str, culprit)) if isinstance(culprit, list) else culprit})"
    return detail[:300]


class NessieClient:
    def __init__(self, api_key: str, base_url: Optional[str] = None, timeout_s: float = 10.0,
                 transport: Optional[httpx.BaseTransport] = None):
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._http = httpx.Client(timeout=timeout_s, transport=transport)

    @classmethod
    def from_env(cls) -> "NessieClient":
        # Pasted keys often pick up spaces, newlines, or quotes; any of those makes Nessie answer 404.
        api_key = os.environ.get("NESSIE_API_KEY", "").strip().strip("'\"").strip()
        if not api_key:
            raise RuntimeError("NESSIE_API_KEY is required")
        return cls(api_key, base_url=os.environ.get("NESSIE_BASE_URL"))

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: Any) -> Any:
        return self._request("POST", path, body=body)

    def put(self, path: str, body: Any) -> Any:
        return self._request("PUT", path, body=body)

    def _request(self, method: str, path: str, params: Optional[dict] = None, body: Any = None) -> Any:
        query = {**(params or {}), "key": self._api_key}
        try:
            response = self._http.request(method, f"{self._base_url}{path}", params=query,
                                          json=body, headers={"Accept": "application/json"})
        except httpx.TimeoutException:
            raise NessieApiError("Nessie request timed out", 408)
        except httpx.HTTPError:
            raise NessieApiError("Couldn't reach Nessie", 503)

        if response.status_code >= 400:
            raise NessieApiError(f"Nessie request failed with status {response.status_code}", response.status_code,
                                 _error_detail(response))
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text
