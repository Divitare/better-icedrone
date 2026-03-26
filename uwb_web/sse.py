"""Server-Sent Events broadcaster for live dashboard updates."""

import json
import queue
import threading


class SSEBroadcaster:
    """Fan-out broadcaster: serial worker publishes, SSE clients subscribe."""

    def __init__(self):
        self._clients = []
        self._lock = threading.Lock()

    def subscribe(self):
        """Generator that yields SSE-formatted strings. Use as Flask streaming response."""
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._clients.append(q)
        try:
            while True:
                try:
                    data = q.get(timeout=15)
                    yield f"data: {json.dumps(data)}\n\n"
                except queue.Empty:
                    # Send heartbeat comment to keep connection alive
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            with self._lock:
                if q in self._clients:
                    self._clients.remove(q)

    def publish(self, data):
        """Push an event to all connected SSE clients."""
        with self._lock:
            dead = []
            for q in self._clients:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._clients.remove(q)

    @property
    def client_count(self):
        with self._lock:
            return len(self._clients)
