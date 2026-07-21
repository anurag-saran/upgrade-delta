#!/usr/bin/env bash
# lightwell-app-report.sh — ONE report per application.
#
# Chains the whole pipeline for a real app against the Lightwell catalog:
#   1. coverage  : bucket every dependency (COVERED / NEAR / UNCOVERED)
#   2. analyze   : for each COVERED dependency, fetch community + remediated jars
#                  and produce the per-library delta report (skipped if cached)
#   3. scan      : score the whole app against that evidence (+ optional app jar)
#   4. compose   : write out/reports/app-report.html — the single entry page:
#                  headline grade + coverage % up top, drill-down links below
#
# Usage:
#   export RHLN_USER='orgID|service-account' RHLN_TOKEN='...'
#   ./lightwell-app-report.sh <app-sbom.json> [app.jar]
#
# Offline mode (no credentials): skips fetching; composes from whatever evidence
# already exists in out/evidence/ — useful for demos and re-renders.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"
SBOM="${1:?usage: lightwell-app-report.sh <app-sbom.json> [app.jar]}"
APP="${2:-}"
CATALOG="${CATALOG:-catalogs/lightwell-remediated-java-sbom.json}"
RHLN_REPO="${RHLN_REPO:-https://packages.redhat.com/lightwell/java/remediated}"
CENTRAL="https://repo1.maven.org/maven2"
mkdir -p out/evidence out/reports lightwell-jars

# ---- 1) coverage -------------------------------------------------------------
python3 upgrade_delta.py coverage --sbom "$SBOM" --catalog "$CATALOG" \
  --json out/coverage.json --html out/reports/coverage.html

# ---- 2) per-covered-library delta reports -----------------------------------
python3 - "$SBOM" <<'EOF' > /tmp/covered.tsv
import json, sys
cov = json.load(open("out/coverage.json"))
for e in cov["exact"]:
    print(f'{e["group"]}\t{e["artifact"]}\t{e["version"]}\t{e["remediated"]}')
EOF
while IFS=$'\t' read -r GROUP ARTIFACT CURRENT REMEDIATED; do
  [[ -n "$ARTIFACT" ]] || continue
  EV="out/evidence/${ARTIFACT}-${CURRENT}-to-${REMEDIATED}.json"
  if [[ -f "$EV" ]]; then
    echo "cached:  $ARTIFACT $CURRENT -> $REMEDIATED"
    continue
  fi
  if [[ -z "${RHLN_TOKEN:-}" ]]; then
    echo "offline: skipping fetch for $ARTIFACT (set RHLN_USER/RHLN_TOKEN to analyze it)"
    continue
  fi
  GPATH=$(printf %s "$GROUP" | tr . /)
  OLD="lightwell-jars/${ARTIFACT}-${CURRENT}.jar"
  NEW="lightwell-jars/${ARTIFACT}-${REMEDIATED}.jar"
  [[ -f "$OLD" ]] || curl -fSL "${CENTRAL}/${GPATH}/${ARTIFACT}/${CURRENT}/${ARTIFACT}-${CURRENT}.jar" -o "$OLD" \
    || { echo "  ! central fetch failed for $ARTIFACT $CURRENT — skipping"; continue; }
  [[ -f "$NEW" ]] || curl -fSL -u "${RHLN_USER}:${RHLN_TOKEN}" \
    "${RHLN_REPO}/${GPATH}/${ARTIFACT}/${REMEDIATED}/${ARTIFACT}-${REMEDIATED}.jar" -o "$NEW" \
    || { echo "  ! lightwell fetch failed for $ARTIFACT $REMEDIATED — skipping"; continue; }
  python3 upgrade_delta.py analyze "$OLD" "$NEW" \
    --old-version "$CURRENT" --new-version "$REMEDIATED" --library "$ARTIFACT" \
    --json "$EV" --html "out/reports/${ARTIFACT}-${CURRENT}-to-${REMEDIATED}.html" || true
done < /tmp/covered.tsv

