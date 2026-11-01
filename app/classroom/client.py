import asyncio
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProxyResponse:
    status_code: int
    headers: list[tuple[str, str]]
    body: bytes


class GoogleApiProxyError(RuntimeError):
    pass


class GoogleApiClient:
    async def request(
        self,
        method: str,
        url: str,
        body: bytes,
        headers: list[tuple[str, str]],
    ) -> ProxyResponse:
        def send() -> ProxyResponse:
            request_headers = {
                key: value
                for key, value in headers
                if key.lower() not in {"host", "content-length"}
            }
            http_request = urllib.request.Request(
                url,
                data=body if method not in {"GET", "HEAD"} else None,
                headers=request_headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(http_request, timeout=30) as response:
                    return ProxyResponse(
                        response.status,
                        list(response.headers.items()),
                        response.read(),
                    )
            except urllib.error.HTTPError as exc:
                return ProxyResponse(
                    exc.code,
                    list(exc.headers.items()),
                    exc.read(),
                )
            except OSError as exc:
                raise GoogleApiProxyError("Google API request failed") from exc

        return await asyncio.to_thread(send)
