#!/usr/bin/env python3
"""
fetch_iacr_jobs.py — scrapes the IACR jobs board at https://iacr.org/jobs/,
normalizes each posting into the schema used by _data/positions.yml, and
appends the *new* entries (not already present in positions.yml) directly
to the end of _data/positions.yml so they publish on the next site build.

The IACR board is server-rendered HTML (there is no RSS/Atom feed), so this
parses the listing markup. De-duplication is by `link` (the canonical
https://iacr.org/jobs/item/<id> URL), so re-running is safe: entries already
in positions.yml are never appended twice.

Run locally:
    python scripts/fetch_iacr_jobs.py
"""

from __future__ import annotations

import html
import re
import sys
import datetime as dt
import urllib.request
from pathlib import Path

try:
    import yaml  # pip install pyyaml
except ImportError:
    sys.stderr.write("pyyaml missing; install with: pip install pyyaml\n")
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "_data"
EXISTING = DATA / "positions.yml"

JOBS_URL = "https://iacr.org/jobs/"
# IACR sits behind Cloudflare and 403s the default urllib user-agent.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
)

# ---------- Heuristics for classifying a free-text title ----------

TYPE_PATTERNS = [
    (re.compile(r"\bpost.?doc(toral)?\b", re.I), "postdoc"),
    (re.compile(r"\bresearch (scientist|engineer|associate|fellow|staff)\b", re.I), "research_scientist"),
    (re.compile(r"\b(faculty|tenure.?track|associate professor|assistant professor|lecturer)\b", re.I), "faculty"),
    (re.compile(r"\bintern(ship)?\b", re.I), "intern"),
    (re.compile(r"\bvisit(ing|or)\b", re.I), "visiting"),
    (re.compile(r"\bph\.?d\.?\b|\bdoctoral\b", re.I), "phd"),
]

REGION_PATTERNS = [
    (re.compile(r"\b(India|IIT|IISc|IIIT|TIFR|ISI|IISER)\b", re.I), "india"),
    (re.compile(r"\b(USA|United States|Boston|California|Berkeley|New York|Texas|Georgia|Massachusetts|Princeton|Stanford|MIT|CMU|Cornell|UIUC|UCLA|Maryland|Washington|Atlanta|Pittsburgh|Chicago|Seattle)\b", re.I), "north_america"),
    (re.compile(r"\b(Canada|Toronto|Vancouver|Montreal|Waterloo|Calgary)\b", re.I), "north_america"),
    (re.compile(r"\b(Germany|France|Netherlands|Belgium|Sweden|Norway|Denmark|Finland|Switzerland|Austria|Spain|Italy|UK|United Kingdom|Ireland|Luxembourg|Portugal|Poland|Czech|Greece|Cyprus|Hungary|Romania|Slovenia|Aarhus|ETH|EPFL|TU Darmstadt|TUM|TU Graz|KU Leuven|Bristol|Edinburgh|Imperial|Cambridge|Oxford|Bochum|Karlsruhe|Saarbr|Bergen|Munich|Berlin|Paris|Amsterdam|Madrid|Graz|Vienna|Rome|Milano|Lyon|Lille|Lausanne|Geneva|Zurich|Helsinki|Stockholm|Copenhagen|Oslo|Warsaw|Prague|Athens)\b", re.I), "europe"),
    (re.compile(r"\b(Israel|Bar.?Ilan|Weizmann|Technion|Tel Aviv|Hebrew University|BGU|Reichman|IDC Herzliya)\b", re.I), "middle_east"),
    (re.compile(r"\b(UAE|Abu Dhabi|TII|Saudi|KAUST|Qatar)\b", re.I), "middle_east"),
    (re.compile(r"\b(Singapore|NTU|NUS|Australia|Monash|Sydney|Melbourne|New Zealand|Japan|Korea|KAIST|Tokyo|Kyoto|Hong Kong|HKUST|CUHK|Taiwan|China|Tsinghua|Peking|Shanghai|SJTU|Xiamen|Fudan|Tencent)\b", re.I), "asia_pacific"),
    (re.compile(r"\b(Africa|South Africa|Cape Town|Morocco|Egypt|Cairo|Nigeria)\b", re.I), "africa"),
]

