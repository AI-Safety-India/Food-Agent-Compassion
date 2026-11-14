"""Build a formal document-style HTML (for PDF printing) of the SF report draft:
title page, table of contents, numbered pages, plain report typography.
Run: python -I -B build_formal_html.py   (needs the `markdown` package)"""
import os
import re
import sys

import markdown

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "SF_REPORT_v3_2026-11-15.md")
OUT = os.path.join(HERE, "SF_REPORT_v3_2026-11-15_formal.html")

CSS = """
@page{size:A4;margin:22mm 20mm 22mm 20mm;
  @bottom-center{content:counter(page);font-family:Calibri,Arial,sans-serif;font-size:9pt;color:#555}
  @top-right{content:"Your AI Meal Planner Would Order You a Live Lobster · Draft";font-family:Calibri,Arial,sans-serif;font-size:8.5pt;color:#777}}
@page :first{@bottom-center{content:none}@top-right{content:none}}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;font-family:Calibri,"Segoe UI",Arial,sans-serif;font-size:10.8pt;line-height:1.5;color:#1a1a1a;font-variant-numeric:tabular-nums}
h1,h2,h3{font-family:Cambria,Georgia,"Times New Roman",serif;color:#0f3d2e;font-weight:700;line-height:1.2}
h2{font-size:16pt;margin:22pt 0 7pt;break-after:avoid}
h3{font-size:12.5pt;margin:14pt 0 5pt;break-after:avoid}
p{margin:0 0 7pt;text-align:left}
ul,ol{margin:0 0 8pt 0;padding-left:20pt}li{margin-bottom:3pt}
strong{font-weight:700}
pre{background:#f3f6f5;border:1px solid #dfe7e3;border-radius:8px;padding:10px 14px;white-space:pre-wrap;font-size:0.92em;line-height:1.5;break-inside:avoid}pre code{background:none;padding:0}
code{font-family:Consolas,"Courier New",monospace;font-size:9pt;background:#f2f4f3;padding:0 3px}
blockquote{margin:9pt 0 11pt;padding:7pt 12pt;border:1px solid #cfe3d9;background:#f3f8f5}
blockquote p{margin:0;font-style:italic}
hr{display:none}
table{width:100%;border-collapse:collapse;margin:6pt 0 10pt;font-size:9.4pt}
th{background:#0f3d2e;color:#fff;font-weight:700;text-align:left;padding:4pt 6pt;vertical-align:bottom}
td{border-bottom:1px solid #d9dedc;padding:3.5pt 6pt;vertical-align:top}
tr:nth-child(even) td{background:#f6f8f7}
tr{break-inside:avoid}p:has(+ .tbl),p:has(+ table){break-after:avoid}thead{display:table-header-group}
/* title page */
.titlepage{height:247mm;display:flex;flex-direction:column;justify-content:center;break-after:page}
.titlepage .tag{font-family:Calibri,Arial,sans-serif;font-size:11pt;letter-spacing:.18em;text-transform:uppercase;color:#12a36a;font-weight:700}
.titlepage h1{font-size:30pt;margin:10pt 0 8pt;color:#0f3d2e}
.titlepage .sub{font-family:Cambria,Georgia,serif;font-size:15pt;color:#444;margin-bottom:28pt}
.titlepage .meta{font-size:11.5pt;color:#333;border-top:1px solid #cfd8d4;padding-top:12pt}
.titlepage .meta p{margin:0 0 4pt}
.titlepage .draft{display:inline-block;margin-top:18pt;border:1.5px solid #b23b22;color:#b23b22;font-weight:700;letter-spacing:.14em;padding:3pt 10pt;font-size:10pt}
/* contents */
.toc{break-after:page}
.toc h2{margin-top:0}
.toc ol{list-style:none;padding-left:0}
.toc li{display:flex;gap:8pt;border-bottom:1px dotted #c7cfcb;padding:4pt 0;margin:0;font-size:11pt}
.toc li span{color:#0f3d2e;font-weight:700;min-width:22pt}
/* key findings */
.keybox{border:1px solid #cfe3d9;background:#f3f8f5;padding:10pt 14pt 6pt;margin:0 0 12pt;break-inside:avoid}
.keybox h2{margin-top:0}
.take{font-weight:700;color:#0f3d2e}
"""

md = open(SRC, encoding="utf-8").read()
# split off the cover lines (title, subtitle, org line, byline) before the first rule
head, rest = md.split("\n---\n", 1)
lines = [l.strip() for l in head.splitlines() if l.strip()]
title = lines[0].lstrip("# ").strip()
subtitle = lines[1].lstrip("# ").strip()
org = lines[2].strip("*").strip()
byline = lines[3]
authors, date, status = [x.strip() for x in byline.split("·")]

body = markdown.markdown(rest, extensions=["tables", "sane_lists", "fenced_code"])
# key findings box
k0 = body.index("<h2>Key findings</h2>")
k1 = body.index("<hr", k0)
key = body[k0:k1].replace("<p><strong>Take-home message:", '<p class="take"><strong>Take-home message:')
body = body[:k0] + '<section class="keybox">' + key + "</section>" + body[k1:]
# table of contents from h2 headings
heads = re.findall(r"<h2>(.*?)</h2>", body)
toc_items = []
for h in heads:
    m = re.match(r"(\d+)\.\s+(.*)", h)
    if m:
        toc_items.append(f"<li><span>{m.group(1)}</span>{m.group(2)}</li>")
    else:
        toc_items.append(f"<li><span></span>{h}</li>")
toc = '<section class="toc"><h2>Contents</h2><ol>' + "".join(toc_items) + "</ol></section>"

titlepage = f"""<section class="titlepage">
<div class="tag">Research report</div>
<h1>{title}</h1>
<div class="sub">{subtitle}</div>
<div class="meta"><p><strong>{authors}</strong></p><p>{org}</p><p>{date}</p></div>
<div><span class="draft">{status.upper()}</span></div>
</section>"""

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{title}: draft report</title><style>{CSS}</style></head><body>
{titlepage}{toc}{body}
</body></html>"""
open(OUT, "w", encoding="utf-8").write(html)
print("wrote", OUT, "| sections:", len(heads))
