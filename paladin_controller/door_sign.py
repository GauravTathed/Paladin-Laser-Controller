"""Publish verified shutter status to the QuDit sign without touching RS-232."""

from contextlib import ExitStack
import os
from pathlib import Path
from queue import Empty, Queue
import socket
from threading import Thread
import time

import paramiko


CONFIG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "QuDitPaladin"
MAX_QUEUED_AGE = 2
SSH_TIMEOUT = 5
PI_HOST = "welcome-pi.local"


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
            error = self.send(reading, sampled_at=sampled)
            result = ("simulation" if simulated else "reading", error)
            if last_result != result:
                self.results.put(result)
                last_result = result

    def check(self):
        Thread(target=lambda: self.results.put(("probe", self.send("probe"))),
               daemon=True, name="qudit-door-link-test").start()

    def send(self, message, *, sampled_at=None):
        try:
            with ExitStack() as stack:
                address = PI_HOST
                ssh_config = self.config / "setup-ssh.conf"
                if ssh_config.is_file():
                    config = paramiko.SSHConfig.from_path(str(ssh_config))
                    address = config.lookup(PI_HOST).get("hostname", PI_HOST)
                sock = None
                if address != PI_HOST:
                    sock = stack.enter_context(socket.create_connection((address, 22), timeout=SSH_TIMEOUT))
                client = stack.enter_context(paramiko.SSHClient())
                client.load_host_keys(str(self.config / "known_hosts"))
                client.connect(
                    PI_HOST, username="pi", key_filename=str(self.config / "shutter_ed25519"),
                    allow_agent=False, look_for_keys=False, timeout=SSH_TIMEOUT,
                    banner_timeout=SSH_TIMEOUT, auth_timeout=SSH_TIMEOUT, sock=sock,
                )
                stdin, stdout, _stderr = client.exec_command("shutter-status", timeout=SSH_TIMEOUT)
                if sampled_at is not None and time.monotonic() - sampled_at >= MAX_QUEUED_AGE:
                    message = "sim-unknown" if message.startswith("sim-") else "unknown"
                stdin.write(message + "\n")
                stdin.flush()
                stdin.channel.shutdown_write()
                if stdout.readline(16).strip() == "OK":
                    return None
                return "The Pi did not acknowledge the shutter message."
        except paramiko.AuthenticationException:
            return "The Pi rejected the lab PC's SSH key."
        except (OSError, EOFError, paramiko.SSHException, ValueError) as error:
            return str(error) or type(error).__name__

    def status(self):
        try:
            return self.results.get_nowait()
        except Empty:
            return None


def verified_shutter(response):
    if response.fault_code != 0 or not response.raw.strip().endswith(";"):
        return "unknown"
    return {"0": "closed", "1": "open"}.get(response.value.strip(), "unknown")
