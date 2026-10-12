"""Runs the game on a web host that speaks WSGI (PythonAnywhere and most others).

The host imports `application` from this file. See README.md for the setup.
The host must run this with a single worker process: cities are kept in memory.
"""

from http import HTTPStatus

import server

server.startup()


def application(environ, start_response):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    body = environ["wsgi.input"].read(min(length, server.MAX_BODY)) if length > 0 else b""
    status, payload, content_type = server.respond(
        environ["REQUEST_METHOD"], environ.get("PATH_INFO") or "/",
        environ.get("QUERY_STRING", ""), environ.get("HTTP_X_TOKEN"), body)
    start_response(f"{status} {HTTPStatus(status).phrase}", [
        ("Content-Type", content_type),
        ("Content-Length", str(len(payload))),
        ("Cache-Control", "no-store"),
    ])
    return [payload]
