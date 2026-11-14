"""Build the standalone HTML copy of SF report v2 from its Markdown source, in the project website's style.
Run: python -I -B build_html.py   (needs the `markdown` package)"""
import os
import re
import sys

import markdown

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "SF_REPORT_v3_2026-11-15.md")
OUT = os.path.join(HERE, "SF_REPORT_v3_2026-11-15.html")

CSS = """
:root{--bg:#fff;--soft:#f5f8f7;--line:#e6ecea;--ink:#1d1d1f;--ink2:#5f5f66;--ink3:#8a8a91;--E:#12a36a;--Esoft:#e6f5ef;--Eink:#1d6e52;--harm:#f04e30;
--font:"Manrope","Segoe UI",system-ui,-apple-system,sans-serif;--mono:"JetBrains Mono",ui-monospace,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);font-size:17px;line-height:1.65;-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
main{max-width:860px;margin:0 auto;padding:56px 24px 96px}
h1{font-size:clamp(32px,5vw,46px);font-weight:800;letter-spacing:-.03em;line-height:1.1;margin:0 0 10px}
h2{font-size:26px;font-weight:800;letter-spacing:-.02em;line-height:1.2;margin:56px 0 14px}
h1+h2{font-size:21px;font-weight:600;color:var(--ink2);margin:0 0 18px;letter-spacing:-.01em}
h3{font-size:19px;font-weight:800;margin:34px 0 10px}
p,li{color:var(--ink)}
strong{font-weight:800}
a{color:#235a9c}
hr{border:0;border-top:1px solid var(--line);margin:36px 0}
pre{background:#f3f6f5;border:1px solid #dfe7e3;border-radius:8px;padding:10px 14px;white-space:pre-wrap;font-size:0.92em;line-height:1.5;break-inside:avoid}pre code{background:none;padding:0}
code{font-family:var(--mono);font-size:.85em;background:var(--soft);padding:2px 6px;border-radius:6px}
blockquote{margin:18px 0;padding:16px 22px;background:var(--Esoft);border-radius:18px;color:var(--Eink);font-weight:600}
blockquote p{color:var(--Eink);margin:0}
table{width:100%;border-collapse:collapse;margin:16px 0 8px;font-size:14.5px}
th{text-align:left;font-weight:800;color:var(--ink2);border-bottom:2px solid var(--line);padding:9px 10px;vertical-align:bottom}
td{border-bottom:1px solid var(--line);padding:8px 10px;vertical-align:top}
tr:nth-child(even) td{background:#fafcfb}
.tbl{overflow-x:auto}
.cover{background:var(--soft);border-radius:28px;padding:34px 34px 26px;margin-bottom:34px}
.cover p{color:var(--ink2);margin:6px 0}
.kick{display:inline-block;font-size:12.5px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--E);margin-bottom:12px}
.keybox{background:#fff;border:1px solid var(--line);border-radius:24px;padding:8px 28px 18px;box-shadow:0 20px 50px -38px rgba(0,0,0,.45)}
.take{background:var(--Esoft);color:var(--Eink);border-radius:999px;padding:12px 22px;font-weight:800;display:inline-block;margin-top:6px}
@page{size:A4;margin:16mm 15mm 18mm}
@media print{html{-webkit-print-color-adjust:exact;print-color-adjust:exact}body{font-size:12.5px}main{padding:0;max-width:none}
h1{font-size:32px}h2{font-size:20px;margin-top:30px;break-after:avoid}h3{font-size:15px;break-after:avoid}
table{font-size:11px}tr{break-inside:avoid}p:has(+ .tbl),p:has(+ table){break-after:avoid}thead{display:table-header-group}.keybox{box-shadow:none;break-inside:avoid}.cover{padding:24px 26px 18px}}
"""

md = open(SRC, encoding="utf-8").read()
body = markdown.markdown(md, extensions=["tables", "sane_lists", "fenced_code"])
body = re.sub(r"<table>", '<div class="tbl"><table>', body).replace("</table>", "</table></div>")
# cover block: title, subtitle and the two byline paragraphs
cov_end = body.index("<hr")
body = '<div class="cover">' + body[:cov_end] + "</div>" + body[cov_end:]
# key findings card and take-away pill
k0 = body.index('<h2>Key findings</h2>')
k1 = body.index("<hr", k0)
key = body[k0:k1].replace("<p><strong>Take-home message:", '<p class="take"><strong>Take-home message:')
body = body[:k0] + '<section class="keybox">' + key + "</section>" + body[k1:]
html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your AI Meal Planner Would Order You a Live Lobster: SF report (draft)</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&family=JetBrains+Mono:wght@500&display=swap">
<style>{CSS}</style></head><body><main>
{body}
</main></body></html>"""
open(OUT, "w", encoding="utf-8").write(html)
print("wrote", OUT, len(html), "bytes")
