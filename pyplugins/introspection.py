import os
import subprocess
import threading
import queue
from collections import Counter
import math
import time
from penguin import plugins, Plugin
import itertools
import string
import yaml
import asyncio
import traceback
import socket
import sys

class Instrospection(Plugin):
    def __init__(self):
        self.text = "hello world"
        print("My plugin is initialized!!!")
        sys.stdout.flush()

        # 1) Start a thread on __init__ that runs a TCP listener
        self._server_thread = threading.Thread(
            target=self._start_tcp_listener,
            name="InstrospectionTCP",
            daemon=True,
        )
        self._server_thread.start()

    # 2) TCP listener on port 9999 speaking a minimal HTTP/1.1 protocol
    def _start_tcp_listener(self):
        host = "0.0.0.0"
        port = 9999

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((host, port))
            srv.listen(5)
            print(f"[Instrospection] TCP listener started on {host}:{port}", flush=True)
        except Exception as e:
            print(f"[Instrospection] Failed to bind {host}:{port}: {e}", flush=True)
            return

        while True:
            try:
                conn, addr = srv.accept()
                # Handle each client in its own tiny handler thread
                threading.Thread(
                    target=self._handle_client, args=(conn, addr), daemon=True
                ).start()
            except Exception as e:
                print(f"[Instrospection] accept() failed: {e}", flush=True)

    def _handle_client(self, conn: socket.socket, addr):
        try:
            conn.settimeout(10)
            # Read until end of HTTP headers (very small/for demo)
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\r\n\r\n" in data:
                    break

            # 3) On any request, call dostuff()
            result = self.dostuff()
            if result is None:
                result = "OK"
            body_bytes = result.encode("utf-8", errors="replace")

            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                + f"Content-Length: {len(body_bytes)}\r\n".encode()
                + b"Connection: close\r\n"
                b"\r\n"
                + body_bytes
            )
            conn.sendall(response)
        except Exception as e:
            err = f"Error: {e}".encode()
            try:
                conn.sendall(
                    b"HTTP/1.1 500 Internal Server Error\r\n"
                    b"Content-Type: text/plain; charset=utf-8\r\n"
                    + f"Content-Length: {len(err)}\r\n".encode()
                    + b"Connection: close\r\n\r\n"
                    + err
                )
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # Removed unused args; now returns text so the HTTP handler can reply with it
    def dostuff(self) -> str:
        try:
            lines = ["okay reading from target system"]
            proc = subprocess.Popen(
                ["python3", "/igloo_static/guesthopper/guest_cmd.py", "cat", "/etc/passwd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = proc.communicate()

            if stdout:
                lines.append(stdout)
            if stderr:
                lines.append(stderr)

            out = "\n".join(lines)
            print(out, flush=True)  # still log to stdout as before
            return out
        except Exception as e:
            # Always show the main error
            print("Error:", e, flush=True)

            # Then show the underlying cause/context, if any
            cause = e.__cause__ or e.__context__
            if cause:
                print("Caused by:", repr(cause), flush=True)
                traceback.print_exception(type(cause), cause, cause.__traceback__)
            else:
                # No chained exception; print the original traceback
                traceback.print_exception(type(e), e, e.__traceback__)

            return f"Error: {e}"
