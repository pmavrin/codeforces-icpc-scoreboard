"""Bounded HTTP reads of public scoreboard URLs, without access to private networks."""

import http.client
import ipaddress
import socket
import ssl
import urllib.parse
import urllib.error
from email.message import Message


MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def public_connection(address, timeout=12, source_address=None):
    host, port = address
    records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not records or any(not ipaddress.ip_address(record[4][0]).is_global for record in records):
        raise ValueError("Scoreboard URLs must resolve to public Internet addresses.")
    # Connect directly to the validated address so DNS cannot change between validation and connection.
    last_error = None
    for family, kind, protocol, _, sockaddr in records:
        connection = socket.socket(family, kind, protocol)
        try:
            connection.settimeout(timeout)
            connection.connect(sockaddr)
            return connection
        except OSError as error:
            last_error = error
            connection.close()
    raise last_error or OSError("No reachable public address")


def read_public_html(url):
    for _ in range(6):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            raise ValueError("A public HTTP or HTTPS scoreboard URL is required.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URLs containing credentials are not supported.")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in (80, 443):
            raise ValueError("Public scoreboard URLs must use port 80 or 443.")
        if parsed.scheme == "https":
            connection = http.client.HTTPSConnection(parsed.hostname, port, timeout=12, context=ssl.create_default_context())
        else:
            connection = http.client.HTTPConnection(parsed.hostname, port, timeout=12)
        connection._create_connection = public_connection
        try:
            target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            connection.request("GET", target, headers={
                "Accept": "text/html,*/*;q=0.8", "User-Agent": "ICPC-TV-Scoreboard/1.0",
            })
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Scoreboard redirect has no destination.")
                url = urllib.parse.urljoin(url, location)
                continue
            if response.status >= 400:
                raise urllib.error.HTTPError(url, response.status, response.reason, response.headers, None)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Scoreboard HTML exceeds the 8 MiB size limit.")
            content_type = Message()
            content_type["Content-Type"] = response.getheader("Content-Type", "text/html")
            charset = content_type.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
        finally:
            connection.close()
    raise ValueError("Too many scoreboard redirects.")
