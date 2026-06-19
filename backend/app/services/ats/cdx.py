"""CommonCrawl CDX index discovery — extract ATS company slugs.

Ported faithfully from Allen's pipeline/cdx.py (feature/dev-automation): download
the crawl's ``cluster.idx`` (~100MB), binary-search a per-platform SURT prefix in
O(log 878K), download the matching CDXJ shard files (~500MB), and regex-extract
company slugs from the URLs. Downloads are ephemeral (memory only) — only the
extracted slugs persist (in omni_ats_slugs). stdlib only (urllib/gzip/bisect).

This is the SLUG-DISCOVERY half of the ATS sources; the per-company job fetch
lives in the Rust muscle (handlers/ats.rs). See [[project_ats_cdx_port]].
"""

from __future__ import annotations

import bisect
import gzip
import io
import json
import urllib.request
from collections.abc import Callable, Iterator

_CDX_BASE = "https://data.commoncrawl.org/cc-index/collections"
_COLLINFO = "https://index.commoncrawl.org/collinfo.json"


def get_available_crawls() -> list[dict]:
    """List CommonCrawl crawls, newest first. [0]['id'] is the latest crawl id."""
    req = urllib.request.Request(_COLLINFO)
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 — fixed trusted URL
        return json.loads(r.read())


def latest_crawl() -> str | None:
    crawls = get_available_crawls()
    return crawls[0]["id"] if crawls else None


def download_cluster_idx(crawl: str) -> bytes | None:
    """Download a crawl's cluster.idx. Returns None on 404 (missing crawl)."""
    url = f"{_CDX_BASE}/{crawl}/indexes/cluster.idx"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310
            return r.read()
    except urllib.request.HTTPError as e:
        if e.code == 404:
            return None
        raise


def parse_cluster_idx(data: bytes) -> list[tuple[str, str]]:
    """Parse cluster.idx into sorted (surt_key, cdx_filename) tuples (~878K)."""
    text = data.decode("latin-1", errors="replace")
    entries: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        surt_key = parts[0].rsplit(" ", 1)[0]
        entries.append((surt_key, parts[1].strip()))
    return entries


def find_cdx_files(entries: list[tuple[str, str]], surt_prefix: str) -> set[str]:
    """Binary-search the sorted entries for surt_prefix; collect matching shards."""
    surts = [e[0] for e in entries]
    pos = bisect.bisect_left(surts, surt_prefix)
    if pos >= len(entries):
        return set()
    cdx_files: set[str] = set()
    cdx_files.add(entries[pos][1])
    i = pos + 1
    while i < len(entries) and entries[i][0].startswith(surt_prefix):
        cdx_files.add(entries[i][1])
        i += 1
    return cdx_files


def download_cdx(crawl: str, filename: str) -> bytes:
    url = f"{_CDX_BASE}/{crawl}/indexes/{filename}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310
        return r.read()


def parse_cdxj(data: bytes, extractor: Callable[[str], Iterator[str]]) -> Iterator[str]:
    """Yield unique slugs from a gzipped CDXJ shard via the platform's extractor."""
    seen: set[str] = set()
    buf = io.BytesIO(data)
    with gzip.GzipFile(fileobj=buf) as f:
        for raw_line in f:
            line = raw_line.decode("latin-1", errors="replace").strip()
            if not line:
                continue
            space_idx = line.find(" ", line.find(" ") + 1)
            if space_idx < 0:
                continue
            raw_json = line[space_idx + 1:]
            try:
                meta = json.loads(raw_json)
                url = meta.get("url", "")
                for slug in extractor(url):
                    if 1 < len(slug) < 100 and slug not in seen:
                        seen.add(slug)
                        yield slug
            except (ValueError, json.JSONDecodeError):
                continue


def discover_slugs(
    crawl: str,
    surt_prefix: str,
    extractor: Callable[[str], Iterator[str]],
    progress_callback: Callable[[int], None] | None = None,
) -> list[str]:
    """Full discovery for one platform/crawl: cluster.idx → shards → slugs."""
    all_slugs: set[str] = set()

    cluster_data = download_cluster_idx(crawl)
    if cluster_data is None:
        return []
    entries = parse_cluster_idx(cluster_data)

    cdx_files = find_cdx_files(entries, surt_prefix)
    if not cdx_files:
        return []

    total_files = len(cdx_files)
    for idx, fname in enumerate(sorted(cdx_files)):
        cdx_data = download_cdx(crawl, fname)
        for slug in parse_cdxj(cdx_data, extractor):
            all_slugs.add(slug)
        if progress_callback:
            progress_callback(int((idx + 1) / total_files * 100))

    return list(all_slugs)
