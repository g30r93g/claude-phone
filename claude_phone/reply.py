"""Claude's last reply in each session, for conversation mode. The Stop hook saves it to
replies/<session_id>.json; the daemon reads it back and speaks it."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import config

DIR = config.HOME / "replies"
MAX_WORDS = 60
MORE = "There's more if you ask."  # the caller can't see a screen, so a cut reply offers the rest


def _path(session_id: str) -> Path:
    return DIR / f"{session_id}.json"


def save(session_id: str, payload: dict) -> None:
    """Called by the Stop hook. Newer Claude Code passes the reply in the payload; older ones only the
    transcript path."""
    text = payload.get("last_assistant_message")
    if not isinstance(text, str):
        text = from_transcript(payload.get("transcript_path"))
    if text is None:
        return
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(session_id).with_suffix(".tmp")
    tmp.write_text(json.dumps({"ts": time.time(), "text": text}))
    tmp.rename(_path(session_id))


def latest(session_id: str) -> tuple[float, str] | None:
    """(when it was saved, text), or None if this session hasn't replied yet."""
    try:
        d = json.loads(_path(session_id).read_text())
        return d["ts"], d["text"]
    except (OSError, ValueError, KeyError):
        return None


def from_transcript(path: str | None, tail_bytes: int = 2_000_000) -> str | None:
    """The text Claude ended its last turn with: the run of assistant text after its last tool call."""
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail_bytes))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    texts: list[str] = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("isSidechain") or e.get("type") not in ("assistant", "user"):
            continue
        content = (e.get("message") or {}).get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        if e["type"] == "user" or any(b.get("type") == "tool_use" for b in blocks):
            break  # the prompt, or a tool call: the final reply is everything after it
        texts[:0] = [b.get("text") or "" for b in blocks if b.get("type") == "text"]
    return "\n\n".join(t for t in texts if t.strip())


def spoken(text: str, max_words: int = MAX_WORDS) -> str:
    """Markdown written for a screen, cut down to a few sentences for the phone. Code, tables and anything
    past max_words are left out, and the reply offers to say more."""
    cut = False
    text, n = re.subn(r"```.*?(```|$)", " ", text, flags=re.S)
    cut |= n > 0
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            cut = True
            continue
        line = re.sub(r"^\s*(#+|[-*+]|\d+[.)])\s+", "", line)
        lines.append(line)
    text = " ".join(lines)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[`*]+", "", text)
    text = text.replace("_", " ")  # call_owner -> "call owner"; also drops _emphasis_ marks
    text = " ".join(text.split())
    words = text.split()
    if len(words) > max_words:
        cut = True
        sentences, total = [], 0
        for s in re.split(r"(?<=[.!?])\s+", text):
            total += len(s.split())
            if sentences and total > max_words:
                break
            sentences.append(s)
        text = " ".join(sentences)
        if len(text.split()) > max_words:  # one long sentence
            text = " ".join(text.split()[:max_words]) + "."
    if not text:
        return "Done. " + MORE
    return f"{text} {MORE}" if cut else text
