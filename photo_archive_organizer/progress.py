import threading
from datetime import datetime


class ProgressReporter:
    """Independent heartbeat remains active during a single slow read/subprocess."""
    def __init__(self, interval, log_path):
        self.interval, self.log_path = interval, log_path
        self.stage, self.detail = "START", ""
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._thread = None
        self.error = None

    def emit(self, message):
        line = f"{datetime.now().isoformat(timespec='seconds')} [{self.stage}] {message}"
        with self._lock:
            print(line, flush=True)
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def set_stage(self, stage, detail=""):
        self.stage, self.detail = stage, detail
        self.emit(detail or "started")

    def update(self, detail):
        self.detail = detail

    def _heartbeat(self):
        while not self._done.wait(self.interval):
            try:
                self.emit(self.detail or "working")
            except OSError as exc:
                self.error = exc
                return

    def start(self):
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()

    def close(self):
        self._done.set()
        if self._thread:
            self._thread.join()
