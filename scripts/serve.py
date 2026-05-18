"""Tiny static server for the dashboard. Runs from project root."""
import http.server
import os
import socketserver
import sys
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
os.chdir(Path(__file__).resolve().parent.parent)

with socketserver.TCPServer(("127.0.0.1", PORT), http.server.SimpleHTTPRequestHandler) as httpd:
    httpd.allow_reuse_address = True
    print(f"serving on http://127.0.0.1:{PORT}")
    httpd.serve_forever()
