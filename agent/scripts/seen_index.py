"""Shared "already seen" index for the feed (feed fix plan, action 1, option A; 2026-11-15).

One index for sweep.py, board_scan.py and every session. A posting counts as seen when
  - its link is already known, or
  - an earlier posting has the same company, the same title and the same city.
The same title at another company is never a duplicate.

The index is rebuilt from the inbox files on every load (they are the record all sessions share), plus the
links in the legacy agent/inbox/_seen.json. A copy is written to agent/inbox/_index.json for inspection.

    python seen_index.py            # rebuild and print a summary
    python seen_index.py --check "Company" "Title" "City" [url]
"""
import datetime as dt
import glob
import html
import io
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import intake  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.abspath(os.path.join(HERE, "..", "inbox"))
LEGACY = os.path.join(INBOX, "_seen.json")
COPY = os.path.join(INBOX, "_index.json")
KEY_MAX_AGE_DAYS = 45  # an identical posting older than this may be a re-opened role; the link still blocks

UNKNOWN = {"", "unknown", "n a", "na", "confidential"}
LEGAL = re.compile(r"\b(gmbh|ag|se|sa|s a|plc|ltd|limited|llc|inc|nv|n v|bv|b v|sarl|s a r l|kg|kgaa|co|cie|et cie|"
                   r"holding|holdings|group|gruppe)\b")
GENDER = re.compile(r"\(?\b(m\s*/\s*w\s*/\s*d|m\s*/\s*f\s*/\s*d|f\s*/\s*m\s*/\s*d|w\s*/\s*m\s*/\s*d|m\s*/\s*f\s*/\s*x|"
                    r"f\s*/\s*m\s*/\s*x|m\s*/\s*w\s*/\s*x|all genders|mfxd|gn)\b\)?", re.I)
SUFFIX = re.compile(r"\s+(?:bei|at|chez|bij|presso|en)\s+.+$", re.I)  # "... bei Company — City" on localised board pages
CITY = {
    "frankfurt am main": "frankfurt", "frankfurt main": "frankfurt", "frankfurt a main": "frankfurt",
    "zuerich": "zurich", "zurich": "zurich", "muenchen": "munich", "munchen": "munich", "genf": "geneva",
    "geneve": "geneva", "wien": "vienna", "koeln": "cologne", "koln": "cologne", "luxemburg": "luxembourg",
    "duesseldorf": "dusseldorf", "den haag": "the hague", "bruxelles": "brussels", "bruessel": "brussels",
    "brussel": "brussels", "mailand": "milan", "milano": "milan",
}


def _ascii(s):
    s = (s or "").replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    s = s.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", _ascii(s).lower()).strip()


def canon_url(url):
    url = html.unescape((url or "").strip())  # "&amp;" in a copied link is the same link
    m = re.search(r"linkedin\.com/jobs/view/(?:[^/?#]*-)?(\d{8,})", url)
    if m:
        return "https://www.linkedin.com/jobs/view/" + m.group(1)
    url = url.split("#")[0]
    if not re.search(r"[?&](id|jobid|job_id|gh_jid|jk|Id)=", url, re.I):  # keep the query when it carries the job id
        url = url.split("?")[0]
    url = re.sub(r"(/job/\d{4,})/[^/?#]+/?$", r"\1", url)  # /job/109891/Senior-Risk-Manager -> /job/109891
    return url.rstrip("/")


GEO = re.compile(r"\b(deutschland|germany|europe|european|emea|schweiz|switzerland|ireland|luxembourg|international|"
                 r"frankfurt branches|frankfurt|continental)\b")
ALIAS = [(re.compile(r"^(jpmorgan ?chase|jpmorganchase|j p morgan|jp morgan|jpmorgan)\b.*"), "jpmorgan"),
         (re.compile(r"^(bny mellon|bny|bank of new york mellon)\b.*"), "bny"),
         (re.compile(r"^(citibank|citigroup|citi)\b.*"), "citi"),
         (re.compile(r"^(mufg)\b.*"), "mufg"),
         (re.compile(r"^(allianz)\b.*"), "allianz"), (re.compile(r"^solvd\b.*"), "allianz"),
         (re.compile(r"^(hsbc)\b.*"), "hsbc"), (re.compile(r"^(julius baer|julius bar)\b.*"), "julius baer"),
         (re.compile(r"^(amazon)\b.*"), "amazon"), (re.compile(r"^(generali)\b.*"), "generali"),
         (re.compile(r"^(nomura)\b.*"), "nomura"), (re.compile(r"^(banque )?pictet\b.*"), "pictet"),
         (re.compile(r"^six\b.*"), "six"), (re.compile(r"^(ubs)\b.*"), "ubs")]


def norm_company(s):
    """Employer name for matching. Local-entity words are dropped ("Julius Baer Deutschland" = "Julius Baer")
    and large groups get one name. The legal entity still matters for the repeat-employer rule; that rule
    reads the original name, not this one."""
    c = LEGAL.sub(" ", norm(re.sub(r"\(.*?\)", " ", s or "")))
    c = re.sub(r"\s+", " ", GEO.sub(" ", c)).strip()
    for pat, name in ALIAS:
        if pat.match(c):
            return name
    return "" if c in UNKNOWN else c


