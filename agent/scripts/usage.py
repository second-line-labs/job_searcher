"""Usage counter for the feed's outside services (feed fix plan, action 14; budget rule G10).
Counts calls per day in agent/inbox/_usage.json: page reads through Jina, Tavily searches. Scorer tokens are
read from the decisions in the inbox. The digest adds these up for the month."""
import datetime as dt
import io
import json
import os

FILE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "inbox", "_usage.json"))


def add(kind, n=1):
    try:
        d = json.loads(io.open(FILE, encoding="utf-8").read())
    except (OSError, ValueError):
        d = {}
    day = d.setdefault(dt.date.today().isoformat(), {})
    day[kind] = int(day.get(kind, 0)) + n
    try:
        io.open(FILE, "w", encoding="utf-8", newline="\n").write(json.dumps(d, indent=1, sort_keys=True))
    except OSError:
        pass


def month(prefix=None):
    """Totals per kind for the month that starts with prefix ("2026-11"); the current month by default."""
    prefix = prefix or dt.date.today().isoformat()[:7]
    try:
        d = json.loads(io.open(FILE, encoding="utf-8").read())
    except (OSError, ValueError):
        return {}
    out = {}
    for day, kinds in d.items():
        if day.startswith(prefix):
            for k, v in kinds.items():
                out[k] = out.get(k, 0) + int(v)
    return out
