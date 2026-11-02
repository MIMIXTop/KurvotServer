import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import quote

DOCKER_SOCKET = "/var/run/docker.sock"
DEFAULT_TAIL = 100


class DockerError(RuntimeError):
    """Raised when the Docker Engine API cannot be queried."""


async def _read_headers(reader: asyncio.StreamReader) -> tuple[int, dict[str, str]]:
    try:
        raw_headers = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
        raise DockerError("Docker API вернул неполный HTTP-ответ") from exc

    lines = raw_headers[:-4].decode("iso-8859-1").split("\r\n")
    try:
        status = int(lines[0].split(" ", 2)[1])
    except (IndexError, ValueError) as exc:
        raise DockerError("Docker API вернул некорректный HTTP-статус") from exc

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.lower()] = value.strip()
    return status, headers


async def _iter_body(
    reader: asyncio.StreamReader, headers: dict[str, str]
) -> AsyncIterator[bytes]:
    if headers.get("transfer-encoding", "").lower() == "chunked":
        while True:
            try:
                size_line = await reader.readuntil(b"\r\n")
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
                raise DockerError("Docker API оборвал chunked-ответ") from exc
            size_text = size_line[:-2].split(b";", 1)[0].strip()
            try:
                size = int(size_text, 16)
            except ValueError as exc:
                raise DockerError("Docker API вернул некорректный chunk") from exc
            if size == 0:
                await reader.readexactly(2)
                return
            yield await reader.readexactly(size)
            await reader.readexactly(2)
        return

    content_length = headers.get("content-length")
    if content_length is not None:
        remaining = int(content_length)
        while remaining:
            chunk = await reader.read(min(65536, remaining))
            if not chunk:
                raise DockerError("Docker API оборвал ответ")
            remaining -= len(chunk)
            yield chunk
        return

    while chunk := await reader.read(65536):
        yield chunk


async def _request(
    method: str, path: str
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, dict[str, str]]:
    try:
        reader, writer = await asyncio.open_unix_connection(
            DOCKER_SOCKET, limit=1024 * 1024
        )
    except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
        raise DockerError("Не удалось подключиться к Docker Engine API") from exc

    request = (
        f"{method} {path} HTTP/1.1\r\n"
        "Host: docker\r\n"
        "Connection: close\r\n"
        "Accept: application/json\r\n"
        "\r\n"
    ).encode("ascii")
    writer.write(request)
    await writer.drain()

    try:
        status, headers = await _read_headers(reader)
    except (DockerError, asyncio.CancelledError):
        writer.close()
        await writer.wait_closed()
        raise
    if status >= 400:
        body = b"".join([chunk async for chunk in _iter_body(reader, headers)])
        writer.close()
        await writer.wait_closed()
        try:
            message = json.loads(body).get("message", body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            message = body.decode("utf-8", errors="replace")
        raise DockerError(f"Docker API: {message}")
    return reader, writer, headers


async def list_containers() -> list[dict[str, str]]:
    reader, writer, headers = await _request("GET", "/containers/json")
    try:
        payload = b"".join([chunk async for chunk in _iter_body(reader, headers)])
    finally:
        writer.close()
        await writer.wait_closed()

    try:
        containers = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DockerError("Docker API вернул некорректный список контейнеров") from exc

    result = []
    for container in containers:
        names = container.get("Names") or []
        name = names[0].lstrip("/") if names else container.get("Id", "")[:12]
        result.append(
            {
                "id": container.get("Id", ""),
                "name": name,
                "image": container.get("Image", ""),
                "state": container.get("State", ""),
                "status": container.get("Status", ""),
            }
        )
    return result


def _log_entry(container: str, stream: int, message: bytes) -> dict[str, str]:
    return {
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": "ERROR" if stream == 2 else "INFO",
        "name": container,
        "msg": message.decode("utf-8", errors="replace").rstrip("\r\n"),
    }


async def stream_logs(
    container: str, *, tail: int = DEFAULT_TAIL
) -> AsyncIterator[dict[str, str]]:
    safe_container = quote(container, safe="")
    path = (
        f"/containers/{safe_container}/logs"
        f"?stdout=1&stderr=1&follow=1&tail={max(0, min(tail, 10000))}"
    )
    reader, writer, headers = await _request("GET", path)
    buffer = bytearray()
    try:
        async for chunk in _iter_body(reader, headers):
            buffer.extend(chunk)
            while len(buffer) >= 8:
                stream = buffer[0]
                size = int.from_bytes(buffer[4:8], "big")
                if stream not in (1, 2) or size > 16 * 1024 * 1024:
                    line_end = buffer.find(b"\n")
                    if line_end < 0:
                        break
                    yield _log_entry(container, 1, bytes(buffer[: line_end + 1]))
                    del buffer[: line_end + 1]
                    continue
                if len(buffer) < 8 + size:
                    break
                message = bytes(buffer[8 : 8 + size])
                del buffer[: 8 + size]
                yield _log_entry(container, stream, message)
            if buffer and len(buffer) < 8:
                continue
        if buffer:
            yield _log_entry(container, 1, bytes(buffer))
    finally:
        writer.close()
        await writer.wait_closed()
