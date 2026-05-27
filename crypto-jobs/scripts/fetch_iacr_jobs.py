#!/usr/bin/env python3
"""
fetch_iacr_jobs.py — pulls https://iacr.org/jobs/rss.xml, normalizes each
posting into the schema used by _data/positions.yml, and writes the
*new* entries (not already present in positions.yml) to
_data/positions.iacr.auto.yml.

A separate workflow step then merges that into _data/positions.yml via
an open PR, so a human can review before publishing.

Run locally:
    python scripts/fetch_iacr_jobs.py
"""

from __future__ import annotations

import os
import re
import sys
import datetime as dt
from pathlib import Path

try:
    import feedparser  # pip install feedparser
except ImportError:
    sys.stderr.write("feedparser missing; install with: pip install feedparser pyyaml\n")
    sys.exit(2)

try:
    import yaml  # pip install pyyaml
except ImportError:
    sys.stderr.write("pyyaml missing; install with: pip install pyyaml\n")
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "_data"
EXISTING = DATA / "positions.yml"
AUTO_OUT = DATA / "positions.iacr.auto.yml"

RSS_URL = "https://iacr.org/jobs/rss.xml"

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


def parse_feed() -> list[dict]:
    feed = feedparser.parse(RSS_URL)
    entries = []
    for e in feed.entries:
        title = e.get("title", "").strip()
        link = e.get("link", "").strip()
        summary = e.get("summary", "")
        published = e.get("published_parsed")
        text = f"{title} {summary}"

        # Many IACR feed titles look like "Postdoc at <Institution>" or
        # "<Institution> — <Role>"
        parts = re.split(r"\s+[–—-]\s+|, ", title, maxsplit=1)
        if len(parts) == 2:
            role_or_name, institution = parts[0], parts[1]
        else:
            role_or_name = title
            institution = ""

        entries.append({
            "name": title[:120],
            "role": role_or_name[:120],
            "type": classify_type(text),
            "region": classify_region(text),
            "country": "",
            "institution": institution[:120],
            "link": link,
            "deadline": "rolling",
            "posted": dt.date(*published[:3]).isoformat() if published else dt.date.today().isoformat(),
            "area": classify_areas(text),
            "status": "open",
            "source": "iacr",
        })
    return entries


def load_existing_links() -> set[str]:
    if not EXISTING.exists():
        return set()
    with EXISTING.open() as fh:
        data = yaml.safe_load(fh) or []
    return {item.get("link", "") for item in data if item.get("link")}


def write_auto(new_items: list[dict]) -> None:
    header = (
        "# Auto-generated from https://iacr.org/jobs/rss.xml\n"
        f"# Generated: {dt.datetime.utcnow().isoformat()}Z\n"
        "# These entries are candidates for merging into positions.yml.\n"
        "# Open the PR opened by the GitHub Action, review, and merge.\n\n"
    )
    with AUTO_OUT.open("w") as fh:
        fh.write(header)
        yaml.safe_dump(new_items, fh, sort_keys=False, allow_unicode=True, default_flow_style=False)


def main() -> int:
    existing = load_existing_links()
    feed_entries = parse_feed()
    new = [e for e in feed_entries if e["link"] not in existing]
    if not new:
        print("No new positions in the IACR feed.")
        # still write an empty file so the workflow can detect "no changes"
        AUTO_OUT.write_text("# No new entries.\n")
        return 0
    print(f"{len(new)} new position(s) found.")
    write_auto(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
