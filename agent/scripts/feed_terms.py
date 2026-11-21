"""Shared title rules for the feed (feed fix plan, action 7, option A; 2026-11-15).

One place for the title list, the level rule and the exclusions, read from agent/feed_terms.json and used by
sweep.py, board_scan.py and board_search.py.

    python feed_terms.py --check "Senior Manager, Regulatory Compliance"
    python feed_terms.py --groups        # the LinkedIn search groups built from the title list
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.abspath(os.path.join(HERE, "..", "feed_terms.json"))
_T = None


def terms():
    global _T
    if _T is None:
        d = json.loads(io.open(FILE, encoding="utf-8").read())
        lv, tp = d["level"], d["topic"]
        _T = {
            "raw": d,
            "never": re.compile(lv["never"], re.I),
            "always": re.compile(lv["always"], re.I),
            "mandate": re.compile(lv["with_mandate"], re.I),
            "core": re.compile(tp["core"], re.I),
            "qualified": re.compile(tp["qualified"], re.I),
            "exclude": [(w, re.compile(w, re.I)) for w in d["exclude"]["words"]],
        }
    return _T


DEPARTMENT = re.compile(r"\b(cro|cio|coo)\b", re.I)


def _level_text(s):
    """The title as the level rule reads it. After a dash, CRO, CIO and COO name a department, not the level of the
    posting: "IT Risk & Control Officer - CRO IT & Cyber" is an officer's post (2026-11-20)."""
    parts = re.split(r"\s[-–—|]\s", s, maxsplit=1)
    if len(parts) == 2:
        return parts[0] + " - " + DEPARTMENT.sub(" ", parts[1])
    return s


def check(title, any_level=False):
    """How a posting title is judged.
    Returns {"keep": bool, "level": "always" | "mandate" | "below" | "never", "reason": text}.
    level "mandate" (Senior Manager, Lead, Officer) is kept here and decided by the scorer: it needs a visible
    mandate and "at level". any_level=True skips the level rule (subject and exclusions still apply)."""
    t = terms()
    s = re.sub(r"\(.*?\)", " ", title or "")          # "(m/w/d)", "(Equivalent of AVP)" are read separately below
    full = title or ""
    for word, pat in t["exclude"]:
        if pat.search(full):
            return {"keep": False, "level": "", "reason": "excluded subject: %s" % word.replace("\\b", "")}
    if not (t["core"].search(full) or t["qualified"].search(full)):
        return {"keep": False, "level": "", "reason": "no subject from the list"}
    if t["never"].search(full):
        level, reason = "never", "level never shown: %s" % t["never"].search(full).group(0)
    elif t["always"].search(_level_text(s)):
        level, reason = "always", "level always shown: %s" % t["always"].search(_level_text(s)).group(0)
    elif t["mandate"].search(s):
        level, reason = "mandate", "level shown only with a mandate: %s" % t["mandate"].search(s).group(0).strip()
    else:
        level, reason = "below", "no level word (below Senior Manager)"
    keep = any_level or level in ("always", "mandate")
    return {"keep": keep, "level": level, "reason": reason}


def linkedin_groups():
    """Title groups as LinkedIn search strings: quoted titles joined by OR, at most twelve a group."""
    out = {}
    for name, titles in terms()["raw"]["titles"].items():
        for i in range(0, len(titles), 12):
            key = name if i == 0 else "%s %d" % (name, i // 12 + 1)
            out[key] = " OR ".join('"%s"' % x for x in titles[i:i + 12])
    return out


def board_terms():
    return list(terms()["raw"]["board_terms"])


def all_titles():
    return [x for group in terms()["raw"]["titles"].values() for x in group]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        for x in sys.argv[2:]:
            print(x, "->", check(x))
    elif len(sys.argv) >= 2 and sys.argv[1] == "--groups":
        for k, v in linkedin_groups().items():
            print("%-14s %s" % (k, v))
    else:
        print(__doc__)
