"""Feed intake: fill employer and place details on a posting before it is scored
(feed fix plan, action 4, option A; 2026-11-15).

Fills, when missing: company (from a job-board page title), location and country (from the place text, the
page title or the link), sector and company type (from agent/employers.json). A country that cannot be found
is written as "unknown". The scorer then shows "location unknown" instead of treating the posting as the
lowest location category.

    python intake.py --check "Zurich, ZH, Switzerland"
    python intake.py --employer "Julius Baer Deutschland"
"""
import io
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
EMPLOYERS = os.path.abspath(os.path.join(HERE, "..", "employers.json"))

# country code -> names and codes as they appear in postings (lower case, ASCII)
COUNTRIES = {
    "DE": ["germany", "deutschland", "allemagne", "deu", "de"],
    "CH": ["switzerland", "schweiz", "suisse", "svizzera", "che", "ch"],
    "LU": ["luxembourg", "luxemburg", "letzebuerg", "lux", "lu"],
    "AT": ["austria", "osterreich", "oesterreich", "aut", "at"],
    "NL": ["netherlands", "the netherlands", "nederland", "niederlande", "nld", "nl"],
    "IE": ["ireland", "irland", "irl", "ie"],
    "GB": ["united kingdom", "england", "scotland", "wales", "northern ireland", "great britain", "gbr", "uk", "gb"],
    "US": ["united states", "united states of america", "usa", "us"],
    "FR": ["france", "frankreich", "fra", "fr"],
    "ES": ["spain", "spanien", "espana", "esp", "es"],
    "IT": ["italy", "italien", "italia", "ita", "it"],
    "BE": ["belgium", "belgien", "belgique", "bel", "be"],
    "PL": ["poland", "polen", "pol", "pl"],
    "PT": ["portugal", "prt", "pt"],
    "SE": ["sweden", "schweden", "swe"],
    "DK": ["denmark", "danemark", "dnk", "dk"],
    "NO": ["norway", "norwegen", "nor"],
    "FI": ["finland", "finnland", "fin", "fi"],
    "CZ": ["czech republic", "czechia", "tschechien", "cze", "cz"],
    "HU": ["hungary", "ungarn", "hun", "hu"],
    "RO": ["romania", "rumanien", "rou", "ro"],
    "LT": ["lithuania", "litauen", "ltu", "lt"],
    "LI": ["liechtenstein", "lie"],
    "MT": ["malta", "mlt"],
    "CY": ["cyprus", "zypern", "cyp"],
    "AE": ["united arab emirates", "uae", "are", "ae"],
    "SA": ["saudi arabia", "saudi-arabien", "ksa", "sau", "sa"],
    "QA": ["qatar", "katar", "qat", "qa"],
    "KW": ["kuwait", "kwt", "kw"],
    "BH": ["bahrain", "bhr", "bh"],
    "OM": ["oman", "omn", "om"],
    "SG": ["singapore", "singapur", "sgp", "sg"],
    "HK": ["hong kong", "hkg", "hk"],
    "IN": ["india", "indien", "ind"],
    "CN": ["china", "chn", "cn"],
    "JP": ["japan", "jpn", "jp"],
    "AU": ["australia", "australien", "aus", "au"],
    "CA": ["canada", "kanada", "can"],
    "MX": ["mexico", "mexiko", "mex", "mx"],
    "BR": ["brazil", "brasilien", "bra", "br"],
    "ZA": ["south africa", "sudafrika", "zaf", "za"],
    "RU": ["russia", "russland", "russian federation", "rus", "ru"],
    # further countries by full name only (no short codes, to avoid false hits)
    "TW": ["taiwan"], "TH": ["thailand"], "MY": ["malaysia"], "ID": ["indonesia"], "PH": ["philippines"],
    "KR": ["south korea", "korea"], "NZ": ["new zealand"], "IL": ["israel"], "TR": ["turkey", "turkiye"],
    "EG": ["egypt"], "NG": ["nigeria"], "KE": ["kenya"], "AR": ["argentina"], "CO": ["colombia"], "CL": ["chile"],
    "UA": ["ukraine"], "GR": ["greece"], "BG": ["bulgaria"], "HR": ["croatia"], "SK": ["slovakia"], "SI": ["slovenia"],
    "EE": ["estonia"], "LV": ["latvia"], "RS": ["serbia"], "IS": ["iceland"], "BY": ["belarus"], "KZ": ["kazakhstan"],
    "AM": ["armenia"], "AZ": ["azerbaijan"], "KG": ["kyrgyzstan"], "MD": ["moldova"], "TJ": ["tajikistan"],
    "UZ": ["uzbekistan"],
}
# codes that are also common words or US state / region codes are only read in a clear "City, XX" position
AMBIGUOUS = {"de", "at", "it", "be", "in", "us", "es", "no", "fi", "hu", "ro", "lt", "sa", "om", "ca", "can", "aus", "nor", "fin",
             "ind", "ch", "lu", "nl", "ie", "gb", "uk", "fr", "pl", "pt", "dk", "cz", "ae", "qa", "kw", "bh", "sg", "hk",
             "cn", "jp", "au", "mx", "br", "za", "ru", "lie", "are", "lux", "bel", "pol", "ita", "esp", "fra", "deu", "che",
             "aut", "nld", "irl", "gbr", "sau", "qat", "kwt", "bhr", "omn", "sgp", "hkg", "chn", "jpn", "mex", "bra", "zaf",
             "rus", "swe", "dnk", "cze", "hun", "rou", "ltu", "mlt", "cyp", "prt", "ksa", "uae", "usa"}

