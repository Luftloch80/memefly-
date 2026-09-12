"""Pure logic for reading/merging/writing the .env file, kept separate
from app.py so it's testable without Flask or the filesystem's real
permission model getting in the way.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from panel.fields import FIELDS, CHECKBOX_FIELDS, SECRET_FIELDS


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def form_to_env_updates(form: dict[str, str]) -> dict[str, str]:
    """Converts raw submitted form values (checkboxes present only when
    checked, everything else as plain strings) into the env values that
    should be applied.
    """
    updates: dict[str, str] = {}
    for f in FIELDS:
        if f.type == "checkbox":
            updates[f.name] = f.on_value if form.get(f.name) else f.off_value
        elif f.name in form:
            updates[f.name] = form[f.name].strip()
    return updates


def merge_env(existing: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    """Applies `updates` onto `existing`, except a blank value for a secret
    field means "leave the current value alone" rather than "clear it" --
    so users aren't forced to re-paste a private key every time they tweak
    an unrelated risk limit.
    """
    merged = dict(existing)
    for key, value in updates.items():
        if key in SECRET_FIELDS and value == "":
            continue
        merged[key] = value
    return merged


def format_env(data: dict[str, str]) -> str:
    lines: list[str] = []
    written: set[str] = set()
    for f in FIELDS:
        if f.name in data:
            lines.append(f"{f.name}={data[f.name]}")
            written.add(f.name)
    for key in sorted(set(data) - written):
        lines.append(f"{key}={data[key]}")
    return "\n".join(lines) + "\n"


def write_env(path: Path, data: dict[str, str]) -> None:
    content = format_env(data)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
    finally:
        os.chmod(path, 0o600)


def masked_form_values(existing: dict[str, str]) -> dict[str, str]:
    """Values to pre-fill the HTML form with: secrets never round-trip to
    the browser, everything else does.
    """
    result: dict[str, str] = {}
    for f in FIELDS:
        value = existing.get(f.name, f.default)
        if f.type == "checkbox":
            result[f.name] = "checked" if value == f.on_value else ""
        elif f.type == "password":
            result[f.name] = ""  # never echo secrets back
        else:
            result[f.name] = value
    return result


def secret_is_set(existing: dict[str, str], name: str) -> bool:
    return bool(existing.get(name))
