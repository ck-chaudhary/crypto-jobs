#!/usr/bin/env python3
"""
fetch_scholarships.py — refresh scholarship & fellowship listings by following
each provider's page (DAAD, MSCA, Fulbright, …) and using Claude (Haiku) to
extract currently-open awards *with their deadlines*.

Like fetch_lab_jobs.py, provider pages have no common HTML structure, so a
regex parser can't work — Claude reads the prose. And like that script this is
DELIBERATELY review-gated: LLM extraction is fuzzy (wrong deadlines, invented
programmes), so nothing auto-publishes. It appends proposals to
_data/scholarships.yml tagged `source: scrape`, and the workflow opens a PULL
REQUEST for a human to check the deadlines before merging.

Two modes, run together each pass:
  1. Refresh — visit every provider already in scholarships.yml and pull the
     current-cycle deadline / any new sub-programmes.
  2. Discover — visit the portal index pages in SEED_PORTALS (DAAD database,
     EURAXESS, Erasmus catalogue, …) and pull scholarships relevant to
     security / privacy / cryptography or open to any field.

De-dup is by (provider|name), case-insensitive, against what's already in
scholarships.yml, so re-running never proposes the same award twice.

Requires ANTHROPIC_API_KEY. If it is unset the script exits 0 without doing
anything, so the workflow can sit dormant until the secret is added.

Run locally:
    ANTHROPIC_API_KEY=sk-ant-... python scripts/fetch_scholarships.py
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import datetime as dt
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import yaml  # pip install pyyaml
except ImportError:
    sys.stderr.write("pyyaml missing; install with: pip install pyyaml\n")
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "_data"
SCHOLARSHIPS = DATA / "scholarships.yml"

MODEL = "claude-haiku-4-5"          # cheap model — extraction is a simple task
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
)
PAGE_CHAR_CAP = 14000                # cap text per page fed to the model
FETCH_TIMEOUT = 15                   # seconds per HTTP request

# Portal / index pages that aggregate many scholarships. Discover mode scans
# these for security/privacy/crypto-relevant or generic awards. Add more here.
SEED_PORTALS = [
    {
        "provider": "DAAD",
        "region": "europe", "country": "Germany",
        "url": "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
    },
    {
        "provider": "European Commission (MSCA)",
        "region": "europe", "country": "EU / associated countries",
        "url": "https://marie-sklodowska-curie-actions.ec.europa.eu/actions/postdoctoral-fellowships",
    },
    {
        "provider": "European Commission (Erasmus+)",
        "region": "europe", "country": "Multiple EU countries",
        "url": "https://www.eacea.ec.europa.eu/scholarships/emjmd-catalogue_en",
    },
    {
        "provider": "EURAXESS",
        "region": "europe", "country": "Europe",
        "url": "https://euraxess.ec.europa.eu/jobs/search?keywords=cryptography",
    },
]

# Anchor text/href hinting at a deadline / apply / current-call page.
DEADLINE_LINK_RE = re.compile(
    r"deadline|apply|application|how to apply|closing date|call\b|"
    r"eligib|current|open call|202\d|fellowship|scholarship|award",
    re.I,
)

# Shared taxonomies — keep in sync with _data/scholarships.yml / _config.yml.
VALID_LEVELS = ["masters", "phd", "postdoc", "faculty", "any"]
VALID_FOCUS = ["cryptography", "security", "privacy", "generic"]
VALID_REGIONS = [
    "india", "europe", "north_america", "asia_pacific",
    "middle_east", "africa", "worldwide",
]

EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scholarships": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "level": {"type": "string", "enum": VALID_LEVELS},
                    "focus": {"type": "array", "items": {"type": "string", "enum": VALID_FOCUS}},
                    "eligibility": {"type": "string"},
                    "funding": {"type": "string"},
                    "deadline": {"type": "string"},
                    "apply_url": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["name", "level", "focus", "eligibility",
                             "funding", "deadline", "apply_url", "note"],
            },
        }
    },
    "required": ["scholarships"],
}

SYSTEM_PROMPT = (
    "You extract scholarships & fellowships from a funding provider's web page "
    "text. Report only awards that fund research/study a CRYPTOGRAPHY, SECURITY "
    "or PRIVACY researcher could hold: either explicitly in those fields, OR "
    "open to any field (tag those `generic`). For each, capture the exact "
    "application DEADLINE as printed — an ISO date (YYYY-MM-DD) if a specific "
    "date is given, else 'rolling' or 'annual'. Never invent a deadline; if "
    "none is stated use 'annual'. Set `level` to the career stage funded "
    "(masters, phd, postdoc, faculty, or any). Choose `focus` only from the "
    "allowed enum. Do NOT invent programmes, and skip generic navigation, past "
    "cycles, or awards clearly unrelated to STEM/CS. Keep `note` to one short "
    "sentence. Use `apply_url` only if the page gives a real details/apply "
    "link; otherwise leave it empty. If the page lists none, return an empty "
    "list."
)


def fetch(url: str) -> str | None:
    """Fetch a URL, returning decoded text or None on any failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype and ctype:
                return None
            raw = resp.read(2_000_000)  # 2 MB ceiling
            return raw.decode("utf-8", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None


def strip_html(page: str) -> str:
    """Collapse an HTML page into a single readable line of text."""
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def find_deadline_links(page: str, base_url: str) -> list[str]:
    """Return up to 2 same-site URLs that look like a deadline/apply page."""
    base_host = urlparse(base_url).netloc
    found: list[str] = []
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page, re.I | re.S):
        href, anchor = m.group(1), strip_html(m.group(2))
        if not DEADLINE_LINK_RE.search(href) and not DEADLINE_LINK_RE.search(anchor):
            continue
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        if urlparse(absolute).netloc != base_host:   # stay on the provider's own site
            continue
        if absolute not in found and absolute.rstrip("/") != base_url.rstrip("/"):
            found.append(absolute)
        if len(found) >= 2:
            break
    return found


