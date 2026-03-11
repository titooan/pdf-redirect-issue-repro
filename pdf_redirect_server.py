#!/usr/bin/env python3

import argparse
import json
import struct
import zlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote
from zipfile import ZIP_DEFLATED, ZipFile


def generate_sample_pdf():
    buffer = BytesIO()

    def write(data):
        buffer.write(data if isinstance(data, bytes) else data.encode("ascii"))

    offsets = []

    def add_object(obj_number: int, body: bytes):
        offsets.append(buffer.tell())
        write(f"{obj_number} 0 obj\n")
        write(body)
        if not body.endswith(b"\n"):
            write(b"\n")
        write(b"endobj\n")

    write("%PDF-1.4\n")

    add_object(1, b"<< /Type /Catalog /Pages 2 0 R >>\n")
    add_object(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n")
    add_object(
        3,
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
        b"<< /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\n",
    )
    add_object(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n")

    stream_data = b"BT\n/F1 24 Tf\n72 720 Td\n(Hello from redirect PDF) Tj\nET\n"
    add_object(
        5,
        f"<< /Length {len(stream_data)} >>\n".encode("ascii")
        + b"stream\n"
        + stream_data
        + b"endstream\n",
    )

    xref_offset = buffer.tell()
    write(f"xref\n0 {len(offsets) + 1}\n")
    write("0000000000 65535 f \n")
    for point in offsets:
        write(f"{point:010d} 00000 n \n")
    write("trailer\n")
    write(f"<< /Size {len(offsets) + 1} /Root 1 0 R >>\n")
    write("startxref\n")
    write(f"{xref_offset}\n")
    write("%%EOF\n")

    return buffer.getvalue(), "redirect-sample.pdf"


def generate_solid_color_png(size: int, rgb: tuple[int, int, int]) -> bytes:
    """Return a PNG with the requested size and solid color."""
    width = height = size
    png_signature = b"\x89PNG\r\n\x1a\n"

    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = bytes(rgb) * width
    raw = b"".join(b"\x00" + row for _ in range(height))
    idat = zlib.compress(raw)
    return png_signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def generate_sample_zip() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("ticket.txt", "Local debug zip-ticket payload.\n")
    return buffer.getvalue()


PWA_ICON_192 = generate_solid_color_png(192, (79, 70, 229))
PWA_ICON_512 = generate_solid_color_png(512, (55, 65, 81))

PWA_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#0f172a">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>PDF Redirect PWA</title>
    <link rel="manifest" href="/pwa/manifest.json">
    <link rel="icon" sizes="192x192" href="/pwa/icon-192.png">
    <link rel="apple-touch-icon" href="/pwa/icon-192.png">
    <style>
      body {{
        margin: 0;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        min-height: 100vh;
        background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
        color: #f8fafc;
        display: flex;
        justify-content: center;
        align-items: center;
        text-align: center;
      }}
      button {{
        font-size: 1.5rem;
        padding: 1.25rem 2rem;
        border-radius: 999px;
        border: none;
        background: #38bdf8;
        color: #0f172a;
        font-weight: 600;
        box-shadow: 0 10px 25px rgba(15, 23, 42, 0.6);
      }}
      button:active {{
        transform: scale(0.98);
      }}
    </style>
    <script>
      if ('serviceWorker' in navigator) {{
        window.addEventListener('load', () => {{
          navigator.serviceWorker.register('/sw.js').catch(console.error);
        }});
      }}
    </script>
  </head>
  <body>
    <main>
      <h1>PDF Redirect Debug PWA</h1>
      <p>Install this PWA, then tap the button to launch the redirect chain.</p>
      <p>
        <button id="load-pdf">Load PDF</button>
      </p>
      <p>
        <button id="load-page">Load Page</button>
      </p>
      <p>
        <button id="open-popup">Open popup</button>
      </p>
      <p>
        <button id="open-ticket">Ticket</button>
      </p>
    </main>
    <script>
      document.getElementById('load-pdf').addEventListener('click', () => {{
        window.location.href = '/start';
      }});
      document.getElementById('load-page').addEventListener('click', () => {{
        window.location.href = '/start-html';
      }});
      document.getElementById('open-popup').addEventListener('click', () => {{
        window.open('/start-popup', 'redirect-popup', 'popup=yes,width=450,height=700');
      }});
      document.getElementById('open-ticket').addEventListener('click', () => {{
        window.location.href = '/ticket';
      }});
    </script>
  </body>
</html>
"""

PWA_MANIFEST = {
    "id": "/pwa/",
    "name": "PDF Redirect Debug",
    "short_name": "PDF Redirect",
    "start_url": "/pwa/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#0f172a",
    "theme_color": "#0f172a",
    "display_override": ["standalone"],
    "icons": [
        {"src": "/pwa/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
        {"src": "/pwa/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}

SW_JS = """self.addEventListener('install', event => {
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener('fetch', event => {
  event.respondWith(fetch(event.request));
});
"""

HTML_REDIRECT_TARGET = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Redirect Target Page</title>
    <style>
      body {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #f8fafc;
        color: #0f172a;
      }
      main {
        text-align: center;
        padding: 2rem;
      }
      a {
        color: #0369a1;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>HTML Redirect Target</h1>
      <p>You reached this page through the same multi-hop redirect pattern as the PDF flow.</p>
      <p><a href="/pwa/">Back to PWA home</a></p>
    </main>
  </body>
</html>
"""

POPUP_REDIRECT_TARGET = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Popup Redirect Target</title>
    <style>
      body {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #111827;
        color: #f9fafb;
      }
      main {
        text-align: center;
        padding: 2rem;
      }
      a {
        color: #38bdf8;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>Popup Redirect Target</h1>
      <p>This page was opened in a popup through a dedicated redirect chain.</p>
      <p><a href="/pwa/">Back to PWA home</a></p>
    </main>
  </body>
</html>
"""


def build_handler(pdf_bytes: bytes, filename: str, zip_bytes: bytes):
    class RedirectingPdfHandler(BaseHTTPRequestHandler):
        server_version = "PdfRedirectServer/1.0"

        def _absolute_location(self, path: str) -> str:
            host = self.headers.get("Host") or f"localhost:{self.server.server_port}"
            return f"http://{host}{path}"

        def _send_redirect(self, next_path: str):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", self._absolute_location(next_path))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK, extra_headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
            request_path = self.path.split("?", 1)[0].split("#", 1)[0]

            if request_path in {"/pwa", "/pwa/"}:
                self._send_bytes(PWA_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return

            if request_path == "/pwa/manifest.json":
                body = json.dumps(PWA_MANIFEST).encode("utf-8")
                self._send_bytes(body, "application/manifest+json; charset=utf-8")
                return

            if request_path == "/pwa/icon-192.png":
                self._send_bytes(PWA_ICON_192, "image/png")
                return

            if request_path == "/pwa/icon-512.png":
                self._send_bytes(PWA_ICON_512, "image/png")
                return

            if request_path == "/sw.js":
                self._send_bytes(SW_JS.encode("utf-8"), "application/javascript; charset=utf-8")
                return

            if request_path == "/start-html":
                self._send_redirect("/redirect-html-1")
                return

            if request_path == "/redirect-html-1":
                self._send_redirect("/redirect-html-2")
                return

            if request_path == "/redirect-html-2":
                self._send_bytes(HTML_REDIRECT_TARGET.encode("utf-8"), "text/html; charset=utf-8")
                return

            if request_path == "/start-popup":
                self._send_redirect("/redirect-popup-1")
                return

            if request_path == "/redirect-popup-1":
                self._send_redirect("/redirect-popup-2")
                return

            if request_path == "/redirect-popup-2":
                self._send_bytes(POPUP_REDIRECT_TARGET.encode("utf-8"), "text/html; charset=utf-8")
                return

            if request_path == "/ticket":
                target = self._absolute_location("/voucher/pdf/local-debug-token==?SPMID=LOCAL_TEST")
                encoded_target = quote(target, safe="")
                self._send_redirect(
                    f"/url?q={encoded_target}&source=gmail&ust=1772968368397000&usg=AOvVawLocalDebugToken"
                )
                return

            if request_path == "/zip-ticket":
                target = self._absolute_location("/voucher/zip/local-debug-token==?SPMID=LOCAL_TEST")
                encoded_target = quote(target, safe="")
                self._send_redirect(
                    f"/url?q={encoded_target}&source=gmail&ust=1772968368397000&usg=AOvVawLocalDebugToken"
                )
                return

            if request_path == "/url":
                query = parse_qs(self.path.partition("?")[2], keep_blank_values=True)
                target_url = query.get("q", [""])[0]
                if target_url:
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", unquote(target_url))
                    self.send_header("Cache-Control", "private")
                    self.send_header("Content-Type", "text/html; charset=UTF-8")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._send_bytes(b"Missing query parameter: q\n", "text/plain; charset=utf-8", HTTPStatus.BAD_REQUEST)
                return

            if request_path.startswith("/voucher/pdf/"):
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="giftcard.pdf"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(pdf_bytes)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(pdf_bytes)
                return

            if request_path.startswith("/voucher/zip/"):
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="ticket.zip"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(zip_bytes)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(zip_bytes)
                return

            if request_path == "/start":
                self._send_redirect("/redirect-1")
                return

            if request_path == "/redirect-1":
                self._send_redirect("/redirect-2")
                return

            if request_path == "/redirect-2":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(pdf_bytes)))
                self.end_headers()
                self.wfile.write(pdf_bytes)
                return

            body = (
                "Endpoints:\n"
                "  /start -> /redirect-1 -> /redirect-2 -> PDF response\n"
                "  /start-html -> /redirect-html-1 -> /redirect-html-2 -> HTML page\n"
                "  /start-popup -> /redirect-popup-1 -> /redirect-popup-2 -> popup HTML page\n"
                "  /ticket -> /url?q=<encoded target> -> /voucher/pdf/... -> attachment download\n"
                "  /zip-ticket -> /url?q=<encoded target> -> /voucher/zip/... -> attachment download\n"
                "Use http://<host>:<port>/start inside the custom tab to reproduce the issue.\n"
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return RedirectingPdfHandler


def main():
    parser = argparse.ArgumentParser(description="Serve a redirect chain that ends with a PDF attachment.")
    parser.add_argument("--pdf", type=Path, help="Path to the PDF that should be returned.")
    parser.add_argument("--port", type=int, default=8765, help="TCP port to listen on (default: 8765).")
    args = parser.parse_args()
    if args.pdf is None:
        pdf_bytes, filename = generate_sample_pdf()
    else:
        pdf_path = args.pdf.resolve(strict=True)
        pdf_bytes, filename = pdf_path.read_bytes(), pdf_path.name
    zip_bytes = generate_sample_zip()
    handler = build_handler(pdf_bytes, filename, zip_bytes)
    with ThreadingHTTPServer(("0.0.0.0", args.port), handler) as httpd:
        print(f"Serving redirects on http://localhost:{args.port}/start")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
