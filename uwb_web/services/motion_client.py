"""TCP client for the isel iMC-S8 motion controller API server."""

import json
import socket
import threading
import time
import logging

logger = logging.getLogger(__name__)

# How long to suppress reconnection attempts after a failure (seconds).
_BACKOFF_SECONDS = 3.0


class MotionClient:
    """Thread-safe TCP client that talks to the isel controller's JSON API."""

    def __init__(self, host='127.0.0.1', port=5001, connect_timeout=2.0,
                 read_timeout=10.0):
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self._lock = threading.Lock()
        self._sock = None
        self._last_fail: float = 0.0  # monotonic timestamp of last connect failure

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self):
        """Open a TCP socket if not already connected."""
        if self._sock is not None:
            return

        # Fast-fail: if we failed recently, don't even try
        if self._last_fail and (time.monotonic() - self._last_fail) < _BACKOFF_SECONDS:
            raise ConnectionRefusedError(
                f'Motion controller at {self.host}:{self.port} unreachable '
                f'(backoff {_BACKOFF_SECONDS}s)'
            )

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Short connect timeout so we don't block the whole server
            sock.settimeout(self.connect_timeout)
            sock.connect((self.host, self.port))
            # After connecting, use the longer read timeout
            sock.settimeout(self.read_timeout)
            self._sock = sock
            self._last_fail = 0.0
        except Exception:
            sock.close()
            self._last_fail = time.monotonic()
            raise

    def _disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _send(self, payload: dict) -> dict:
        """Send a JSON command and read the JSON response (newline-delimited)."""
        with self._lock:
            try:
                self._connect()
                data = json.dumps(payload) + '\n'
                self._sock.sendall(data.encode('utf-8'))

                # Read until we get a complete newline-terminated response
                buf = ''
                while '\n' not in buf:
                    chunk = self._sock.recv(4096)
                    if not chunk:
                        raise ConnectionError('Server closed connection')
                    buf += chunk.decode('utf-8')
                line = buf.split('\n', 1)[0]
                return json.loads(line)
            except Exception:
                self._disconnect()
                raise

    # ------------------------------------------------------------------
    # Public API — mirrors the isel ApiServer commands
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        return self._send({'cmd': 'get_status'})

    def get_position(self) -> dict:
        return self._send({'cmd': 'get_pos'})

    def init_axes(self, wait=True) -> dict:
        return self._send({'cmd': 'init', 'wait_ready': wait})

    def home(self, speed=12.5, wait=True) -> dict:
        return self._send({'cmd': 'home', 'speed': speed, 'wait_ready': wait})

    def move_absolute(self, x, y, z, speed=5.0, wait=False) -> dict:
        return self._send({
            'cmd': 'move_abs', 'x': x, 'y': y, 'z': z,
            'speed': speed, 'wait_ready': wait,
        })

    def move_relative(self, x, y, z, speed=5.0, wait=False) -> dict:
        return self._send({
            'cmd': 'move_rel', 'x': x, 'y': y, 'z': z,
            'speed': speed, 'wait_ready': wait,
        })

    def stop(self) -> dict:
        return self._send({'cmd': 'stop'})

    def set_acceleration(self, accel) -> dict:
        return self._send({'cmd': 'set_acceleration', 'accel': accel})

    def start_grid(self, grid_cfg: dict) -> dict:
        payload = {'cmd': 'grid'}
        payload.update(grid_cfg)
        return self._send(payload)

    def close(self):
        self._disconnect()
        self._last_fail = 0.0