# ---- 3) publish the library certificates + scan the app ---------------------
EVIDENCE=(out/evidence/*.json)
if [[ -e "${EVIDENCE[0]}" ]]; then
  python3 upgrade_delta.py publish "${EVIDENCE[@]}" --out out/reports
  SCAN_ARGS=(--evidence out/evidence --sbom "$SBOM"
             --json out/scorecard.json --html out/reports/scorecard.html)
  if [[ -n "$APP" && -f "$APP" ]]; then
    python3 upgrade_delta.py scan "$APP" "${SCAN_ARGS[@]}" || true
  else
    echo "note: no app jar given — scorecard needs one; composing without it"
  fi
fi

# ---- 4) compose the single app-level report ---------------------------------
python3 - <<'PYEOF_INNER'
import json, os, html
from datetime import date

cov = json.load(open("out/coverage.json"))
t = cov["totals"]
total = t["dependencies"] or 1
pct = round(100 * t["exact"] / total)
near_pct = round(100 * t["serviced_other_version"] / total)
unc_pct = round(100 * t["uncovered"] / total)

score = json.load(open("out/scorecard.json")) if os.path.exists("out/scorecard.json") else None

GC = {"A": "#1E6E52", "B": "#B07414", "C": "#B07414", "D": "#A03A2A", "F": "#A03A2A"}

def gav(e):
    g = html.escape(e["group"] or "")
    return f'{g}:{html.escape(e["artifact"])}' if g else html.escape(e["artifact"])

# covered rows carry the per-library GRADE badge + link to the certificate
cov_rows = ""
for e in cov["exact"]:
    slug = f'{e["artifact"]}-{e["version"]}-to-{e["remediated"]}'
    link = f"{slug}.html" if os.path.exists(f"out/reports/{slug}.html") else None
    ev = f"out/evidence/{slug}.json"
    grade = json.load(open(ev))["rating"]["grade"] if os.path.exists(ev) else None
    badge = (f'<span class="g" style="--c:{GC.get(grade,"#888")}">{grade}</span>'
             if grade else '<span class="g na">—</span>')
    dep = f'<a href="{link}">{gav(e)}</a>' if link else gav(e)
    cov_rows += (f'<tr><td class="dep">{dep}</td>'
                 f'<td class="ver">{html.escape(e["version"])}</td>'
                 f'<td class="ver arrow">{html.escape(e["remediated"])}</td>'
                 f'<td class="badge">{badge}</td>'
                 f'<td class="act">Swap the suffix. No code change.</td></tr>')

near_rows = "".join(
    f'<tr><td class="dep">{gav(e)}</td><td class="ver">{html.escape(e["version"])}</td>'
    f'<td class="ver">{html.escape(", ".join(e["serviced_versions"]))}</td>'
    f'<td class="act">Upgrade to a serviced version, or request yours.</td></tr>'
    for e in cov["serviced_other_version"])
unc_rows = "".join(
    f'<tr><td class="dep">{gav(e)}</td><td class="ver">{html.escape(e["version"])}</td>'
    f'<td class="ver dash">not serviced</td>'
    f'<td class="act">No remediated build — full regression on any upgrade.</td></tr>'
    for e in cov["uncovered"])

def section(color, title, subtitle, count, head_cols, rows):
    if not rows:
        return ""
    heads = "".join(f"<th>{h}</th>" for h in head_cols)
    return f'''<section class="grp">
  <div class="grp-h" style="--gc:{color}">
    <span class="pill">{count}</span>
    <div><div class="grp-t">{title}</div><div class="grp-s">{subtitle}</div></div>
  </div>
  <table class="grid"><thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table>
</section>'''

body = (
    section("#1E6E52", "Covered — drop-in remediated build",
            "Red Hat rebuilt the exact version you run. Each links to its rated delta report.",
            t["exact"],
            ["Dependency", "You run", "Remediated build", "Grade", "What it means"], cov_rows) +
    section("#B07414", "Serviced — at a different version",
            "Serviced, but not the version you run — upgrade, or request your version.",
            t["serviced_other_version"],
            ["Dependency", "You run", "Serviced versions", "What it means"], near_rows) +
    section("#A03A2A", "Not covered",
            "No remediated build — the unscoped-regression case this tool exists to remove.",
            t["uncovered"],
            ["Dependency", "You run", "Status", "What it means"], unc_rows))

grade_line = ""
if score:
    p = score["project"]
    gc = GC.get(p["headline_grade"], "#888")
    grade_line = (f'<div class="proj"><span class="g big" style="--c:{gc}">'
                  f'{p["headline_grade"]}</span>'
                  f'<div><div class="proj-t">Project test grade</div>'
                  f'<div class="proj-s">{html.escape(p.get("headline_note",""))} — '
                  f'<a href="scorecard.html">full scorecard</a></div></div></div>')

app = html.escape(cov["app"])
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{app} — Lightwell app report</title>
<style>
:root{{--ink:#17272E;--soft:#44565E;--line:#e6e6e6}}
*{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  max-width:920px;margin:0 auto;padding:44px 22px;color:var(--ink);line-height:1.5}}
.k{{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--soft)}}
h1{{font-size:27px;margin:5px 0 3px}}
.sub{{color:var(--soft);font-size:13.5px;margin:0 0 22px}}
.hero{{display:flex;gap:34px;align-items:center;flex-wrap:wrap;
  background:#fafafa;border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin:0 0 12px}}
.hero .big{{font:700 42px/1 sans-serif}}
.hero .lbl{{font-size:12px;color:var(--soft)}}
.legend2{{display:flex;gap:22px;flex-wrap:wrap;margin-left:auto}}
.legend2 .li{{display:flex;align-items:baseline;gap:8px}}
.legend2 .n{{font:700 20px/1 sans-serif}} .legend2 .t{{font-size:11.5px;color:var(--soft)}}
.dot{{width:9px;height:9px;border-radius:50%;align-self:center}}
.proj{{display:flex;gap:14px;align-items:center;margin:0 0 26px;padding:14px 18px;
  border:1px solid var(--line);border-radius:10px}}
.proj-t{{font-weight:700;font-size:14px}} .proj-s{{font-size:12.5px;color:var(--soft)}}
.g{{display:inline-flex;align-items:center;justify-content:center;min-width:26px;height:26px;
  border-radius:6px;border:2px solid var(--c);color:var(--c);font:700 15px/1 sans-serif;padding:0 6px}}
.g.big{{min-width:44px;height:44px;font-size:24px;border-width:2.5px}}
.g.na{{border-color:#ccc;color:#aaa}}
.grp{{margin:0 0 26px}}
.grp-h{{display:flex;align-items:center;gap:13px;padding-bottom:9px;border-bottom:2px solid var(--gc)}}
.grp .pill{{background:var(--gc);color:#fff;font:700 14px/1 sans-serif;min-width:30px;height:30px;
  border-radius:15px;display:flex;align-items:center;justify-content:center;padding:0 8px}}
.grp-t{{font-weight:700;font-size:15px}} .grp-s{{font-size:12px;color:var(--soft);margin-top:3px}}
table.grid{{width:100%;border-collapse:collapse}}
table.grid th{{text-align:left;font:600 10.5px/1 sans-serif;letter-spacing:.05em;text-transform:uppercase;
  color:var(--soft);padding:11px 12px 7px;border-bottom:1px solid var(--line)}}
table.grid td{{padding:10px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;vertical-align:middle}}
table.grid tr:last-child td{{border-bottom:none}}
td.dep{{font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:nowrap}}
td.dep a{{color:var(--ink);text-decoration:none;border-bottom:1px solid #ccc}}
td.ver{{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:var(--soft);white-space:nowrap}}
td.ver.arrow{{color:#1E6E52;font-weight:600}}
td.ver.arrow::before{{content:"\2192 ";color:var(--soft);font-weight:400}}
td.ver.dash{{color:#A03A2A}} td.act{{font-size:12.5px}}
.foot{{color:var(--soft);font-size:11.5px;border-top:1px solid var(--line);padding-top:16px;margin-top:30px}}
</style></head><body>
<div class="k">Lightwell app report · {date.today()}</div>
<h1>{app}</h1>
<p class="sub">What Red Hat Lightwell can remediate for this application — today, for the
exact versions in production — and the test scope each fix owes.</p>

<div class="hero">
  <div><div class="big">{pct}%</div><div class="lbl">drop-in ready</div></div>
  <div class="legend2">
    <div class="li"><span class="dot" style="background:#1E6E52"></span>
      <span class="n" style="color:#1E6E52">{t["exact"]}</span>
      <span class="t">covered<br>({pct}%)</span></div>
    <div class="li"><span class="dot" style="background:#B07414"></span>
      <span class="n" style="color:#B07414">{t["serviced_other_version"]}</span>
      <span class="t">serviced elsewhere<br>({near_pct}%)</span></div>
    <div class="li"><span class="dot" style="background:#A03A2A"></span>
      <span class="n" style="color:#A03A2A">{t["uncovered"]}</span>
      <span class="t">not covered<br>({unc_pct}%)</span></div>
  </div>
</div>
{grade_line}
{body}
<div class="foot">One page per application · one certificate per library (linked from the
Covered rows). Library reports are publisher-side and identical for every consumer; this page
is the consumer-side composition. See also the <a href="index.html">rated library catalog</a>
and the <a href="coverage.html">coverage card</a>.</div>
</body></html>"""
open("out/reports/app-report.html", "w").write(page)
print("APP REPORT: out/reports/app-report.html")
PYEOF_INNER
echo "Open out/reports/app-report.html — that is the one report per app."
