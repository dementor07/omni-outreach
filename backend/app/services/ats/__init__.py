"""ATS lead-source engine — CommonCrawl-index company discovery across 12 ATS
platforms (Greenhouse, Ashby, Workday, …).

Split:
  - plugins.py  — per-platform discovery defs (surt_prefix / slug_regex / validators)
  - cdx.py      — CommonCrawl cluster.idx binary search + CDXJ slug extraction
  - discover.py — run one (platform, crawl) discovery and persist
  - store.py    — omni_ats_slugs / omni_ats_crawls persistence (global, no RLS)

The per-company JOB fetch lives in the Rust muscle (handlers/ats.rs); this
package is slug discovery + storage. See [[project_ats_cdx_port]].
"""