AREA_PATTERNS = [
    (re.compile(r"\bmulti.?party computation\b|\bMPC\b", re.I), "mpc"),
    (re.compile(r"\bfunction secret sharing\b|\bFSS\b|\bDPF\b|\bDCF\b", re.I), "fss"),
    (re.compile(r"\bhomomorphic encryption\b|\bFHE\b|\bSHE\b|\bBGV\b|\bCKKS\b|\bTFHE\b", re.I), "fhe"),
    (re.compile(r"\bzero.?knowledge\b|\bZK\b|\bSNARK\b|\bSTARK\b", re.I), "zk"),
    (re.compile(r"\bpost.?quantum\b|\bPQC\b", re.I), "pqc"),
    (re.compile(r"\blattice\b|\bLWE\b|\bSIS\b|\bM-?LWE\b|\bRing-?LWE\b", re.I), "lattice"),
    (re.compile(r"\bsymmetric\b|\bhash function\b|\bAEAD\b|\bblock cipher\b|\bstream cipher\b", re.I), "symmetric"),
    (re.compile(r"\bhardware\b|\bFPGA\b|\bASIC\b|\bVLSI\b|\bembedded\b", re.I), "hardware"),
    (re.compile(r"\bside.?channel\b|\bSCA\b|\bpower analysis\b|\bEM analysis\b|\bfault attack\b", re.I), "side_channel"),
    (re.compile(r"\bprivacy.?preserving (machine learning|ML)\b|\bPPML\b|\bfederated\b", re.I), "ppml"),
    (re.compile(r"\bsearchable encryption\b|\bSSE\b|\bencrypted search\b|\bORAM\b|\bPIR\b", re.I), "sse"),
    (re.compile(r"\bblockchain\b|\bconsensus\b|\bDeFi\b|\bpayment\b", re.I), "blockchain"),
    (re.compile(r"\bformal (methods|verification)\b|\bCoq\b|\bIsabelle\b|\bEasyCrypt\b", re.I), "formal_methods"),
]


def classify_type(text: str) -> str:
    for pat, t in TYPE_PATTERNS:
        if pat.search(text):
            return t
    return "postdoc"  # IACR jobs lean postdoc by default


def classify_region(text: str) -> str:
    for pat, r in REGION_PATTERNS:
        if pat.search(text):
            return r
    return "remote"


def classify_areas(text: str) -> list[str]:
    areas = []
    for pat, a in AREA_PATTERNS:
        if pat.search(text):
            areas.append(a)
    return areas or ["mpc"]


def _strip_html(fragment: str) -> str:
    """Turn an HTML fragment into a single line of readable plain text."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_jobs_html() -> str:
    req = urllib.request.Request(JOBS_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_jobs(page: str) -> list[dict]:
    """Parse the IACR jobs listing HTML into normalized position dicts.

    Each listing carries a numeric id surfaced as id="url-<id>",
    id="position-<id>", id="place-<id>" and id="description-<id>".
    """
    entries = []
    # Preserve listing order; de-dupe ids defensively.
    ids = list(dict.fromkeys(re.findall(r'id="url-(\d+)"', page)))
    for jid in ids:
        title_m = re.search(rf'id="position-{jid}"[^>]*>(.*?)</span>', page, re.S)
        place_m = re.search(rf'id="place-{jid}"[^>]*>(.*?)</h6>', page, re.S)
        desc_m = re.search(rf'id="description-{jid}"[^>]*>(.*?)</div>', page, re.S)

        title = _strip_html(title_m.group(1)) if title_m else ""
        if not title:
            continue
        place = _strip_html(place_m.group(1)) if place_m else ""
        description = _strip_html(desc_m.group(1)) if desc_m else ""

        # "posted on YYYY-MM-DD" appears within each listing block.
        block = page[page.find(f'id="url-{jid}"'):]
        nxt = re.search(r'id="url-\d+"', block[10:])
        if nxt:
            block = block[: nxt.start() + 10]
        posted_m = re.search(r"posted on (\d{4}-\d{2}-\d{2})", block)
        posted = posted_m.group(1) if posted_m else dt.date.today().isoformat()

        # place is usually "<Institution>, <City>, <Country>"
        place_parts = [p.strip() for p in place.split(",") if p.strip()]
        institution = place_parts[0] if place_parts else ""
        country = place_parts[-1] if len(place_parts) > 1 else ""

        text = f"{title} {place} {description}"
        # The canonical item URL is stable, so use it as the dedup key + link.
        link = f"https://iacr.org/jobs/item/{jid}"

        entries.append({
            "name": (institution or title)[:120],
            "role": title[:120],
            "type": classify_type(text),
            "region": classify_region(text),
            "country": country[:60],
            "institution": institution[:120],
            "link": link,
            "deadline": "rolling",
            "posted": posted,
            "added": dt.date.today().isoformat(),
            "area": classify_areas(text),
            "status": "open",
            "note": description[:240],
            "source": "iacr",
        })
    return entries


def load_existing_links() -> set[str]:
    if not EXISTING.exists():
        return set()
    with EXISTING.open() as fh:
        data = yaml.safe_load(fh) or []
    return {item.get("link", "") for item in data if item.get("link")}


def append_to_positions(new_items: list[dict]) -> None:
    """Append new entries to the end of positions.yml, preserving the
    existing hand-curated content and comments."""
    header = (
        "\n# ---------------- AUTO-APPENDED from IACR jobs board"
        f" ({dt.date.today().isoformat()}) ----------------\n"
    )
    body = yaml.safe_dump(
        new_items,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    with EXISTING.open("a") as fh:
        fh.write(header)
        fh.write(body)


def main() -> int:
    existing = load_existing_links()
    page = fetch_jobs_html()
    listings = parse_jobs(page)
    if not listings:
        print("Parsed 0 listings from the IACR jobs board "
              "(page layout may have changed).", file=sys.stderr)
        return 1
    new = [e for e in listings if e["link"] not in existing]
    if not new:
        print(f"Parsed {len(listings)} listings; none are new.")
        return 0
    print(f"{len(new)} new position(s) found; appending to positions.yml.")
    append_to_positions(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