def gather_text(link: str) -> str:
    """Fetch a provider page plus any deadline/apply pages, capped."""
    home = fetch(link)
    if not home:
        return ""
    parts = [f"PROVIDER PAGE ({link}):\n" + strip_html(home)[:PAGE_CHAR_CAP]]
    for sub in find_deadline_links(home, link):
        sub_html = fetch(sub)
        if sub_html:
            parts.append(f"\n\nDEADLINE/APPLY PAGE ({sub}):\n" + strip_html(sub_html)[:PAGE_CHAR_CAP])
    return "\n".join(parts)


def extract(client, context: str, text: str) -> list[dict]:
    """Ask Claude to pull scholarships (with deadlines) from page text."""
    user = f"{context}\n\nPage text:\n{text}"
    msg = client.messages.create(
        model=MODEL,
        max_tokens=3072,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
    )
    blob = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    return data.get("scholarships", []) if isinstance(data, dict) else []


def load_existing() -> list[dict]:
    if not SCHOLARSHIPS.exists():
        return []
    with SCHOLARSHIPS.open() as fh:
        return yaml.safe_load(fh) or []


def existing_keys(existing: list[dict]) -> set[str]:
    """(provider|name) keys already present, to avoid duplicate proposals."""
    keys = set()
    for item in existing:
        prov = (item.get("provider") or "").strip().lower()
        name = (item.get("name") or "").strip().lower()
        if prov and name:
            keys.add(f"{prov}|{name}")
    return keys


def valid_region(region: str) -> str:
    return region if region in VALID_REGIONS else "worldwide"


def to_entry(provider: str, region: str, country: str, sch: dict) -> dict:
    today = dt.date.today().isoformat()
    deadline = (sch.get("deadline") or "annual").strip()[:60]
    status = "annual"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", deadline):
        status = "open"
    elif deadline.lower() == "rolling":
        status = "rolling"
    return {
        "name": (sch.get("name") or "")[:140],
        "provider": provider[:100],
        "level": sch.get("level") or "any",
        "region": valid_region(region),
        "country": (country or "")[:80],
        "eligibility": (sch.get("eligibility") or "")[:200],
        "focus": sch.get("focus") or ["generic"],
        "funding": (sch.get("funding") or "")[:200],
        "link": sch.get("apply_url") or "",
        "deadline": deadline,
        "posted": today,
        "added": today,
        "status": status,
        "note": (sch.get("note") or "")[:240],
        "source": "scrape",
    }


def append_proposals(items: list[dict]) -> None:
    header = (
        "\n# ---------------- PROPOSED from provider pages"
        f" ({dt.date.today().isoformat()}) — verify DEADLINES before keeping ----------------\n"
    )
    body = yaml.safe_dump(items, sort_keys=False, allow_unicode=True, default_flow_style=False)
    with SCHOLARSHIPS.open("a") as fh:
        fh.write(header)
        fh.write(body)


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; skipping scholarship scrape (no-op).")
        return 0
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.stderr.write("anthropic SDK missing; install with: pip install anthropic\n")
        return 2

    client = Anthropic()
    existing = load_existing()
    seen = existing_keys(existing)
    proposals: list[dict] = []
    scanned = failed = 0

    # Sources = every curated provider link + the discovery portals.
    sources: list[dict] = []
    for item in existing:
        if item.get("link"):
            sources.append({
                "provider": item.get("provider", ""),
                "region": item.get("region", "worldwide"),
                "country": item.get("country", ""),
                "url": item["link"],
                "context": (
                    f"Provider: {item.get('provider','')}. This page should list "
                    f"the award '{item.get('name','')}' and its current deadline; "
                    "also report any related sub-programmes on the page."
                ),
            })
    for portal in SEED_PORTALS:
        sources.append({
            **portal,
            "context": (
                f"Portal: {portal['provider']}. This index lists many awards — "
                "report those relevant to cryptography/security/privacy or open "
                "to any field, each with its deadline."
            ),
        })

    for src in sources:
        text = gather_text(src["url"])
        if not text:
            failed += 1
            continue
        scanned += 1
        try:
            found = extract(client, src["context"], text)
        except Exception as exc:  # one bad source shouldn't kill the whole run
            sys.stderr.write(f"  ! {src.get('provider','?')}: {exc}\n")
            failed += 1
            continue
        for sch in found:
            if not (sch.get("name") or "").strip():
                continue
            entry = to_entry(src["provider"], src["region"], src.get("country", ""), sch)
            key = f"{entry['provider'].strip().lower()}|{entry['name'].strip().lower()}"
            if key in seen:
                continue
            seen.add(key)
            proposals.append(entry)
            print(f"  + {entry['provider']}: {entry['name']} (deadline {entry['deadline']})")

    print(f"\nScanned {scanned} sources ({failed} unreachable); "
          f"{len(proposals)} new scholarship(s) proposed.")
    if proposals:
        append_proposals(proposals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
