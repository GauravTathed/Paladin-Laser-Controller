"""Send confirmed Paladin shutter readings over an authenticated Pi connection."""

import base64
import hashlib
import hmac
from queue import Empty, Full, Queue
from threading import Event, Thread
import time

import paramiko


PI_HOST = "welcome-pi.local"
PI_KEY = "SHA256:dAcXH2+ROWLkrjy/4FWcblc7zwxDLwfrI1IewuT/nCk"
RECEIVER = "/usr/bin/python3 -B /home/pi/lab-status-display/paladin_shutter.py"
MAX_QUEUED_AGE = 2
SSH_TIMEOUT = 5


class PiHostKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, _client, _hostname, key):
        digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if not hmac.compare_digest(f"SHA256:{digest}", PI_KEY):
            raise paramiko.SSHException("The SSH host key does not match welcome-pi.")


def ed25519_transport(*args, **kwargs):
    transport = paramiko.Transport(*args, **kwargs)
    transport.get_security_options().key_types = ("ssh-ed25519",)
    return transport


class DoorSign:
    def __init__(self):
        self.session = None
        self.events = Queue()

    def connect(self, host, port, user, password):
        self.disconnect()
        self.session = session = DoorSession()
        Thread(
            target=session.run, args=(host, port, user, password, self.events),
            daemon=True, name="qudit-shutter-status",
        ).start()

    def disconnect(self):
        if self.session is not None:
            self.session.stop.set()
            self.session = None

    def report(self, reading):
        session = self.session
        if session is None or session.stop.is_set():
            return
        try:
            session.pending.get_nowait()
        except Empty:
            pass
        try:
            session.pending.put_nowait((time.monotonic(), reading))
        except Full:
            pass

    def status(self):
        while True:
            try:
                session, kind, message = self.events.get_nowait()
            except Empty:
                return None
            if session is self.session:
                if kind == "closed":
                    self.session = None
                return kind, message


class DoorSession:
    def __init__(self):
        self.stop = Event()
        self.pending = Queue(maxsize=1)

    def run(self, host, port, user, password, events):
        try:
            with paramiko.SSHClient() as client:
                client.set_missing_host_key_policy(PiHostKey())
                client.connect(
                    host, port=port, username=user, password=password,
                    allow_agent=False, look_for_keys=False, timeout=SSH_TIMEOUT,
                    banner_timeout=SSH_TIMEOUT, auth_timeout=SSH_TIMEOUT,
                    transport_factory=ed25519_transport,
                )
                del password
                if self.stop.is_set():
                    return
                self.send(client, "probe")
                events.put((self, "connected", f"Connected to {host}"))
                transport = client.get_transport()
                while not self.stop.is_set():
                    if not transport.is_active():
                        raise ConnectionError("The Pi closed the SSH connection.")
                    try:
                        sampled, reading = self.pending.get(timeout=0.25)
                    except Empty:
                        continue
                    if not self.stop.is_set():
                        self.send(client, reading, sampled_at=sampled)
        except paramiko.AuthenticationException:
            events.put((self, "closed", "SSH sign-in failed. Check the Pi username and password."))
        except (OSError, EOFError, paramiko.SSHException, ValueError) as error:
            events.put((self, "closed", str(error) or type(error).__name__))

    def send(self, client, message, *, sampled_at=None):
        stdin, stdout, stderr = client.exec_command(RECEIVER, timeout=SSH_TIMEOUT)
        with stdout.channel, stdin, stdout, stderr:
            if self.stop.is_set():
                return
            if sampled_at is not None and time.monotonic() - sampled_at >= MAX_QUEUED_AGE:
                message = "sim-unknown" if message.startswith("sim-") else "unknown"
            stdin.write(message + "\n")
            stdin.flush()
            stdin.channel.shutdown_write()
            if stdout.readline(16).strip() != "OK":
                raise ConnectionError("The Pi did not acknowledge the shutter message. Check that the door dashboard is installed.")


def verified_shutter(response):
    if response.fault_code != 0 or not response.raw.strip().endswith(";"):
        return "unknown"
    return {"0": "closed", "1": "open"}.get(response.value.strip(), "unknown")