CITIES = {
    "DE": ["frankfurt", "eschborn", "mainz", "wiesbaden", "darmstadt", "bad homburg", "offenbach", "kronberg", "hanau",
           "neu-isenburg", "neu isenburg", "bad vilbel", "munich", "munchen", "muenchen", "unterfohring", "unterfoehring",
           "garching", "berlin", "hamburg", "dusseldorf", "duesseldorf", "cologne", "koln", "koeln", "stuttgart", "bonn",
           "hannover", "nuremberg", "nurnberg", "nuernberg", "leipzig", "dresden", "karlsruhe", "essen", "dortmund",
           "mannheim", "heidelberg", "kirchdorf an der iller", "holzminden", "erfurt", "duisburg", "bremen", "ingelheim"],
    "CH": ["zurich", "zuerich", "geneva", "geneve", "genf", "basel", "bern", "zug", "lugano", "lausanne", "adliswil",
           "wallisellen", "winterthur", "st. gallen", "st gallen", "luzern", "lucerne", "opfikon", "pfaffikon", "baar"],
    "LU": ["luxembourg", "luxemburg", "hesperange", "betzdorf", "senningerberg", "strassen", "kirchberg", "bertrange",
           "munsbach", "esch-sur-alzette", "grevenmacher", "leudelange"],
    "AT": ["vienna", "wien", "graz", "linz", "salzburg", "innsbruck"],
    "NL": ["amsterdam", "amstelveen", "rotterdam", "the hague", "den haag", "utrecht", "eindhoven", "schiphol", "almere"],
    "IE": ["dublin", "cork", "kilkenny", "galway", "limerick"],
    "GB": ["london", "bournemouth", "belfast", "edinburgh", "glasgow", "chester", "croydon", "manchester", "birmingham",
           "leeds", "northampton", "bristol", "cannon street", "canary wharf", "city of london"],
    "FR": ["paris", "lyon", "nanterre", "la defense"],
    "ES": ["madrid", "barcelona"],
    "IT": ["milan", "milano", "rome", "roma"],
    "BE": ["brussels", "bruxelles", "brussel", "waterloo", "antwerp"],
    "PL": ["warsaw", "warszawa", "krakow", "wroclaw"],
    "LT": ["vilnius"],
    "AE": ["dubai", "abu dhabi"],
    "SA": ["riyadh", "dhahran", "jeddah", "ras tanura"],
    "QA": ["doha"],
    "KW": ["kuwait city"],
    "BH": ["manama"],
    "OM": ["muscat"],
    "SG": ["singapore"],
    "US": ["new york", "san francisco", "seattle", "santa clara", "jersey city", "charlotte", "chicago", "boston", "dallas",
           "austin", "washington dc", "mclean", "north charleston", "plano", "atlanta", "denver", "philadelphia", "palo alto"],
}
PRIORITY_ORDER = ["DE", "CH", "LU", "AT", "NL", "IE", "AE", "SA", "QA", "KW", "BH", "OM", "US", "GB"]
REMOTE = re.compile(r"\b(remote|home ?office|work from home|100% remote|fully remote)\b", re.I)


def _ascii(s):
    s = (s or "").replace("ß", "ss").replace("ä", "a").replace("ö", "o").replace("ü", "u")
    s = s.replace("Ä", "A").replace("Ö", "O").replace("Ü", "U")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def _word(fragment, text):
    return re.search(r"(?<![a-z0-9])" + re.escape(fragment) + r"(?![a-z0-9])", text) is not None


