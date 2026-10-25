"""Runs the game on a web host that speaks WSGI (PythonAnywhere and most others).

The host imports `application` from this file. See README.md for the setup.
The host must run this with a single worker process: cities are kept in memory.

Moving the game to another server (README.md, "Moving to your own server"): a file named MOVED_TO next to this
one stops the game here. The first request after it appears saves every city to disk one last time, and from
then on nothing here changes. While the file is empty, every page says the game is moving; once it holds the new
address (https://...), everyone is sent there, the desktop apps included.
"""

from http import HTTPStatus

import server

server.startup()

MOVED_FILE = server.ROOT / "MOVED_TO"
FROZEN = {"done": False}
MOVING_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dolphin City Builder is moving</title></head>
<body style="background:#0d1110;color:#cfd8d3;font:16px/1.6 monospace;display:grid;place-items:center;min-height:90vh;margin:0;padding:16px">
<div style="max-width:520px"><h1 style="color:#e6c35c;font-size:20px">Dolphin City Builder is moving to a new home</h1>
<p>Every city is safe and is being copied across now. The game will be back in a few minutes, at a new address:
reload this page then and you will be taken there.</p></div></body></html>"""


def _moved_to():
    """None while the game runs here; "" while it is being moved; the new address once it has moved."""
    try:
        return MOVED_FILE.read_text(encoding="utf-8").strip() if MOVED_FILE.exists() else None
    except OSError:
        return None


def _moved(environ, start_response, target):
    if not FROZEN["done"]:          # the last save here, before the saves are copied across
        with server.LOCK:
            server.DIRTY.update(server.CITIES)      # every city in memory, with its latest progress
            server.flush()
        FROZEN["done"] = True
    path, query = environ.get("PATH_INFO") or "/", environ.get("QUERY_STRING", "")
    if target.startswith("https://"):
        if path.startswith("/api/"):     # a page still open here: it is told where to go
            body = ('{"error": "The game has moved to %s - reload the page to go there."}' % target).encode("utf-8")
            start_response("410 Gone", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
            return [body]
        where = target.rstrip("/") + path + ("?" + query if query else "")
        start_response("301 Moved Permanently", [("Location", where), ("Content-Length", "0")])
        return [b""]
    if path.startswith("/api/"):
        body = b'{"error": "The game is moving to a new home and will be back in a few minutes."}'
        start_response("503 Service Unavailable", [("Content-Type", "application/json"), ("Content-Length", str(len(body))),
                                                   ("Retry-After", "120")])
        return [body]
    body = MOVING_PAGE.encode("utf-8")
    start_response("503 Service Unavailable", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))),
                                               ("Retry-After", "120"), ("Cache-Control", "no-store")])
    return [body]


def application(environ, start_response):
    target = _moved_to()
    if target is not None:
        return _moved(environ, start_response, target)
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    body = environ["wsgi.input"].read(min(length, server.MAX_BODY)) if length > 0 else b""
    status, payload, content_type = server.respond(
        environ["REQUEST_METHOD"], environ.get("PATH_INFO") or "/",
        environ.get("QUERY_STRING", ""), environ.get("HTTP_X_TOKEN"), body,
        {"X-Signature-Ed25519": environ.get("HTTP_X_SIGNATURE_ED25519"),
         "X-Signature-Timestamp": environ.get("HTTP_X_SIGNATURE_TIMESTAMP")})
    payload, extra = server.compress(payload, environ.get("HTTP_ACCEPT_ENCODING"))
    start_response(f"{status} {HTTPStatus(status).phrase}", extra + [
        ("Content-Type", content_type),
        ("Content-Length", str(len(payload))),
        ("Cache-Control", "no-store"),
    ])
    return [payload]
