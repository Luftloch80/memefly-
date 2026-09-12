"""Local control panel: edit .env, then build/start/stop the memefly
Docker Compose stack (bot + dashboard).

This is a privileged local tool -- it writes your secrets to disk and
shells out to `docker`/`docker compose` on the host. It binds to
127.0.0.1 by default and requires a startup-generated access token.
Do NOT expose it to the internet or an untrusted network.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session

from panel import env_writer, fields
from panel.jobs import Job

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"

PANEL_TOKEN = os.environ.get("PANEL_TOKEN") or secrets.token_urlsafe(24)

app = Flask(__name__)
app.secret_key = secrets.token_bytes(32)
app.permanent_session_lifetime = timedelta(hours=12)

build_job = Job("build")
start_job = Job("start")
stop_job = Job("stop")


@app.before_request
def check_auth():
    if request.endpoint == "static":
        return None
    if session.get("authed"):
        return None

    supplied = request.args.get("token") or request.headers.get("X-Panel-Token")
    if supplied and secrets.compare_digest(supplied, PANEL_TOKEN):
        session.permanent = True
        session["authed"] = True
        if request.method == "GET" and "token" in request.args:
            return redirect(request.path)
        return None

    if request.path.startswith("/api/"):
        return jsonify({"error": "unauthorized: missing or invalid ?token="}), 401
    return render_template("token_prompt.html"), 401


@app.get("/")
def index():
    existing = env_writer.read_env(ENV_PATH)
    values = env_writer.masked_form_values(existing)
    secret_flags = {name: env_writer.secret_is_set(existing, name) for name in fields.SECRET_FIELDS}
    return render_template(
        "index.html",
        sections=fields.sections(),
        fields_by_section={s: [f for f in fields.FIELDS if f.section == s] for s in fields.sections()},
        values=values,
        secret_flags=secret_flags,
    )


@app.post("/api/env")
def api_save_env():
    updates = env_writer.form_to_env_updates(request.form.to_dict())
    existing = env_writer.read_env(ENV_PATH)
    merged = env_writer.merge_env(existing, updates)
    env_writer.write_env(ENV_PATH, merged)
    return jsonify({"ok": True})


def _run_job(job: Job, cmd: list[str]):
    started = job.run(cmd, cwd=str(REPO_ROOT))
    return jsonify({"started": started, "status": job.snapshot()["status"]})


@app.post("/api/build")
def api_build():
    return _run_job(build_job, ["docker", "compose", "build"])


@app.get("/api/build/status")
def api_build_status():
    return jsonify(build_job.snapshot())


@app.post("/api/start")
def api_start():
    return _run_job(start_job, ["docker", "compose", "up", "-d"])


@app.get("/api/start/status")
def api_start_status():
    return jsonify(start_job.snapshot())


@app.post("/api/stop")
def api_stop():
    return _run_job(stop_job, ["docker", "compose", "down"])


@app.get("/api/stop/status")
def api_stop_status():
    return jsonify(stop_job.snapshot())


@app.get("/api/status")
def api_status():
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return jsonify({"containers": [], "error": "docker was not found on PATH"})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"containers": [], "error": str(exc)})

    if result.returncode != 0:
        return jsonify({"containers": [], "error": result.stderr.strip()})

    raw = result.stdout.strip()
    containers: list[dict] = []
    if raw:
        try:
            parsed = json.loads(raw)
            containers = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            for line in raw.splitlines():
                line = line.strip()
                if line:
                    containers.append(json.loads(line))
    return jsonify({"containers": containers})


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="memefly control panel")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print("\n  memefly control panel")
    print(f"  open: http://{args.host}:{args.port}/?token={PANEL_TOKEN}\n")
    if args.host not in ("127.0.0.1", "localhost"):
        print(
            "  WARNING: binding to a non-localhost address. Anyone who can reach "
            "this port can overwrite your .env and trigger docker builds. Do not "
            "expose this to the internet or an untrusted network.\n"
        )

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
