"""Step 3 scorer: hard filters, then one JEV call, then band mapping.

Usage (run from the workspace root, Python 3.10+, stdlib only):
  python -I agent/scripts/jev_score.py --jd agent/inbox/<item>.md [--dry-run] [--no-write]
  python -I agent/scripts/jev_score.py --ping

Reads JEV_API_KEY from .env. Never prints the key. Writes the decision block into the inbox item and
appends one JSON line to agent/inbox/_log.jsonl.
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # needed under "python -I"
import intake  # noqa: E402
import feed_terms  # noqa: E402
import pay_estimate  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT = os.path.join(ROOT, "agent")
API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

THRESHOLDS = {
    "match_go": 0.65,
    "match_go_priority2": 0.70,
    "match_no": 0.35,
    "match_cat4_min": 0.60,
    "match_warm_promote": 0.60,
    "interview_go": 0.60,
    "seniority_at_level_go": 0.50,
    "content_never_again": 0.80,
    "prefs_downgrade": 0.30,
    "comp_below_floor_downgrade": 0.70,
}

QUESTIONS = {
    "match": {
        "type": "noul",
        "instructions": "The candidate meets the must-have requirements of this job and would be shortlisted by a reasonable recruiter for it.",
        "criteria": {
            "true": "The candidate's experience, regulatory knowledge, seniority and languages cover the stated must-haves; a recruiter would include them in the shortlist.",
            "false": "One or more must-have requirements are clearly not met, or the role is in a different field or at a clearly different level.",
        },
    },
    "interview": {
        "type": "noul",
        "instructions": "The hiring manager for this job would invite the candidate to a first interview based on this profile.",
    },
    "seniority": {
        "type": "choice",
        "instructions": "Compare the level of this job with the level the candidate currently holds and targets (Head of or Director; VP or Senior Manager acceptable with the right mandate).",
        "criteria": {
            "below_candidate": "The job is clearly junior to the candidate: analyst, specialist, manager without a mandate, individual contributor reporting several layers below the executive.",
            "at_level": "The job is at the candidate's level: Head of, Director, VP or Senior Manager with a real mandate, Executive Director, CISO or deputy CISO of an entity.",
            "above_candidate": "The job is clearly above the candidate: group CRO or CIO of a large institution, C-suite of a major group.",
            "unclear": "The posting does not make the level clear.",
        },
    },
    "content": {
        "type": "choice",
        "instructions": "What is the dominant content of this job?",
        "criteria": {
            "leadership_mandate": "Owns a function or programme: IT risk, information security, operational resilience, technology regulatory compliance, AI governance, with accountability to management or regulators.",
            "senior_specialist": "Senior individual contributor in risk, security, resilience or compliance without owning the function.",
            "pm_pmo_only": "Project or programme management, PMO, delivery coordination, without risk, security or regulatory content.",
            "dpo_only": "Data protection officer or privacy role with no wider risk or security scope.",
            "staffed_consulting_delivery": "Consulting delivery role staffed on client projects with utilisation or billable-hours expectations.",
            "bcm_only": "Business continuity or crisis management only, without security or ICT risk scope.",
            "other": "None of the above describes the role.",
        },
    },
    "prefs": {
        "type": "noul",
        "instructions": "The job's location and working mode, language, sector and company type fit the candidate's stated soft preferences in the profile.",
    },
    "comp": {
        "type": "choice",
        "instructions": "Compare the compensation stated or clearly implied in the posting with the candidate's stated floor for this location and track.",
        "criteria": {
            "above_floor": "Stated or clearly implied pay is at or above the candidate's floor for this location and track.",
            "below_floor": "Stated or clearly implied pay is below the candidate's floor.",
            "not_stated": "The posting gives no usable compensation information.",
        },
    },
    "gap": {
        "type": "choice",
        "instructions": "What is the single most important gap between the candidate and this job?",
        "criteria": {
            "none": "No material gap.",
            "regulation_or_market": "A specific regulation, supervisor or market the candidate has not worked with.",
            "hands_on_technical": "Hands-on technical or engineering skill the role requires.",
            "people_leadership_scale": "The role requires leading a much larger team than the candidate has led.",
            "industry_domain": "Industry knowledge outside banking and regulated finance.",
            "language": "A working language the candidate does not have at the required level.",
            "years_in_title": "Years in an exact title, for example years as a CISO of a large institution.",
            "other": "A different gap.",
        },
    },
}


def read(path):
    return io.open(path, encoding="utf-8").read()


def api_key():
    env = read(os.path.join(ROOT, ".env"))
    m = re.search(r"^JEV_API_KEY=(.+)$", env, flags=re.M)
    if not m:
        sys.exit("JEV_API_KEY not found in .env")
    return m.group(1).strip()


def call_jev(state, questions):
    body = {"state": state, "model": MODEL, "questions": questions}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key(), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit("JEV HTTP %s: %s" % (e.code, e.read().decode("utf-8")[:500]))


def parse_item(path):
    text = read(path)
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, flags=re.S)
    if not m:
        sys.exit("Inbox item needs a front-matter block delimited by --- lines: " + path)
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    body = m.group(2)
    body = re.split(r"\n## Decision\b", body)[0].rstrip()
    return meta, body, text


def num(v):
    try:
        return float(str(v).replace(",", "").replace(" ", ""))
    except Exception:
        return None


def contains_any(haystack, needles):
    """Names of 4+ characters match as substrings; shorter codes (DE, CH, US) only as whole tokens."""
    h = (haystack or "").lower()
    tokens = set(re.findall(r"[a-z]+", h))
    for n in needles:
        nl = n.lower()
        if len(nl) >= 4:
            if nl in h:
                return True
        elif re.search(r"(^|[,(/;|]\s*)" + re.escape(nl) + r"\s*($|[,)/;|])", h.strip()):
            # short country codes only as a standalone field value ("DE", "Berlin, DE"), never inside words
            return True
    return False


def location_tier(meta, c):
    """Location category: N, 1, 2, 3, 4, or "?" when the place is not known. An unknown place is shown to the
    user as "location unknown"; it is never treated as category 4 (feed fix plan, action 4)."""
    country = meta.get("country", "").strip()
    loc = (meta.get("location", "") + ", " + ("" if country.lower() == "unknown" else country)).strip(" ,")
    remote = meta.get("remote", "unknown").lower()
    if contains_any(loc, c["location"]["negative_countries"]):
        return "N"
    for rule in c["location"].get("conditional_tier2", []):
        if contains_any(loc, rule["places"]):
            title_ok = re.search(rule["title_regex"], meta.get("title", ""), flags=re.I) is not None
            sector_ok = contains_any(meta.get("sector", "") + " " + meta.get("company_type", ""), rule["sectors"])
            pay = num(meta.get("salary_max")) or num(meta.get("salary_min"))
            pay_ok = pay is None or pay >= rule["min_base_eur"]
            return "2" if (title_ok and sector_ok and pay_ok) else rule["else_tier"]
    if contains_any(loc, c["location"]["tier1_cities"]):
        return "1"
    if remote == "remote" and c["location"]["tier1_remote"]:
        return "1"
    # multi-location postings: the best available tier wins, so check tier 2 before tier 3
    if contains_any(loc, c["location"]["tier2_countries"]):
        return "2"
    if contains_any(loc, c["location"]["tier3_countries"]):
        return "3"
    if country.lower() in ("", "unknown"):
        return "?"
    return "4"


def prepare_meta(meta, body, c):
    """Intake before scoring (feed fix plan, action 4): fill company, place, country, sector and company type.
    Order: front matter as captured; job-board page title, link and "Location:" label (intake.enrich); the
    employer page title ("... in <place> |"); last, the first known place in the posting text, marked as a guess."""
    intake.enrich(meta, body)
    if not meta.get("location", "").strip():
        hm = re.search(r"^Title: .*? in ([^|\n]{3,120})\|", body, flags=re.M)
        if hm:
            meta["location"] = hm.group(1).strip()
            meta["location_source"] = "page title"
    if not meta.get("location", "").strip():
        places = (c["location"]["tier1_cities"] + ["Munich", "München", "Düsseldorf", "Duesseldorf", "Berlin", "Hamburg",
                  "Cologne", "Köln", "Stuttgart", "Zurich", "Zürich", "Geneva", "Genève", "Luxembourg", "Vienna", "Wien",
                  "Amsterdam", "Dublin", "London", "Paris", "Madrid", "Warsaw", "Singapore", "New York", "San Francisco",
                  "Hong Kong", "Tokyo", "Riyadh", "Dhahran", "Dubai", "Abu Dhabi", "United States", "India", "China"])
        own = re.split(r"(Similar jobs|People also viewed|Show more jobs like this|More jobs like this)", body)[0]
        best = None
        for pl in places:
            i = own.find(pl)
            if i >= 0 and (best is None or i < best[0]):
                best = (i, pl)
        if best:
            meta["location"] = best[1]
            meta["location_source"] = "posting text (guess)"
    if meta.get("country", "").strip().lower() in ("", "unknown"):
        meta["country"] = ""
        intake.enrich(meta, "")  # country from the place found above


def jev_text(body, limit=30000):
    """Posting text for the model: page style and data blobs removed (long lines full of "key": value pairs, as on
    HSBC's Eightfold pages), then cut at `limit` characters. The description comes first on every site seen so far."""
    keep = [ln for ln in body.splitlines() if not (len(ln) > 1500 and ln.count('":') > 20)]
    t = "\n".join(keep)
    return t if len(t) <= limit else t[:limit] + "\n[posting text cut at %d characters]" % limit


def eur_k(amount):
    """An amount from constraints.json as text for a rule line, in the form 'EUR <n>k'; 'configured' when not set.
    The figures live in the settings file only, never in this code (2026-11-21)."""
    return "EUR %dk" % round(amount / 1000) if isinstance(amount, (int, float)) and amount else "configured"


def gulf_us_rule(meta, band, rules, c):
    """Gulf region and United States (user decisions G4, G5 and action 11). Only Head, Director, Chief and CISO titles
    are shown. A published package below the minimum is dropped earlier, by the hard filter. With no published
    package the result is a conditional Stretch that lists the three conditions as questions for the employer."""
    rule = c.get("feed_rules", {}).get("tier3_rule", {})
    if not re.search(rule.get("title_regex", "(head|director|chief|ciso)"), meta.get("title", ""), flags=re.I):
        rules.append("Gulf and US rule: only Head, Director, Chief or CISO titles are shown")
        return "No"
    if band == "No":
        return band
    published = bool(num(meta.get("salary_max")) or num(meta.get("salary_min")))
    qs = " ".join("(%d) %s" % (i + 1, q) for i, q in enumerate(rule.get("questions", [])))
    if published:
        rules.append("Gulf and US rule: the published package passes the %s line on a rough conversion; still ask: %s"
                     % (eur_k(c.get("compensation", {}).get("tier3_min_total_eur_equiv")), qs))
    else:
        rules.append("Gulf and US rule, pay not published: conditional Stretch. Ask the employer: " + qs)
    return "Stretch"


def wide_rule(meta, band, rules, c, match):
    """Places outside priorities 1 to 3: Europe beyond the priority countries, London, and anything else the user
    sends (user decisions G4, G6 and action 12). Shown only as a Stretch, and only for a Head, Director, Chief or
    CISO title with a match of 0.75 or higher. A published base below the minimum for these places (constraints.json,
    wide_lane.min_base_eur_equiv) is dropped earlier, by the hard filter; with no published pay the Stretch carries
    the pay question."""
    rule = c.get("feed_rules", {}).get("wide_lane", {})
    line = eur_k(rule.get("min_base_eur_equiv"))
    if not re.search(rule.get("title_regex", "(head|director|chief|ciso)"), meta.get("title", ""), flags=re.I):
        rules.append("category 4 rule: only Head, Director, Chief or CISO titles are shown outside priorities 1 to 3")
        return "No"
    if match < float(rule.get("min_match", 0.75)):
        rules.append("category 4 rule: match below %.2f" % float(rule.get("min_match", 0.75)))
        return "No"
    if num(meta.get("salary_max")) or num(meta.get("salary_min")):
        rules.append("category 4 rule: the published base passes the %s line on a rough conversion; Stretch only" % line)
    else:
        rules.append("category 4 rule, pay not published: Stretch only; check that the base reaches %s equivalent" % line)
    return "Stretch"


def hard_filters(meta, c):
    tier = location_tier(meta, c)
    if tier == "N":
        return "location negative list", tier
    sector_type = " ".join([meta.get("sector", ""), meta.get("company_type", ""), meta.get("company", "")])
    if contains_any(sector_type, c["sector_negative"]):
        return "sector negative list", tier
    if contains_any(meta.get("company_type", ""), c["company_type_negative"]):
        return "company type negative list", tier
    if contains_any(meta.get("company", ""), c["named_negative"]):
        return "named company negative list", tier
    track = meta.get("track", "Permanent").lower()
    cur = meta.get("currency", "EUR").upper()
    smax = num(meta.get("salary_max")) or num(meta.get("salary_min"))
    if track == "project":
        rate = num(meta.get("day_rate")) or smax
        if rate is not None and rate < c["compensation"]["project_day_rate_floor_eur"]:
            return "day rate below floor", tier
        months = num(meta.get("contract_months"))
        if months is not None and months < c["compensation"]["project_min_months"]:
            return "contract shorter than minimum", tier
    else:
        if smax is not None:
            fx = c.get("feed_rules", {}).get("fx_to_eur_rough", {})
            rate = fx.get(cur) if isinstance(fx.get(cur), (int, float)) else 1.0  # rough, see constraints.json
            if tier == "3" and smax * rate < c["compensation"]["tier3_min_total_eur_equiv"]:
                return "priority 3 package below minimum", tier
            wide_min = c.get("feed_rules", {}).get("wide_lane", {}).get("min_base_eur_equiv")
            if tier == "4" and wide_min and smax * rate < wide_min:
                return "category 4 base below the %s line" % eur_k(wide_min), tier
            wa = c["compensation"]["permanent_walkaway"].get(cur)
            if wa is not None and smax < wa:
                return "salary below walk-away", tier
    if meta.get("sponsorship", "").lower() in ("no", "none", "not offered") and contains_any(
        meta.get("location", "") + " " + meta.get("country", ""), c["authorization"]["sponsorship_needed"]
    ):
        return "sponsorship needed and not offered", tier
    return None, tier


def band_from(answers, tier, warm, t):
    """Calibrated 2026-11-09: soft misses (Go gate, preferences, pay) may lower the band by at most one step
    below the band the match score alone gives; location rules and the never-again rule apply after that."""
    p = {}
    p["match"] = answers["match"]["noul"]
    p["interview"] = answers["interview"]["noul"]
    p["prefs"] = answers["prefs"]["noul"]
    sen = answers["seniority"]["probabilities"]
    con = answers["content"]["probabilities"]
    comp = answers["comp"]["probabilities"]
    rules = []
    steps = ["No", "Stretch", "Go"]
    never = max(con.get(k, 0.0) for k in ("pm_pmo_only", "dpo_only", "staffed_consulting_delivery"))
    if never >= t["content_never_again"]:
        return "No", ["never-again content (%.2f)" % never], p
    go_line = t["match_go_priority2"] if tier in ("2", "?") else t["match_go"]  # unknown place: the stricter line
    if p["match"] >= go_line:
        base = "Go"
    elif p["match"] < t["match_no"]:
        base = "No"
    else:
        base = "Stretch"
    band = base
    # soft misses
    if band == "Go" and (p["interview"] < t["interview_go"] or sen.get("at_level", 0.0) < t["seniority_at_level_go"]):
        band = "Stretch"
        rules.append("interview or seniority below Go line")
    if p["prefs"] < t["prefs_downgrade"] and band != "No":
        band = steps[steps.index(band) - 1]
        rules.append("preferences miss")
    if comp.get("below_floor", 0.0) >= t["comp_below_floor_downgrade"] and band != "No":
        band = steps[steps.index(band) - 1]
        rules.append("compensation below floor")
    floor = steps[max(0, steps.index(base) - 1)]
    if steps.index(band) < steps.index(floor):
        band = floor
        rules.append("soft misses capped at one step")
    # location rules
    if tier == "3" and band == "Go":
        band = "Stretch"
        rules.append("priority 3 location, never auto-Go")
    if tier == "4":
        if p["match"] >= t["match_cat4_min"] and band != "No":
            band = "Stretch"
            rules.append("category 4 location, Stretch only")
        elif band != "No":
            band = "No"
            rules.append("category 4 location below minimum match")
    if tier == "?":
        rules.append("location unknown: check the place before deciding")
    if warm in ("first", "named") and band == "Stretch" and p["match"] >= t["match_warm_promote"]:
        band = "Go"
        rules.append("warm path promotion")
    if band == "Go" and warm in ("none", "", None):
        rules.append("cold application")
    return band, rules, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", help="inbox item markdown file")
    ap.add_argument("--dry-run", action="store_true", help="build the request, do not call the API")
    ap.add_argument("--no-write", action="store_true", help="do not modify the inbox item or log")
    ap.add_argument("--ping", action="store_true", help="trivial API call to confirm the key works")
    ap.add_argument("--override", default="", help="user-approved exception for one item: score despite a hard filter; "
                    "the waived rule and this note are recorded in the decision (added 2026-11-12)")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if a.ping:
        r = call_jev("The sky is blue on a clear day.", {"t": {"type": "noul", "instructions": "Is the statement true?"}})
        print("ok model=%s noul=%.2f usage=%s" % (r.get("model"), r["answers"]["t"]["noul"], r.get("usage")))
        return
    if not a.jd:
        ap.error("--jd is required unless --ping")

    c = json.loads(read(os.path.join(AGENT, "constraints.json")))
    profile = read(os.path.join(AGENT, "profile_jev.md"))
    meta, body, full = parse_item(a.jd)
    prepare_meta(meta, body, c)
    warm = meta.get("warm_path", "none").lower()
    today = dt.date.today().isoformat()
    status = meta.get("status", "live").lower()
    prose = 0
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", body)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    for line in t.splitlines():
        s = line.strip()
        if s and not s.startswith(("*", "-", "#", "|", ">")) and len(s.split()) >= 12:
            prose += len(re.findall(r"\w+", s))
    # a clean posting view (LinkedIn single-posting view) carries its own word count; bullet-only text is normal there
    clean_words = num(meta.get("description_words")) or 0
    if status != "live" or (prose < 120 and clean_words < 120):
        sys.exit("refused: posting status is %s with %d prose words; capture the live posting with a real description first (%s)" % (status, prose, a.jd))

    # read a posted pay range from the text when the front matter has none (added 2026-11-09 after the Google miss)
    if not (meta.get("salary_max", "").strip() or meta.get("salary_min", "").strip()):
        own = re.split(r"(Similar jobs|People also viewed|Show more jobs like this|Seniority level|More jobs like this)", body)[0]
        cur_map = {"€": "EUR", "EUR": "EUR", "CHF": "CHF", "£": "GBP", "GBP": "GBP", "$": "USD", "USD": "USD"}
        def _n(v, k):
            v = re.sub(r"[ ,.'’ ]", "", v)
            return float(v) * (1000 if k else 1) if v.isdigit() else None
        mm = re.search(r"(€|EUR|CHF|£|GBP|\$|USD)\s?(\d[\d.,'  ]{1,9})(k)?\s*(?:-|–|to|bis)\s*(?:€|EUR|CHF|£|GBP|\$|USD)?\s?(\d[\d.,'  ]{1,9})(k)?", own, flags=re.I)
        cur = None
        if mm:
            cur, lo, hi = cur_map.get(mm.group(1).upper() if mm.group(1).isalpha() else mm.group(1)), _n(mm.group(2), mm.group(3)), _n(mm.group(4), mm.group(5))
        else:
            mm = re.search(r"between\s+(\d[\d.,'  ]{1,9})\s*(CHF|EUR|GBP|USD)\s+and\s+(\d[\d.,'  ]{1,9})\s*(CHF|EUR|GBP|USD)", own, flags=re.I)
            if mm:
                cur, lo, hi = mm.group(2).upper(), _n(mm.group(1), None), _n(mm.group(3), None)
        if cur and lo and hi and 20000 <= lo <= hi <= 2000000:
            meta["salary_min"], meta["salary_max"], meta["currency"] = str(int(lo)), str(int(hi)), cur
            meta["salary_source"] = "posting text"
    # detect "no sponsorship" wording in the posting so the authorization hard filter can apply
    # Narrowed 2026-11-09: only explicit refusals count. Standard "must be eligible / authorised to work in"
    # wording is a legal right-to-work statement that sponsoring employers also use, so it does not trigger.
    if not meta.get("sponsorship", "").strip() and re.search(
        r"(\bno (visa |work permit )?sponsorship\b|"
        r"\b(unable|not able|cannot|can not|will not|won't|do not|does not|are not able) (to )?(offer|provide|support|sponsor)[^.]{0,40}(sponsorship|visa|work permit)|"
        r"\bsponsorship (is |will )?(not|n't) (be )?(available|offered|provided|possible)|"
        r"\bwithout (the need for |requiring )?(current or future )?(visa |employer )?sponsorship\b|"
        r"\bnot (in a position|able) to sponsor\b)", body, flags=re.I):
        meta["sponsorship"] = "no"
    fail, tier = hard_filters(meta, c)
    waived = None
    if fail and a.override:
        waived = {"rule": fail, "note": a.override}
        print("override: hard filter '%s' waived by the user (%s)" % (fail, a.override))
        fail = None
    if fail:
        decision = {"date": today, "band": "No", "stage": "hard filter", "rule": fail, "tier": tier}
        print("No | hard filter: %s | tier %s | %s - %s" % (fail, tier, meta.get("company"), meta.get("title")))
    else:
        job_meta = {k: v for k, v in meta.items() if k not in ("source",)}
        state = {"candidate_profile": profile, "job": {"metadata": job_meta, "posting_text": jev_text(body)}}
        if a.dry_run:
            print(json.dumps({"state_keys": list(state.keys()), "job_metadata": job_meta, "questions": list(QUESTIONS.keys()), "tier": tier}, indent=2))
            return
        r = call_jev(json.dumps(state, ensure_ascii=False), QUESTIONS)
        band, rules, p = band_from(r["answers"], tier, warm, THRESHOLDS)
        # Level rule (user decision 2026-11-15): a Senior Manager, Lead or Officer title is shown only with a visible
        # mandate and "at level". Titles below that are not searched for; a link the user sends is still scored.
        lvl = feed_terms.check(meta.get("title", ""), any_level=True)["level"]
        sen_p = r["answers"]["seniority"]["probabilities"]
        con_p = r["answers"]["content"]["probabilities"]
        if lvl == "mandate" and band != "No" and (sen_p.get("at_level", 0.0) < 0.5 or con_p.get("leadership_mandate", 0.0) < 0.5):
            band = "No"
            rules.append("level rule: Senior Manager, Lead or Officer title without a visible mandate at level")
        elif lvl in ("never", "below"):
            rules.append("level note: this title is below the level the feed shows")
        # Agency adverts (user decisions G7 and action 10): the client is hidden, so the named-negative and
        # repeat-employer rules cannot be checked. The first step is always the question to the recruiter.
        if tier == "3":
            band = gulf_us_rule(meta, band, rules, c)
        if tier == "4":
            band = wide_rule(meta, band, rules, c, p["match"])
        if "recruitment agency" in meta.get("company_type", "").lower():
            rules.append("agency advert, client unknown: first ask the recruiter for the client and the pay band; "
                         "no CV and no package before the client is named")
        # Pay estimate (user decision G3, action 15): free, from the posting only. "Likely below walk-away" moves a
        # Go to Stretch and is shown as the reason; it never drops a role.
        pay = pay_estimate.estimate(meta, body, c)
        if pay["verdict"] == "likely below walk-away":
            if band == "Go":
                band = "Stretch"
            rules.append("pay estimate: likely below your walk-away (%s)" % "; ".join(pay["basis"]))
        decision = {
            "date": today, "band": band, "stage": "jev", "tier": tier, "warm_path": warm, "rules": rules,
            "match": round(p["match"], 3), "interview": round(p["interview"], 3), "prefs": round(p["prefs"], 3),
            "seniority": r["answers"]["seniority"]["choice"], "content": r["answers"]["content"]["choice"],
            "comp": r["answers"]["comp"]["choice"], "gap": r["answers"]["gap"]["choice"],
            "model": r.get("model"), "usage": r.get("usage"), "override": waived, "pay_estimate": pay,
            "probabilities": {k: (v.get("probabilities") if v.get("type") != "noul" else round(v["noul"], 3)) for k, v in r["answers"].items()},
        }
        print("%s | match %.2f interview %.2f prefs %.2f | %s / %s / gap %s | tier %s | %s | %s - %s" % (
            band, p["match"], p["interview"], p["prefs"], decision["seniority"], decision["content"],
            decision["gap"], tier, ", ".join(rules) or "no adjustments", meta.get("company"), meta.get("title")))

    if a.no_write:
        return
    block = "\n\n## Decision\n```json\n" + json.dumps(decision, indent=2, ensure_ascii=False) + "\n```\n"
    base = re.split(r"\n## Decision\b", full)[0].rstrip()
    io.open(a.jd, "w", encoding="utf-8", newline="\n").write(base + block)
    log = dict(decision, company=meta.get("company"), title=meta.get("title"), file=os.path.basename(a.jd))
    with io.open(os.path.join(AGENT, "inbox", "_log.jsonl"), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
