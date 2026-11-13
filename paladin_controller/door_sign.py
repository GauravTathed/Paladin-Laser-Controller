"""Publish verified shutter status to the QuDit sign without touching RS-232."""

from pathlib import Path
import os
from queue import Empty, Queue
import subprocess
from threading import Thread
import time


CONFIG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "QuDitPaladin"
MAX_QUEUED_AGE = 2


class DoorSign:
    def __init__(self, config=CONFIG):
        self.config = config
        self.pending = Queue(maxsize=1)
        self.results = Queue()
        self.enabled = os.name == "nt" and all(
            (config / name).is_file() for name in ("shutter_ed25519", "known_hosts")
        )
        if self.enabled:
            Thread(target=self.run, daemon=True, name="qudit-shutter-status").start()

    def report(self, reading):
        if not self.enabled:
            return
        try:
            self.pending.get_nowait()
        except Empty:
            pass
        self.pending.put_nowait((time.monotonic(), reading))

    def run(self):
        last_result = None
        while True:
            sampled, reading = self.pending.get()
            simulated = reading.startswith("sim-")
            if time.monotonic() - sampled >= MAX_QUEUED_AGE:
                reading = "sim-unknown" if simulated else "unknown"
            delivered = self.send(reading)
            result = ("simulation" if simulated else "reading", delivered)
            if last_result != result:
                self.results.put(result)
                last_result = result

    def check(self):
        Thread(target=lambda: self.results.put(("probe", self.send("probe"))),
               daemon=True, name="qudit-door-link-test").start()

    def send(self, message):
        try:
            result = subprocess.run(
                [
                    "ssh.exe", "-F", "NUL", "-T", "-i", str(self.config / "shutter_ed25519"),
                    "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                    "-o", "PasswordAuthentication=no", "-o", "ConnectTimeout=2",
                    "-o", "StrictHostKeyChecking=yes",
                    "-o", f'UserKnownHostsFile="{self.config / "known_hosts"}"',
                    "pi@welcome-pi.local", "shutter-status",
                ],
                input=(message + "\n").encode("ascii"), capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and result.stdout.strip() == b"OK"

    def status(self):
        try:
            return self.results.get_nowait()
        except Empty:
            return None


def verified_shutter(response):
    if response.fault_code != 0 or not response.raw.strip().endswith(";"):
        return "unknown"
    return {"0": "closed", "1": "open"}.get(response.value.strip(), "unknown")
