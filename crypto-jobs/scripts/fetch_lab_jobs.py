#!/usr/bin/env python3
"""
fetch_lab_jobs.py — visits each cryptography lab in _data/labs.yml, finds a
likely "open positions" page, and uses Claude (Haiku) to extract any *current*
openings into the schema used by _data/positions.yml.

Unlike fetch_iacr_jobs.py (one structured board), the 54 lab sites have wildly
different HTML, so a regex parser can't work — Claude reads the prose instead.
Because that extraction is fuzzy (false positives, missed JS-only pages), this
script does NOT publish: it appends proposals to _data/positions.yml tagged
`source: lab`, and the workflow opens a *pull request* for human review. Merging
the PR is what publishes them.

De-dup is by (institution + role), case-insensitive, against what's already in
positions.yml, so re-running never proposes the same opening twice.

Requires ANTHROPIC_API_KEY. If it is unset the script exits 0 without doing
anything, so the workflow can sit dormant until the secret is added.

Run locally:
    ANTHROPIC_API_KEY=sk-ant-... python scripts/fetch_lab_jobs.py
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
LABS = DATA / "labs.yml"
POSITIONS = DATA / "positions.yml"

MODEL = "claude-haiku-4-5"          # cheap model — extraction is a simple task
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
)
PAGE_CHAR_CAP = 12000                # cap text per page fed to the model
FETCH_TIMEOUT = 15                   # seconds per HTTP request

# Anchor text/href hinting at an openings page, best signal first.
OPENING_LINK_RE = re.compile(
    r"vacanc|opening|open position|positions?\b|job|hiring|recruit|"
    r"join (us|the|our)|we'?re hiring|career|phd|post.?doc|ph\.?d",
    re.I,
)

# Shared taxonomy — keep in sync with _data/positions.yml / _config.yml.
VALID_TYPES = ["postdoc", "phd", "faculty", "research_scientist", "intern", "visiting"]
VALID_AREAS = [
    "mpc", "fhe", "fss", "zk", "pqc", "lattice", "symmetric", "hardware",
    "ppml", "sse", "blockchain", "formal_methods", "side_channel",
]

EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "openings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "role": {"type": "string"},
                    "type": {"type": "string", "enum": VALID_TYPES},
                    "areas": {"type": "array", "items": {"type": "string", "enum": VALID_AREAS}},
                    "deadline": {"type": "string"},
                    "apply_url": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["role", "type", "areas", "deadline", "apply_url", "note"],
            },
        }
    },
    "required": ["openings"],
}

SYSTEM_PROMPT = (
    "You extract CURRENTLY-OPEN cryptography research positions from a lab's web "
    "page text. Only report positions that are explicitly open for application "
    "right now (postdoc, PhD, faculty, research scientist, intern, visiting). "
    "Do NOT invent positions, and do NOT report generic 'we sometimes have "
    "openings / email us' statements, past positions, or already-filled roles. "
    "If the page lists no concrete open position, return an empty list. Keep "
    "`note` to one short sentence. Use `apply_url` only if the page gives a real "
    "application/details link; otherwise leave it empty. Pick `areas` only from "
    "the allowed enum, and only those clearly relevant; if unsure, return []."
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


def find_openings_links(page: str, base_url: str) -> list[str]:
    """Return up to 2 same-site URLs that look like an openings page."""
    base_host = urlparse(base_url).netloc
    found: list[str] = []
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page, re.I | re.S):
        href, anchor = m.group(1), strip_html(m.group(2))
        if not OPENING_LINK_RE.search(href) and not OPENING_LINK_RE.search(anchor):
            continue
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        if urlparse(absolute).netloc != base_host:   # stay on the lab's own site
            continue
        if absolute not in found and absolute.rstrip("/") != base_url.rstrip("/"):
            found.append(absolute)
        if len(found) >= 2:
            break
    return found


def gather_text(lab: dict) -> str:
    """Fetch the homepage plus any openings pages and return capped text."""
    link = lab.get("link", "")
    home = fetch(link)
    if not home:
        return ""
    parts = [f"LAB HOMEPAGE ({link}):\n" + strip_html(home)[:PAGE_CHAR_CAP]]
    for sub in find_openings_links(home, link):
        sub_html = fetch(sub)
        if sub_html:
            parts.append(f"\n\nOPENINGS PAGE ({sub}):\n" + strip_html(sub_html)[:PAGE_CHAR_CAP])
    return "\n".join(parts)


def extract_openings(client, lab: dict, text: str) -> list[dict]:
    """Ask Claude to pull current openings from the lab's page text."""
    user = (
        f"Lab: {lab.get('name','')} at {lab.get('institution','')} "
        f"({lab.get('country','')}).\n\nPage text:\n{text}"
    )
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
    )
    blob = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    return data.get("openings", []) if isinstance(data, dict) else []


def existing_keys() -> set[str]:
    """(institution|role) keys already present, to avoid duplicate proposals."""
    if not POSITIONS.exists():
        return set()
    with POSITIONS.open() as fh:
        data = yaml.safe_load(fh) or []
    keys = set()
    for item in data:
        inst = (item.get("institution") or item.get("name") or "").strip().lower()
        role = (item.get("role") or "").strip().lower()
        if inst and role:
            keys.add(f"{inst}|{role}")
    return keys


def to_position(lab: dict, opening: dict) -> dict:
    today = dt.date.today().isoformat()
    return {
        "name": lab.get("name", "")[:120],
        "role": (opening.get("role") or "")[:120],
        "type": opening.get("type") or "postdoc",
        "region": lab.get("region", "remote"),
        "country": (lab.get("country") or "")[:60],
        "institution": (lab.get("institution") or "")[:120],
        "link": opening.get("apply_url") or lab.get("link", ""),
        "deadline": (opening.get("deadline") or "rolling")[:60],
        "posted": today,
        "added": today,
        "area": opening.get("areas") or [],
        "status": "open",
        "note": (opening.get("note") or "")[:240],
        "source": "lab",
    }


def append_proposals(items: list[dict]) -> None:
    header = (
        "\n# ---------------- PROPOSED from lab career pages"
        f" ({dt.date.today().isoformat()}) — review before keeping ----------------\n"
    )
    body = yaml.safe_dump(items, sort_keys=False, allow_unicode=True, default_flow_style=False)
    with POSITIONS.open("a") as fh:
        fh.write(header)
        fh.write(body)


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; skipping lab scrape (no-op).")
        return 0
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.stderr.write("anthropic SDK missing; install with: pip install anthropic\n")
        return 2

    client = Anthropic()
    with LABS.open() as fh:
        labs = yaml.safe_load(fh) or []

    seen = existing_keys()
    proposals: list[dict] = []
    scanned = failed = 0

    for lab in labs:
        if not lab.get("link"):
            continue
        text = gather_text(lab)
        if not text:
            failed += 1
            continue
        scanned += 1
        try:
            openings = extract_openings(client, lab, text)
        except Exception as exc:  # network/API hiccup on one lab shouldn't kill the run
            sys.stderr.write(f"  ! {lab.get('name','?')}: {exc}\n")
            failed += 1
            continue
        for op in openings:
            if not (op.get("role") or "").strip():
                continue
            pos = to_position(lab, op)
            key = f"{pos['institution'].strip().lower()}|{pos['role'].strip().lower()}"
            if key in seen:
                continue
            seen.add(key)
            proposals.append(pos)
            print(f"  + {pos['institution']}: {pos['role']}")

    print(f"\nScanned {scanned} labs ({failed} unreachable); "
          f"{len(proposals)} new opening(s) proposed.")
    if proposals:
        append_proposals(proposals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
