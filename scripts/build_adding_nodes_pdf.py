"""Render docs/adding-nodes.md to a polished PDF using:
    pandoc (gfm -> html5)
  + post-process Mermaid blocks (unescape + strip <code>, embed mermaid.js)
  + headless Chrome via subprocess (no Playwright dep)

Output: C:\\Users\\navij\\Downloads\\Adding_Nodes.pdf

Theme: dark slate + teal accents, no purple, code blocks wrap with hanging
indent, headings get break-after:avoid-page so we don't end a page on a
heading.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Multi-doc registry. Pass a key as argv[1] to pick one; default builds
# adding-nodes for backwards compatibility.
DOCS = {
    "adding-nodes": (
        REPO / "docs" / "adding-nodes.md",
        Path.home() / "Downloads" / "Adding_Nodes.pdf",
        "Adding a node",
    ),
    "events": (
        REPO / "docs" / "event-streaming-and-postgres.md",
        Path.home() / "Downloads" / "Event_Streaming_and_Postgres.pdf",
        "How Omni stores data",
    ),
}

_doc_key = sys.argv[1] if len(sys.argv) > 1 else "adding-nodes"
if _doc_key not in DOCS:
    sys.exit(f"unknown doc key: {_doc_key}. choices: {', '.join(DOCS)}")
MD, OUT_PDF, _DOC_TITLE = DOCS[_doc_key]

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def have_pandoc() -> str:
    p = shutil.which("pandoc")
    if not p:
        sys.exit("pandoc not on PATH. Install it (anaconda already ships it).")
    return p


def md_to_html_body(md_text: str) -> str:
    """pandoc gfm -> html5 fragment. Mermaid fences come through as
    <pre><code class='language-mermaid'>...</code></pre>."""
    proc = subprocess.run(
        [have_pandoc(), "-f", "gfm", "-t", "html5", "--no-highlight"],
        input=md_text.encode("utf-8"),
        capture_output=True,
        check=True,
    )
    return proc.stdout.decode("utf-8")


def fix_mermaid(html: str) -> str:
    """pandoc wraps Mermaid in <pre><code class='language-mermaid'>...</code></pre>
    with entities escaped. Mermaid wants raw text inside an element with class
    'mermaid'. Unescape and rewrite."""

    def unesc(s: str) -> str:
        return (
            s.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
        )

    # Match ONLY blocks pandoc tagged with language=mermaid. With --no-highlight,
    # gfm pandoc emits:   <pre class="mermaid"><code>...</code></pre>
    # The class lives on the OUTER <pre>, the inner <code> is bare. ASCII-art
    # blocks (no info string) come out as plain <pre><code>...</code></pre>
    # and must NOT match here, or they get parsed as Mermaid and render as
    # "Syntax error in text".
    pattern = re.compile(
        r'<pre\s+class="[^"]*\bmermaid\b[^"]*"\s*>'
        r'<code[^>]*>(.*?)</code></pre>',
        re.DOTALL,
    )
    return pattern.sub(lambda m: f'<pre class="mermaid">{unesc(m.group(1))}</pre>', html)


CSS = """
:root {
  --bg: #ffffff;
  --fg: #1a1a1a;
  --muted: #595959;
  --accent: #1a1a1a;
  --link: #0b5fff;
  --border: #d0d0d0;
  --rule: #1a1a1a;
  --table-head-bg: #f3f3f3;
  --table-stripe: #fafafa;
  --code-bg: #f6f6f6;
  --code-fg: #1a1a1a;
  --code-border: #d0d0d0;
  --blockquote-border: #1a1a1a;
}
* { box-sizing: border-box; }
html, body { background: var(--bg); color: var(--fg); }
body {
  font: 11pt/1.55 "Charter", "Iowan Old Style", Georgia, "Times New Roman", serif;
  margin: 18mm 22mm;
  max-width: none;
}
h1, h2, h3, h4 {
  color: var(--accent);
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-weight: 600;
  break-after: avoid-page;
  line-height: 1.25;
}
h1 {
  font-size: 22pt;
  margin: 0 0 14pt;
  padding-bottom: 8pt;
  border-bottom: 2px solid var(--rule);
}
h2 {
  font-size: 14pt;
  margin-top: 24pt;
  margin-bottom: 6pt;
  padding-bottom: 3pt;
  border-bottom: 1px solid var(--border);
}
h3 {
  font-size: 12pt;
  margin-top: 16pt;
  margin-bottom: 4pt;
  color: var(--accent);
}
h4 {
  font-size: 10.5pt;
  margin-top: 12pt;
  margin-bottom: 3pt;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
p, li { color: var(--fg); }
p { margin: 0 0 8pt; }
strong { color: var(--accent); font-weight: 600; }
em { color: var(--fg); font-style: italic; }
blockquote {
  border-left: 3px solid var(--blockquote-border);
  margin: 10pt 0;
  padding: 4pt 12pt;
  color: var(--muted);
  background: var(--code-bg);
}
ul, ol { padding-left: 22px; margin: 6pt 0 10pt; }
li { margin: 3pt 0; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 10pt 0 14pt;
  font-size: 9.5pt;
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  page-break-inside: auto;
}
th, td {
  border: 1px solid var(--border);
  padding: 5pt 8pt;
  text-align: left;
  vertical-align: top;
}
th {
  background: var(--table-head-bg);
  color: var(--accent);
  font-weight: 600;
}
tbody tr:nth-child(even) td { background: var(--table-stripe); }
code {
  background: var(--code-bg);
  color: var(--code-fg);
  padding: 1px 4px;
  border-radius: 2px;
  font: 9.5pt/1.45 "SF Mono", "JetBrains Mono", Consolas, "Liberation Mono", monospace;
}
pre {
  background: var(--code-bg);
  color: var(--code-fg);
  padding: 10pt 12pt 10pt 30pt;
  border: 1px solid var(--code-border);
  border-radius: 3px;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  text-indent: -22pt;
  font: 9pt/1.5 "SF Mono", "JetBrains Mono", Consolas, "Liberation Mono", monospace;
  page-break-inside: auto;
}
pre code { background: none; padding: 0; font-size: inherit; color: inherit; }
pre.mermaid {
  background: transparent;
  border: none;
  padding: 12pt 0;
  text-indent: 0;
  white-space: normal;
  text-align: center;
}
pre.mermaid svg {
  width: 100% !important;
  max-width: 100% !important;
  height: auto !important;
  display: block;
  margin: 0 auto;
}
hr { border: none; border-top: 1px solid var(--border); margin: 18pt 0; }
"""


def build_html(body_html: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{_DOC_TITLE}</title>
<style>{CSS}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
  window.addEventListener('DOMContentLoaded', () => {{
    mermaid.initialize({{
      startOnLoad: false,
      theme: 'base',
      themeVariables: {{
        background: '#ffffff',
        primaryColor: '#ffffff',
        primaryTextColor: '#1a1a1a',
        primaryBorderColor: '#1a1a1a',
        lineColor: '#1a1a1a',
        secondaryColor: '#f3f3f3',
        tertiaryColor: '#fafafa',
        noteBkgColor: '#f6f6f6',
        noteTextColor: '#1a1a1a',
        noteBorderColor: '#1a1a1a',
        fontFamily: '"Helvetica Neue", Helvetica, Arial, sans-serif',
        fontSize: '18px',
      }},
      flowchart: {{
        useMaxWidth: true,
        htmlLabels: true,
        curve: 'basis',
        nodeSpacing: 28,
        rankSpacing: 50,
        padding: 8,
      }},
      sequence: {{
        useMaxWidth: true,
        actorMargin: 60,
        messageFontSize: 14,
      }},
    }});
    mermaid.run({{ querySelector: 'pre.mermaid' }}).then(() => {{
      window.__mermaidDone = true;
    }});
  }});
</script>
</head>
<body>
{body_html}
</body>
</html>
"""


def chrome_pdf(html_path: Path, pdf_path: Path) -> None:
    """Use headless Chrome to render the HTML to PDF.

    Chrome's --print-to-pdf doesn't wait for JS by default. To give Mermaid
    time to render we use --virtual-time-budget plus a hold on
    window.__mermaidDone via document.title (Chrome flushes pending JS for
    the virtual budget regardless of network)."""
    if not Path(CHROME).exists():
        sys.exit(f"Chrome not at {CHROME}")
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        # 30s of virtual time for fonts + Mermaid CDN + render
        "--virtual-time-budget=30000",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={pdf_path}",
        "--no-pdf-header-footer",
        html_path.as_uri(),
    ]
    print("[render] chrome ...")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not pdf_path.exists():
        print("[render] STDERR:", proc.stderr[-400:])
        sys.exit("Chrome PDF render failed.")


def main() -> int:
    if not MD.exists():
        sys.exit(f"markdown source missing: {MD}")
    md_text = MD.read_text(encoding="utf-8")
    body = md_to_html_body(md_text)
    body = fix_mermaid(body)
    html = build_html(body)

    tmp = Path(tempfile.mkdtemp(prefix="omni-pdf-"))
    html_path = tmp / "adding-nodes.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"[render] html  -> {html_path}")
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    chrome_pdf(html_path, OUT_PDF)
    size = OUT_PDF.stat().st_size
    print(f"[render] pdf   -> {OUT_PDF}  ({size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