def _segment_codes(seg):
    """Country codes and first known city for one place ("Zurich, ZH, Switzerland")."""
    codes, city = [], ""
    for code, names in CITIES.items():
        for n in names:
            if _word(n, seg):
                city = city or n
                break
    northern_ireland = "northern ireland" in seg
    # 1. a country written out in full wins
    for code, names in COUNTRIES.items():
        for n in names:
            if len(n) > 3 and n not in AMBIGUOUS and _word(n, seg):
                if code == "IE" and northern_ireland and not re.search(r"(?<!northern )ireland", seg):
                    break  # Belfast: Northern Ireland is the UK
                if code not in codes:
                    codes.append(code)
                break
    if codes:
        return codes, city
    # 2. a short code in a list position: "Zurich, CH", "DE, BY, Munich", "Dublin, IRL", "Croydon UK"
    tokens = [t.strip(" .()") for t in re.split(r"[,(]", seg) if t.strip(" .()")]
    us_city = any(_word(n, seg) for n in CITIES["US"])
    for pos, tok in enumerate(tokens):
        last = tok.split()[-1] if tok.split() else ""
        for cand in ([tok] if pos in (0, len(tokens) - 1) else []) + ([last] if len(tok.split()) > 1 else []):
            for code, names in COUNTRIES.items():
                if cand in names and cand in AMBIGUOUS and code not in codes:
                    if us_city and len(cand) == 2 and code != "US":
                        continue  # "Charlotte, NC", "Wilmington, DE": a US state, not a country
                    if len(tokens) == 1 and cand == tok:
                        continue  # a lone two-letter word is not a place
                    codes.append(code)
    # 3. every known city in the piece adds its country (the only source when no country or code is given)
    for code, names in CITIES.items():
        if any(_word(n, seg) for n in names) and code not in codes:
            codes.append(code)
    return codes, city


def place_fields(text):
    """(city, country codes) from a place text such as "Zurich, ZH, Switzerland", "DE, BY, Munich" or "Dublin 2, Ireland".
    A country that is written out wins over a guess from the city ("Dublin, California, United States" is US).
    Several places ("London, United Kingdom; Dublin, Ireland") give several codes, priority places first."""
    raw = re.sub(r"\s+", " ", _ascii(text).lower())
    codes, city = [], ""
    for seg in [p.strip() for p in re.split(r";|\||\s/\s|\sand\s|\salso\s|\sor\s", raw) if p.strip()]:
        c, ct = _segment_codes(seg)
        city = city or ct
        for x in c:
            if x not in codes:
                codes.append(x)
    codes.sort(key=lambda c: PRIORITY_ORDER.index(c) if c in PRIORITY_ORDER else 99)
    return (city.title() if city else ""), codes


BOARD_TITLE = [
    # LinkedIn, localised: "<Role> at|bei|chez|bij <Company> — <Place> | LinkedIn Jobs"
    re.compile(r"^(?P<role>.+?)\s+(?:at|bei|chez|bij|presso|en|hos|w|na)\s+(?P<company>.+?)\s+[—–-]\s+(?P<place>[^|]+?)\s*\|\s*LinkedIn", re.I),
    # LinkedIn, English: "<Company> hiring <Role> in <Place> | LinkedIn"
    re.compile(r"^(?P<company>.+?)\s+hiring\s+(?P<role>.+?)\s+in\s+(?P<place>[^|]+?)\s*\|\s*LinkedIn", re.I),
    # jobs.ch: "<Role> - Job Offer at <Company> - jobs.ch"
    re.compile(r"^(?P<role>.+?)\s+-\s+Job Offer at\s+(?P<company>.+?)\s+-\s+jobs\.ch", re.I),
    # jobs.lu: "<Role> - <Company> - jobs.lu"
    re.compile(r"^(?P<role>.+?)\s+-\s+(?P<company>[^-]+?)\s+-\s+jobs\.lu", re.I),
    # employer pages: "<Role> in <Place> | <Company>"
    re.compile(r"^(?P<role>.+?)\s+in\s+(?P<place>[^|]{3,80}?)\s*\|\s*(?P<rest>.+)$", re.I),
]


def parse_page_title(page_title):
    """Role, company and place from the page title line of a capture ("Title: ..."). Empty strings when unknown."""
    t = re.sub(r"\s+", " ", page_title or "").strip()
    for pat in BOARD_TITLE:
        m = pat.match(t)
        if m:
            d = m.groupdict()
            return (d.get("role") or "").strip(), (d.get("company") or "").strip(), (d.get("place") or "").strip()
    return "", "", ""