def norm_title(s):
    t = re.sub(r"\(.*?\)", " ", s or "")
    t = GENDER.sub(" ", t)
    head = SUFFIX.sub("", t)
    if len(head.split()) >= 2:
        t = head
    t = re.sub(r"\b\d{2,3}\s*(?:-|–|to|bis)?\s*\d{0,3}\s*%", " ", t)
    t = re.sub(r"\s[-–]\s(cdi|cdd|unbefristet|permanent|festanstellung)\b.*$", " ", t, flags=re.I)
    return norm(t)


def norm_city(s):
    # a known city anywhere in the text wins ("Zurich Head Cyber Security", "Zurich, CH, Switzerland" -> zurich)
    try:
        known = intake.place_fields(s or "")[0]
    except Exception:  # noqa: BLE001
        known = ""
    if known:
        k = norm(known)
        return CITY.get(k, k)
    c = norm(re.split(r"[,;/|(]| - | – | — ", s or "")[0])
    c = re.sub(r"\b(germany|deutschland|switzerland|schweiz|suisse|luxembourg lu|area|region|greater|metropolitan)\b", " ", c)
    c = re.sub(r"\s+", " ", c).strip()
    return CITY.get(c, c)


def same_company(a, b):
    """Two normalised employer names are one employer when they are equal with spaces ignored ("TX Logistik" and
    "TXLOGISTIK", 2026-11-18), or when one contains the other as whole words and the shorter one has at least six
    letters ("Bitstamp by Robinhood" and "Robinhood", 2026-11-20). Used only together with an equal title."""
    if not a or not b:
        return False
    if a.replace(" ", "") == b.replace(" ", ""):
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short.replace(" ", "")) >= 6 and re.search(r"(^| )%s( |$)" % re.escape(short), long_) is not None


class Index:
    def __init__(self, records):
        self.records = records
        self.urls = {r["url"] for r in records if r.get("url")}

    def seen(self, url="", company="", title="", city="", strict_city=False, today=None):
        """strict_city=True (careers sites): the city must be known on both sides and equal.
        strict_city=False (job boards): an unknown city on either side still counts as the same role."""
        return self.match(url, company, title, city, strict_city, today) is not None

    def match(self, url="", company="", title="", city="", strict_city=False, today=None):
        u = canon_url(url)
        if u and u in self.urls:
            return {"why": "same link", "url": u}
        co, ti, ci = norm_company(company), norm_title(title), norm_city(city)
        if not co or not ti:
            return None
        today = today or dt.date.today()
        for r in self.records:
            if r.get("title_n") != ti or not same_company(r.get("company_n", ""), co):
                continue
            rc = r.get("city_n", "")
            if strict_city:
                if not ci or not rc or ci != rc:
                    continue
            elif ci and rc and ci != rc:
                continue
            try:
                age = (today - dt.date.fromisoformat((r.get("date") or "")[:10])).days
            except ValueError:
                age = 0
            if age > KEY_MAX_AGE_DAYS:
                continue
            return {"why": "same company, title and city", "file": r.get("file", ""), "url": r.get("url", "")}
        return None

    def add(self, url="", company="", title="", city="", date="", file=""):
        rec = {"url": canon_url(url), "company": company, "title": title, "city": city,
               "company_n": norm_company(company), "title_n": norm_title(title), "city_n": norm_city(city),
               "date": date or dt.date.today().isoformat(), "file": file}
        self.records.append(rec)
        if rec["url"]:
            self.urls.add(rec["url"])
        return rec


def _front_matter(path):
    text = io.open(path, encoding="utf-8", errors="ignore").read(4000)
    if not text.startswith("---"):
        return {}
    fm = text.split("---", 2)[1]
    out = {}
    for line in fm.splitlines():
        m = re.match(r"^([a-z_]+):[ \t]*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def load(write_copy=True):
    idx = Index([])
    for f in sorted(glob.glob(os.path.join(INBOX, "*.md"))):
        fm = _front_matter(f)
        if not fm.get("source") and not fm.get("title"):
            continue
        idx.add(url=fm.get("source", ""), company=fm.get("company", ""), title=fm.get("title", ""),
                city=fm.get("location", ""), date=fm.get("captured", "") or os.path.basename(f)[:10],
                file=os.path.basename(f))
    if os.path.exists(LEGACY):
        try:
            for u in json.loads(io.open(LEGACY, encoding="utf-8").read()):
                cu = canon_url(u)
                if cu and cu not in idx.urls:
                    idx.add(url=cu, date="", file="_seen.json")
        except (ValueError, OSError):
            pass
    if write_copy:
        try:
            io.open(COPY, "w", encoding="utf-8", newline="\n").write(
                json.dumps({"built": dt.datetime.now().isoformat(timespec="seconds"), "records": idx.records},
                           ensure_ascii=False, indent=1))
        except OSError:
            pass
    return idx


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ix = load()
    if len(sys.argv) >= 5 and sys.argv[1] == "--check":
        print(ix.match(sys.argv[5] if len(sys.argv) > 5 else "", sys.argv[2], sys.argv[3], sys.argv[4]))
    else:
        keyed = sum(1 for r in ix.records if r["company_n"] and r["title_n"])
        print("index: %d records, %d links, %d with company and title, %d link-only"
              % (len(ix.records), len(ix.urls), keyed, len(ix.records) - keyed))
