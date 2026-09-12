"""Runs a shell-free subprocess (docker compose build/up/down) in a
background thread and captures its output for the UI to poll.
"""
from __future__ import annotations

import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Job:
    name: str
    status: str = "idle"  # idle | running | success | failed
    logs: deque = field(default_factory=lambda: deque(maxlen=2000))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self._lock:
            return {"name": self.name, "status": self.status, "logs": list(self.logs)}

    def run(self, cmd: list[str], cwd: str) -> bool:
        """Starts the command in a background thread. Returns False without
        starting anything if this job is already running.
        """
        with self._lock:
            if self.status == "running":
                return False
            self.status = "running"
            self.logs.clear()
            self.logs.append(f"$ {' '.join(cmd)}")

        thread = threading.Thread(target=self._execute, args=(cmd, cwd), daemon=True)
        thread.start()
        return True

    def _execute(self, cmd: list[str], cwd: str) -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                with self._lock:
                    self.logs.append(line.rstrip("\n"))
            returncode = proc.wait()
            with self._lock:
                self.status = "success" if returncode == 0 else "failed"
                self.logs.append(f"[exit code {returncode}]")
        except FileNotFoundError as exc:
            with self._lock:
                self.status = "failed"
                self.logs.append(f"[error] {exc}")
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.status = "failed"
                self.logs.append(f"[unexpected error] {exc}")