def place_from_url(url):
    """eFinancialCareers and TalentBrew links carry the place: jobs-Netherlands-Amsterdam-..., /job/zurich/..."""
    m = re.search(r"efinancialcareers\.[a-z.]+/jobs-([A-Za-z_]+)-([A-Za-z_]+)-", url or "")
    if m:
        return "%s, %s" % (m.group(2).replace("_", " "), m.group(1).replace("_", " "))
    m = re.search(r"/job/([a-z][a-z\-]{2,40})/", url or "")
    if m and not re.search(r"myworkdayjobs|oraclecloud", url):
        return m.group(1).replace("-", " ")
    return ""


_EMP = None


def employer_fields(company):
    """(sector, company type) from agent/employers.json, or ("", "") when the employer is not listed."""
    global _EMP
    if _EMP is None:
        try:
            _EMP = json.loads(io.open(EMPLOYERS, encoding="utf-8").read()).get("employers", [])
        except (OSError, ValueError):
            _EMP = []
    name = " " + re.sub(r"\s+", " ", _ascii(company).lower()) + " "
    for e in _EMP:
        for frag in e.get("match", []):
            if _word(_ascii(frag).lower().strip(), name):
                return e.get("sector", ""), e.get("company_type", "")
    return "", ""


BAD_COMPANY = re.compile(r"^(unknown|n/?a|)$|job in |homeoffice|vollzeit|vacatures|^(amsterdam|luxembourg|frankfurt|zurich|berlin|"
                         r"munich|dublin|london)( [a-z]{2})?$|^europe at |^emea at |private banking bei |semi overheid", re.I)


def enrich(meta, body=""):
    """Fill missing company, location, country, sector and company type in a front-matter dict. Returns the list of
    fields it filled. Never overwrites a value that is already there, except a company that is clearly not a company."""
    filled = []
    page = re.search(r"^Title:\s*(.+)$", body or "", flags=re.M)
    role, company, place = parse_page_title(page.group(1)) if page else ("", "", "")
    if company and BAD_COMPANY.search(meta.get("company", "").strip()):
        meta["company"] = company
        filled.append("company")
    if role and meta.get("title", "").rstrip().endswith("..."):
        meta["title"] = role  # a title cut short in a board's result list ("Head of Captives & Alternative Risk Transfer So...")
        filled.append("title")
    if role and re.search(r"\s(?:bei|at|chez|bij)\s.+[—–]", meta.get("title", "")):
        meta["title"] = role  # "Head of IT Risk bei Example AG — Zurich" -> "Head of IT Risk"
        filled.append("title")
    loc = meta.get("location", "").strip()
    if not loc or loc.lower() in ("country:", "unknown") or not any(place_fields(loc)):
        # nothing usable on file ("", "jobs.ch", "country:"): take the first candidate that names a real place
        m = re.search(r"(?:Place of work|Workplace|Location|Standort|Arbeitsort|Lieu de travail)\s*[:\-]\s*\**\s*([^\n|*]{3,80})", body or "", flags=re.I)
        for cand in (place, place_from_url(meta.get("source", "")), m.group(1).strip() if m else ""):
            if cand and any(place_fields(cand)):
                meta["location"] = cand
                filled.append("location")
                break
    loc = meta.get("location", "")
    country = meta.get("country", "").strip()
    if not country or country.lower() in ("sector:", "unknown"):
        _, codes = place_fields(loc)
        meta["country"] = "; ".join(codes) if codes else "unknown"
        filled.append("country")
    if meta.get("remote", "unknown").lower() in ("", "unknown") and REMOTE.search(loc + " " + meta.get("title", "")):
        meta["remote"] = "remote"
        filled.append("remote")
    sector, ctype = employer_fields(meta.get("company", ""))
    if not meta.get("sector", "").strip() or meta.get("sector", "").strip().lower() in ("company_type:", "unknown"):
        meta["sector"] = sector or "unknown"
        filled.append("sector")
    if not meta.get("company_type", "").strip() or meta.get("company_type", "").strip().lower() in ("track:", "unknown"):
        meta["company_type"] = ctype or "unknown"
        filled.append("company_type")
    return filled


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        print(place_fields(sys.argv[2]))
    elif len(sys.argv) >= 3 and sys.argv[1] == "--employer":
        print(employer_fields(sys.argv[2]))
    else:
        print(__doc__)
