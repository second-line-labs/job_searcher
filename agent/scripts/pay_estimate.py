"""Free pay estimate for postings without a published salary (feed fix plan, action 15, option A; decision G3).

No outside call. Reads the posting only: title level, years of experience asked, employer type, place, and a job
board's own salary prediction when the capture carries one (front matter "pay_hint", for example from StepStone).
The result is rough by design. "likely below walk-away" moves a Go to Stretch; it never drops a role.

    python pay_estimate.py <inbox item.md> [...]
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import feed_terms  # noqa: E402

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "twelve": 12, "fifteen": 15, "zwei": 2, "drei": 3, "vier": 4, "fuenf": 5, "fünf": 5, "sechs": 6, "sieben": 7,
         "acht": 8, "zehn": 10}
NUM = r"(\d{1,2}|" + "|".join(WORDS) + r")"
YEARS = re.compile(NUM + r"\s*(?:\+|plus|-plus|or more)?\s*(?:-|–|to|bis)?\s*(?:\d{1,2})?\s*\+?\s*(?:years?|yrs|jahre[n]?)\b", re.I)
VAGUE = re.compile(r"\b(several|some|a few|mehrj[aä]hrige|mehrere|einige|first|erste)\b[^.\n]{0,25}\b(years?|jahre|experience|berufserfahrung)", re.I)
PUBLIC = re.compile(r"\b(TV[oö]D|TV-L|Entgeltgruppe|\bE ?1[0-5]\b|Besoldung|[oö]ffentliche[rn]? Dienst|semi.?overheid|public sector pay)\b", re.I)
STARTUP = re.compile(r"\b(start-?up|scale-?up|series [abc]\b|seed[- ]stage|early[- ]stage|vc[- ]backed)\b", re.I)
HIGH_SECTOR = re.compile(r"banking|asset and wealth|market infrastructure|big tech|insurance|european central bank", re.I)
LOW_PLACE = re.compile(r"\b(berlin|leipzig|dresden|erfurt|bremen|graz|linz)\b", re.I)


YEARS_EXP = [
    # "8+ years of relevant experience", "ten years' experience", "5 years in a similar role"
    re.compile(NUM + r"\s*(?:\+|plus|-plus|or more)?\s*(?:-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*(?:years?|yrs)['’]?(?:\s+of)?(?:\s+[\w/&-]+){0,4}?\s+(?:experience|expertise|in a|in an|in the|working)", re.I),
    # "at least 8 years", "minimum of 10 years", "experience of 8 years"
    re.compile(r"(?:at least|minimum(?: of)?|min\.|more than|over|experience of)\s+" + NUM + r"\s*\+?\s*(?:years?|yrs)\b(?!\s+ago)", re.I),
    # "mindestens 8 Jahre", "8 Jahre Berufserfahrung", "mehr als 10 Jahre Erfahrung"
    re.compile(r"(?:mindestens|mehr als|über|ueber)\s+" + NUM + r"\s*\+?\s*jahre[n]?", re.I),
    re.compile(NUM + r"\s*\+?\s*jahre[n]?(?:\s+[\wäöüß/&-]+){0,3}?\s+(?:berufserfahrung|erfahrung|praxis)", re.I),
]
HISTORY = re.compile(r"(for more than|for over|since|seit|founded|gegr[uü]ndet|history|tradition|anniversary|revolutioni[sz]ing|has been)", re.I)


def years_asked(body):
    """Highest number of years of experience the posting asks for, or None. A number counts only when it is tied
    to experience ("8+ years of experience", "mindestens 8 Jahre"); company history ("for more than 25 years") does not."""
    own = re.split(r"(Similar jobs|People also viewed|More jobs like this)", body or "")[0]
    found = []
    for pat in YEARS_EXP:
        for m in pat.finditer(own):
            if HISTORY.search(own[max(0, m.start() - 45): m.start() + 12]):
                continue
            v = m.group(1).lower()
            n = int(v) if v.isdigit() else WORDS.get(v)
            if n and 1 <= n <= 25:
                found.append(n)
    return max(found) if found else None


def walkaway(meta, c):
    cur = "CHF" if re.search(r"\bCH\b", meta.get("country", "")) else "EUR"
    wa = c["compensation"]["permanent_walkaway"]
    return wa.get(cur, wa.get("EUR")), cur


def estimate(meta, body, c):
    """{"verdict": "published" | "likely below walk-away" | "likely at or above walk-away" | "unclear",
        "score": int, "basis": [text, ...]}"""
    if (meta.get("salary_max") or "").strip() or (meta.get("salary_min") or "").strip():
        return {"verdict": "published", "score": 0, "basis": ["the posting states its pay"]}
    if str(meta.get("track", "")).lower() == "project":
        return {"verdict": "unclear", "score": 0, "basis": ["project role: the day rate decides, ask the agency"]}
    score, basis = 0, []
    wa, cur = walkaway(meta, c)
    hint = re.search(r"(\d{4,7})\s*(?:-|–|to)\s*(\d{4,7})\s*(EUR|CHF|GBP|USD)?", (meta.get("pay_hint") or "").replace(",", "").replace(".", ""))
    if hint:
        lo, hi = int(hint.group(1)), int(hint.group(2))
        if hi < wa:
            score -= 3
            basis.append("job board predicts %s to %s, below your walk-away of %s %s" % (format(lo, ","), format(hi, ","), cur, format(wa, ",")))
        elif lo >= wa:
            score += 3
            basis.append("job board predicts %s to %s, at or above your walk-away" % (format(lo, ","), format(hi, ",")))
        else:
            basis.append("job board predicts %s to %s, which straddles your walk-away" % (format(lo, ","), format(hi, ",")))
    level = feed_terms.check(meta.get("title", ""), any_level=True)["level"]
    if level in ("never", "below"):
        score -= 2
        basis.append("title below Senior Manager level")
    elif level == "mandate":
        score -= 1
        basis.append("Senior Manager, Lead or Officer title")
    elif level == "always":
        score += 1
        basis.append("head-level title")
    yrs = years_asked(body)
    if yrs is not None:
        if yrs < 6:
            score -= 2
            basis.append("asks for %d years of experience" % yrs)
        elif yrs < 8:
            score -= 1
            basis.append("asks for %d years of experience" % yrs)
        elif yrs >= 15:
            score += 2
            basis.append("asks for %d years of experience" % yrs)
        elif yrs >= 10:
            score += 1
            basis.append("asks for %d years of experience" % yrs)
        else:
            basis.append("asks for %d years of experience" % yrs)
    elif VAGUE.search(body or ""):
        score -= 1
        basis.append("asks only for \"several years\" of experience")
    own = re.split(r"(Similar jobs|People also viewed)", body or "")[0]
    if PUBLIC.search(own):
        score -= 2
        basis.append("public-sector pay scale named")
    if STARTUP.search(own) or re.search(r"start-?up|scale-?up", meta.get("company_type", ""), re.I):
        score -= 1
        basis.append("start-up or scale-up")
    if HIGH_SECTOR.search(meta.get("sector", "")) and level == "always":
        score += 1
        basis.append("head-level seat at a regulated institution or Big Tech")
    if re.search(r"\b(CH|LU)\b", meta.get("country", "")):
        score += 1
        basis.append("Switzerland or Luxembourg")
    if LOW_PLACE.search(meta.get("location", "")):
        score -= 1
        basis.append("lower-pay city")
    verdict = "likely below walk-away" if score <= -2 else ("likely at or above walk-away" if score >= 2 else "unclear")
    return {"verdict": verdict, "score": score, "basis": basis or ["no pay signal in the posting"]}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import jev_score as js
    c = json.loads(io.open(os.path.join(HERE, "..", "constraints.json"), encoding="utf-8").read())
    for f in sys.argv[1:]:
        meta, body, _ = js.parse_item(f)
        js.prepare_meta(meta, body, c)
        e = estimate(meta, body, c)
        print("%-58s %-30s (%+d) %s" % (os.path.basename(f)[11:69], e["verdict"], e["score"], "; ".join(e["basis"])))
