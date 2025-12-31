#!/usr/bin/env python3

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path


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


def build_handler(pdf_bytes: bytes, filename: str):
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

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path.startswith("/start"):
                self._send_redirect("/redirect-1")
                return

            if self.path.startswith("/redirect-1"):
                self._send_redirect("/redirect-2")
                return

            if self.path.startswith("/redirect-2"):
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
    handler = build_handler(pdf_bytes, filename)
    with ThreadingHTTPServer(("0.0.0.0", args.port), handler) as httpd:
        print(f"Serving redirects on http://localhost:{args.port}/start")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
