"""Build a formal document-style HTML (for PDF printing) of the SF report:
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
@page{size:A4;margin:25mm 24mm 25mm 24mm;
  @bottom-center{content:counter(page);font-family:Cambria,"Times New Roman",serif;font-size:10pt;color:#000}
  @top-center{content:"Your AI Meal Planner Would Order You a Live Lobster · SF Report";font-family:Cambria,"Times New Roman",serif;font-size:9pt;font-style:italic;color:#000}}
@page :first{@bottom-center{content:none}@top-center{content:none}}
*{box-sizing:border-box}
body{margin:0;font-family:Cambria,"Times New Roman",Times,serif;font-size:11pt;line-height:1.45;color:#000;font-variant-numeric:lining-nums tabular-nums;hyphens:auto}
a{color:#000;text-decoration:none}
h1,h2,h3{font-family:Cambria,"Times New Roman",Times,serif;color:#000;font-weight:700;line-height:1.25}
h2{font-size:14pt;margin:20pt 0 6pt;break-after:avoid}
h3{font-size:11.5pt;margin:13pt 0 4pt;break-after:avoid;font-style:italic}
p{margin:0 0 7pt;text-align:justify}
ul,ol{margin:0 0 8pt 0;padding-left:18pt}li{margin-bottom:2.5pt;text-align:justify}
strong{font-weight:700}
pre{border:0.6pt solid #000;padding:7pt 10pt;white-space:pre-wrap;font-size:9pt;line-height:1.45;break-inside:avoid;margin:6pt 0 10pt}
pre code{background:none;padding:0}
code{font-family:"Courier New",Consolas,monospace;font-size:9pt}
blockquote{margin:8pt 18pt 10pt;padding:0}
blockquote p{margin:0;font-style:italic}
hr{display:none}
table{width:100%;border-collapse:collapse;margin:4pt 0 12pt;font-size:9.5pt;border-top:1.2pt solid #000;border-bottom:1.2pt solid #000}
th{font-weight:700;text-align:left;padding:4pt 6pt;vertical-align:bottom;border-bottom:0.6pt solid #000;background:none;color:#000}
td{padding:3pt 6pt;vertical-align:top;border:none}
tr{break-inside:avoid}p:has(+ .tbl),p:has(+ table){break-after:avoid}thead{display:table-header-group}
p:has(+ table) strong:first-child{font-weight:700}
/* title page */
.titlepage{height:235mm;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;break-after:page}
.titlepage .tag{font-size:10.5pt;letter-spacing:.2em;text-transform:uppercase;color:#000}
.titlepage h1{font-size:24pt;margin:14pt 0 8pt;color:#000;line-height:1.2}
.titlepage .sub{font-size:13.5pt;font-style:italic;margin-bottom:30pt}
.titlepage .meta{font-size:11.5pt;padding-top:0}
.titlepage .meta p{margin:0 0 4pt;text-align:center}
.titlepage .draft{display:inline-block;margin-top:24pt;font-size:10.5pt;font-style:italic;letter-spacing:.05em}
/* contents */
.toc{break-after:page}
.toc h2{margin-top:0}
.toc ol{list-style:none;padding-left:0}
.toc li{display:flex;gap:8pt;padding:3pt 0;margin:0;font-size:11pt;text-align:left}
.toc li span{min-width:22pt}
/* key findings: plain, like an abstract */
.keybox{margin:0 0 12pt;padding:0}
.keybox h2{margin-top:0}
.take{font-weight:700}
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
<title>{title}: SF report</title><style>{CSS}</style></head><body>
{titlepage}{toc}{body}
</body></html>"""
open(OUT, "w", encoding="utf-8").write(html)
print("wrote", OUT, "| sections:", len(heads))
