"""
report_builder.py — parameterized PDF report generator for Orionbeam.

Renders two report types from structured data via headless Chromium (same
pipeline as report_audit.py / report_revenue.py):

  build_prospect_brief(data) -> HTML   cold revenue-opportunity brief (modeled)
  build_results_report(data) -> HTML   before/after performance report
  render_pdf(html, out_path)           HTML -> PDF

Design rules carried over from the engine:
  - Traffic is measured; revenue is DERIVED from the measured gain. Never the reverse.
  - Every figure is labeled with its source and whether it's measured or modeled.
  - Revenue attributes only to the organic-click delta — not the client's whole P&L.
  - Conservative by construction: excludes repeat, direct, app, other channels.

Feed real GSC / GA4 / GSC pulls into the dataclasses and render.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


# --------------------------------------------------------------------------- #
# Currency formatting
# --------------------------------------------------------------------------- #
@dataclass
class Money:
    symbol: str = "$"
    style: str = "western"  # "western" -> K/M grouping ; "inr" -> lakh/crore

    def _inr_group(self, n: float) -> str:
        n = int(round(n))
        sign, s = ("-" if n < 0 else ""), str(abs(n))
        if len(s) <= 3:
            return sign + s
        last3, rest, parts = s[-3:], s[:-3], []
        while len(rest) > 2:
            parts.insert(0, rest[-2:]); rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        return sign + ",".join(parts) + "," + last3

    def full(self, n: float) -> str:
        if self.style == "inr":
            return f"{self.symbol}{self._inr_group(n)}"
        return f"{self.symbol}{int(round(n)):,}"

    def compact(self, n: float) -> str:
        if self.style == "inr":
            if abs(n) >= 1e7:
                return f"{self.symbol}{n/1e7:.2f} Cr"
            if abs(n) >= 1e5:
                return f"{self.symbol}{n/1e5:.1f} L"
            return self.full(n)
        if abs(n) >= 1e6:
            return f"{self.symbol}{n/1e6:.1f}M"
        if abs(n) >= 1e3:
            return f"{self.symbol}{n/1e3:.1f}K"
        return self.full(n)


USD = Money("$", "western")
INR = Money("\u20b9", "inr")


def _pct_str(before: float, after: float) -> str:
    if before == 0:
        return "new"
    p = (after - before) / before * 100
    return f"+{p:.0f}%" if p >= 0 else f"{p:.0f}%"


def _n(x: float) -> str:
    return f"{int(round(x)):,}"


# --------------------------------------------------------------------------- #
# Shared chrome / CSS
# --------------------------------------------------------------------------- #
_CSS = """
@page { size: A4; margin: 15mm 15mm 16mm 15mm; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; color: #1c1c1a;
       font-size: 10.5pt; line-height: 1.5; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
h1 { font-size: 21pt; font-weight: 600; letter-spacing: -0.3px; }
h2 { font-size: 12.5pt; font-weight: 600; color: #0f6e56; margin: 20px 0 8px;
     padding-bottom: 5px; border-bottom: 1.5px solid #e1f0ea; }
h3 { font-size: 10pt; font-weight: 600; margin: 12px 0 6px; }
p { margin: 0 0 8px; } .muted { color: #6b6b66; } .small { font-size: 8.8pt; }
.pos { color: #0f6e56; font-weight: 600; }
.head { display: flex; justify-content: space-between; align-items: flex-start;
        border-bottom: 2.5px solid #0f6e56; padding-bottom: 12px; }
.brand { font-size: 13pt; font-weight: 700; letter-spacing: -0.2px; }
.brand span { color: #0f6e56; }
.brand-sub { font-size: 8pt; color: #6b6b66; letter-spacing: 1.5px; text-transform: uppercase; }
.meta { text-align: right; font-size: 8.5pt; color: #6b6b66; line-height: 1.7; }
.title-block { margin: 18px 0 10px; }
.title-block .for { font-size: 9pt; color: #6b6b66; text-transform: uppercase; letter-spacing: 1.2px; }
.period { font-size: 9pt; color: #6b6b66; margin-top: 4px; }
.kpis { display: flex; gap: 10px; margin: 14px 0 4px; }
.kpi { flex: 1; border: 1px solid #e6e6e1; border-radius: 8px; padding: 11px 12px; }
.kpi .lab { font-size: 8pt; text-transform: uppercase; letter-spacing: 0.7px; color: #6b6b66; }
.kpi .val { font-size: 17pt; font-weight: 600; margin-top: 3px; color: #0f6e56; }
.kpi .ba { font-size: 8.2pt; color: #6b6b66; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 9.6pt; }
th { background: #0f6e56; color: #fff; text-align: left; padding: 7px 10px; font-weight: 600; font-size: 9pt; }
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
td { padding: 7px 10px; border-bottom: 1px solid #ededea; }
tr.mid td { background: #f4faf7; font-weight: 600; }
.bar-wrap { display: flex; align-items: center; gap: 8px; }
.bar-track { flex: 1; height: 7px; background: #eef1ef; border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; background: #0f6e56; border-radius: 4px; }
.bar-fill.before { background: #c3d6cf; }
.callout { background: #f4faf7; border-left: 3px solid #0f6e56; padding: 11px 14px;
           border-radius: 0 5px 5px 0; margin: 12px 0; font-size: 9.6pt; }
.formula { font-family: "SF Mono", Menlo, monospace; font-size: 8.8pt;
           background: #f5f5f2; padding: 8px 10px; border-radius: 5px; color: #444; }
ul { margin: 4px 0 8px 16px; } li { margin-bottom: 4px; }
.tag { display: inline-block; font-size: 7.5pt; font-weight: 600; padding: 2px 8px;
       border-radius: 10px; letter-spacing: 0.3px; }
.tag.green { background: #e1f0ea; color: #0f6e56; }
.tag.amber { background: #fde9c8; color: #854f0b; }
.footer { margin-top: 22px; padding-top: 10px; border-top: 1px solid #e6e6e1;
          font-size: 7.8pt; color: #9a9a94; display: flex; justify-content: space-between; }
"""


def _doc(title: str, body: str) -> str:
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{title}</title><style>{_CSS}</style></head><body>{body}</body></html>")


def _header(report_label: str) -> str:
    today = date.today().strftime("%d %b %Y")
    return (
        '<div class="head"><div>'
        '<div class="brand"><span>Orionbeam.in</span></div>'
        '<div class="brand-sub">Search \u00b7 GEO \u00b7 AI Overviews</div></div>'
        f'<div class="meta">{report_label}<br>Issued {today}<br>Confidential</div></div>'
    )


# --------------------------------------------------------------------------- #
# Results report (before/after)
# --------------------------------------------------------------------------- #
@dataclass
class ResultsData:
    client_name: str
    domain: str
    window_before: str
    window_after: str
    engagement_label: str
    # (before, after) pairs from GSC / GA4
    impressions: tuple
    clicks: tuple
    avg_position: tuple          # lower is better
    sessions: tuple
    engagement: tuple            # display strings, e.g. ("1m 12s", "1m 41s")
    engagement_pct: str          # precomputed, e.g. "+40%"
    # ranking bands from GSC
    kw_top3: tuple
    kw_top10: tuple
    kw_total: tuple
    kw_aio: tuple
    # revenue model
    conv_rate: float             # client's actual, e.g. 0.025
    aov: float
    conv_source: str = "Client's actual (GA4)"
    traffic_source: str = "Search Console"   # or "Estimated (GSC)"
    traffic_estimated: bool = False
    money: Money = field(default_factory=lambda: USD)
    illustrative: bool = False

    def incremental_clicks(self) -> float:
        return self.clicks[1] - self.clicks[0]

    def added_monthly(self) -> float:
        return self.incremental_clicks() * self.conv_rate * self.aov

    def added_annual(self) -> float:
        return self.added_monthly() * 12


def build_results_report(d: ResultsData) -> str:
    m = d.money
    flag = ('<span class="tag amber">Illustrative figures</span>' if d.illustrative else "")
    cb, ca = d.clicks
    bar_before = max(2, cb / ca * 100) if ca else 2
    added_mo, added_yr = d.added_monthly(), d.added_annual()

    body = _header("Performance Report")
    body += (
        '<div class="title-block"><div class="for">Results for</div>'
        f'<h1>{d.client_name} <span class="muted" style="font-weight:400;font-size:13pt;">'
        f'\u2014 {d.domain}</span></h1>'
        f'<div class="period">Before: {d.window_before} &nbsp;\u00b7&nbsp; After: {d.window_after}'
        f' &nbsp;\u00b7&nbsp; {d.engagement_label} &nbsp; {flag}</div></div>'
    )
    # KPI cards
    body += (
        '<div class="kpis">'
        f'<div class="kpi"><div class="lab">Organic clicks</div><div class="val">{_pct_str(*d.clicks)}</div>'
        f'<div class="ba">{_n(cb)} \u2192 {_n(ca)} / mo</div></div>'
        f'<div class="kpi"><div class="lab">Search impressions</div><div class="val">{_pct_str(*d.impressions)}</div>'
        f'<div class="ba">{m and _n(d.impressions[0])} \u2192 {_n(d.impressions[1])} / mo</div></div>'
        f'<div class="kpi"><div class="lab">Top-3 keywords</div><div class="val">{d.kw_top3[0]} \u2192 {d.kw_top3[1]}</div>'
        f'<div class="ba">+{d.kw_top3[1]-d.kw_top3[0]} commercial terms</div></div>'
        f'<div class="kpi"><div class="lab">Organic revenue*</div><div class="val">+{m.compact(added_mo)}</div>'
        f'<div class="ba">/ mo, attributable</div></div></div>'
        f''
    )
    # Search performance
    body += '<h2>Search performance \u2014 before vs after</h2>'
    if d.traffic_estimated:
        body += ('<p class="small muted">Traffic figures are'
                 'directly estimated from Google Search Console\u2019s. Sessions are measured in GA4. '
                 f'Before = {d.window_before}; after = {d.window_after}.</p>')
    else:
        body += ('<p class="small muted">Measured directly in Google Search Console and GA4. '
                 f'Before = {d.window_before}; after = {d.window_after}.</p>')
    body += '<table><tr><th>Metric</th><th class="num">Before</th><th class="num">After</th><th class="num">Change</th></tr>'
    if d.impressions[1]:
        body += f'<tr><td>Impressions / mo</td><td class="num">{_n(d.impressions[0])}</td><td class="num">{_n(d.impressions[1])}</td><td class="num pos">{_pct_str(*d.impressions)}</td></tr>'
    if ca:
        body += f'<tr><td>Clicks / mo</td><td class="num">{_n(cb)}</td><td class="num">{_n(ca)}</td><td class="num pos">{_pct_str(*d.clicks)}</td></tr>'
    pos_gain = d.avg_position[0] - d.avg_position[1]
    if d.avg_position[1]:
        body += f'<tr><td>Avg. position</td><td class="num">{d.avg_position[0]:.1f}</td><td class="num">{d.avg_position[1]:.1f}</td><td class="num pos">+{pos_gain:.1f}</td></tr>'
    if d.sessions[1]:
        body += f'<tr><td>Organic sessions / mo</td><td class="num">{_n(d.sessions[0])}</td><td class="num">{_n(d.sessions[1])}</td><td class="num pos">{_pct_str(*d.sessions)}</td></tr>'
    if d.engagement[1] and d.engagement[1] != "0m 00s":
        body += f'<tr><td>Avg. engagement / session</td><td class="num">{d.engagement[0]}</td><td class="num">{d.engagement[1]}</td><td class="num pos">{d.engagement_pct}</td></tr>'
    body += '</table>'
    # bars
    body += ('<h3>Monthly organic clicks</h3><table style="font-size:9pt;">'
             f'<tr><td style="width:70px;">Before</td><td><div class="bar-wrap"><div class="bar-track">'
             f'<div class="bar-fill before" style="width:{bar_before:.1f}%;"></div></div>'
             f'<span style="width:60px;text-align:right;">{_n(cb)}</span></div></td></tr>'
             f'<tr><td>After</td><td><div class="bar-wrap"><div class="bar-track">'
             f'<div class="bar-fill" style="width:100%;"></div></div>'
             f'<span style="width:60px;text-align:right;">{_n(ca)}</span></div></td></tr></table>')
    # rankings
    body += '<h2>Keyword &amp; ranking movement</h2>'
    body += '<p class="small muted">Ranking positions tracked in GSC across the target commercial keyword set.</p>'
    body += '<table><tr><th>Ranking band</th><th class="num">Before</th><th class="num">After</th><th class="num">Net</th></tr>'
    for label, pair in (("Top 3 positions", d.kw_top3), ("Top 10 positions", d.kw_top10),
                        ("Total keywords ranking", d.kw_total), ("AI Overview / answer citations", d.kw_aio)):
        body += f'<tr><td>{label}</td><td class="num">{pair[0]}</td><td class="num">{pair[1]}</td><td class="num pos">+{pair[1]-pair[0]}</td></tr>'
    body += '</table>'
    # revenue
    incr = d.incremental_clicks()
    body += '<h2>Revenue impact <span class="tag amber" style="vertical-align:middle;">Modeled \u2014 attributable</span></h2>'
    body += ('<p>The traffic gains above are measured. Revenue is derived from them \u2014 we take only the '
             '<strong>additional</strong> organic clicks our work produced and apply the client\u2019s own '
             'conversion rate and average order value. This isolates revenue from the organic traffic we can '
             'prove we drove. It does not claim credit for paid, direct, email, or referral channels.</p>')
    body += (f'<p class="formula">incremental clicks ({_n(ca)} \u2212 {_n(cb)} = {_n(incr)}/mo) '
             f'&times; conv {d.conv_rate*100:.1f}% &times; AOV {m.full(d.aov)} = ~{m.full(added_mo)} / mo</p>')
    body += '<table><tr><th>Driver</th><th class="num">Value</th></tr>'
    body += f'<tr><td>Additional organic clicks / mo</td><td class="num">{_n(incr)}</td></tr>'
    body += f'<tr><td>Conversion rate</td><td class="num">{d.conv_rate*100:.1f}%</td></tr>'
    body += f'<tr><td>Average order value</td><td class="num">{m.full(d.aov)}</td></tr>'
    body += f'<tr><td>Added organic revenue / mo</td><td class="num pos">~{m.full(added_mo)}</td></tr>'
    body += f'<tr><td>Annualised run-rate</td><td class="num pos">~{m.full(added_yr)}</td></tr>'
    body += '</table>'
    if d.traffic_estimated:
        body += ('')
    else:
        body += ('<div class="callout"><strong>How to read this.</strong> The percentages are measured facts '
                 'from your own analytics. The revenue line is a conservative model that counts only new organic '
                 'clicks at your real conversion and order value \u2014 so it understates rather than overstates. '
                 'Change either input and the figure moves; we\u2019d rather show the math than a single headline number.</div>')
    method_traffic = ('<li>Traffic figures are third-party estimates (GSC); rankings measured (GSC), sessions measured (GA4).</li>'
                      if d.traffic_estimated else
                      '<li>Traffic and ranking metrics are measured (Search Console, GA4, GSC) \u2014 not estimated.</li>')
    body += ('<h2>Method &amp; attribution</h2><ul class="small">'
             f'<li>Before window: {d.window_before}. After window: {d.window_after}. Same comparison basis throughout.</li>'
             f'{method_traffic}'
             '<li>Revenue is modeled from the <em>incremental</em> organic click gain only, at the client\u2019s actual conversion rate and AOV.</li>'
             '<li>Seasonality and non-organic channels are deliberately excluded from the revenue attribution.</li></ul>')
    foot_note = ("Traffic estimated (GSC) \u00b7 revenue modeled on estimate"
                 if d.traffic_estimated else "Traffic measured \u00b7 revenue modeled from measured gain")
    body += ('<div class="footer"><span>Orionbeam.in \u00b7 Performance Report \u00b7 '
             f'{d.client_name}</span><span>{foot_note}</span></div>')
    return _doc(f"Performance Report - {d.client_name}", body)


# --------------------------------------------------------------------------- #
# Prospect brief (cold, modeled)
# --------------------------------------------------------------------------- #
@dataclass
class ProspectData:
    name: str
    domain: str
    descriptor: str
    aov: float
    take_rate: float                 # 0..1 ; 1.0 if full ticket
    organic_visitors: float          # measured estimate or illustrative
    money: Money = field(default_factory=lambda: USD)
    conv_bands: dict = field(default_factory=lambda: {"Conservative": 0.010,
                                                       "Base case": 0.020, "Upside": 0.035})
    observed: list = field(default_factory=list)   # list of (label, value, note)
    illustrative_traffic: bool = True

    def scenarios(self) -> list:
        rows = []
        for label, conv in self.conv_bands.items():
            bookings = self.organic_visitors * conv
            net_mo = bookings * self.aov * self.take_rate
            rows.append((label, conv, bookings, net_mo, net_mo * 12))
        return rows


def build_prospect_brief(d: ProspectData) -> str:
    m = d.money
    body = _header("Revenue Opportunity Brief")
    body += (
        '<div class="title-block"><div class="for">Prepared for</div>'
        f'<h1>{d.name} <span class="muted" style="font-weight:400;font-size:13pt;">\u2014 {d.domain}</span></h1>'
        f'<p class="muted small" style="margin-top:4px;">{d.descriptor}</p></div>'
    )
    body += ('<div class="callout"><strong>What this is \u2014 and isn\u2019t.</strong> Every figure below is a '
             '<em>modeled estimate</em> built from publicly observable signals, not from the company\u2019s accounts. '
             'It deliberately excludes repeat business, app and direct traffic, and other service lines \u2014 so real '
             'numbers are almost certainly higher. The point is to size the search opportunity, not to state revenue. '
             '<span class="tag green">Conservative by design</span></div>')
    if d.observed:
        body += '<h2>What we observed</h2><div class="kpis">'
        for label, value, note in d.observed[:3]:
            body += (f'<div class="kpi"><div class="lab">{label}</div>'
                     f'<div class="val" style="font-size:14pt;">{value}</div>'
                     f'<div class="ba">{note}</div></div>')
        body += '</div>'
    flag = ('<span class="muted small"> *</span>' if d.illustrative_traffic else "")
    body += '<h2>Traffic basis</h2>'
    body += ('<p>The model needs one input it can\u2019t read from the page: monthly visitors. We split it into '
             'what\u2019s measurable and what isn\u2019t, rather than assuming a single number.</p>')
    body += '<table><tr><th>Source</th><th class="num">Monthly estimate</th><th>Confidence</th></tr>'
    body += f'<tr><td>Organic search (GSC ETV)</td><td class="num">{_n(d.organic_visitors)}{flag}</td><td>Modeled estimate \u2014 usable</td></tr>'
    body += '<tr><td>Paid search</td><td class="num">floor only</td><td>Underreports true ad spend</td></tr>'
    body += '<tr><td>Direct \u00b7 app \u00b7 repeat</td><td class="num">not captured</td><td>Invisible externally \u2014 adds upside</td></tr></table>'
    if d.illustrative_traffic:
        body += ('<p class="small muted">* Illustrative figure for this example. In a live brief this is the organic '
                 'ETV pulled for the domain at the target location \u2014 replace before sending.</p>')
    body += '<h2>Revenue scenarios</h2>'
    body += ('<p>Net revenue across a labeled range of visitor-to-booking conversion rates \u2014 benchmark bands '
             'for B2C local services on cold web traffic, not site-specific claims.</p>')
    body += '<table><tr><th>Scenario</th><th class="num">Conversion</th><th class="num">Bookings / mo</th><th class="num">Net / mo</th><th class="num">Net / yr</th></tr>'
    rows = d.scenarios()
    mid_label = list(d.conv_bands.keys())[len(d.conv_bands)//2]
    for label, conv, bookings, net_mo, net_yr in rows:
        cls = ' class="mid"' if label == mid_label else ""
        body += (f'<tr{cls}><td>{label}</td><td class="num">{conv*100:.1f}%</td>'
                 f'<td class="num">{_n(bookings)}</td><td class="num">{m.full(net_mo)}</td>'
                 f'<td class="num">{m.compact(net_yr)}</td></tr>')
    body += '</table>'
    body += (f'<p class="formula">net = visitors &times; conversion &times; booking value ({m.full(d.aov)}) '
             f'&times; take rate ({d.take_rate*100:.0f}%) &times; 12</p>')
    body += ('<p class="small muted">Modeled on organic visitors only. Adding the paid floor, repeat business, '
             'and other lines moves the real figure upward \u2014 these are floors, not ceilings.</p>')
    body += ('<h2>Method &amp; assumptions</h2><ul class="small">'
             '<li>Traffic: GSC Labs Domain Rank Overview (organic ETV); paid treated as a floor.</li>'
             '<li>Conversion bands are published B2C benchmarks for cold traffic, labeled as such.</li>'
             f'<li>Booking value {m.full(d.aov)} and take rate {d.take_rate*100:.0f}% are assumptions, shown so you can challenge them.</li>'
             '<li>Single service line, single channel. Excludes repeat, direct, app, and other lines.</li></ul>')
    body += ('<div class="footer"><span>Orionbeam.in \u00b7 Revenue Opportunity Brief \u00b7 '
             f'{d.name}</span><span>Modeled estimate \u2014 not a statement of actual revenue</span></div>')
    return _doc(f"Revenue Brief - {d.name}", body)


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render_pdf(html: str, out_path: str) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(html, wait_until="networkidle")
        pg.pdf(path=out_path, format="A4", print_background=True,
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        b.close()
    return out_path


if __name__ == "__main__":
    # Demo 1: before/after results report (Western B2B client, USD)
    results = ResultsData(
        client_name="Sample Client", domain="example.com",
        window_before="Dec 2025", window_after="May 2026",
        engagement_label="6-month engagement",
        impressions=(142000, 389000), clicks=(3100, 9840),
        avg_position=(28.4, 11.2), sessions=(2850, 9200),
        engagement=("1m 12s", "1m 41s"), engagement_pct="+40%",
        kw_top3=(4, 23), kw_top10=(18, 76), kw_total=(214, 612), kw_aio=(0, 11),
        conv_rate=0.025, aov=180, money=USD, illustrative=True,
    )
    render_pdf(build_results_report(results), "results_report.pdf")
    print("wrote results_report.pdf")

    # Demo 2: cold prospect brief (Indian B2C marketplace, INR)
    prospect = ProspectData(
        name="PawSpace", domain="pawspace.in",
        descriptor="At-home pet grooming &amp; care marketplace \u00b7 Bangalore, Hyderabad",
        aov=1500, take_rate=0.25, organic_visitors=18000, money=INR,
        observed=[("Acquisition", "Paid + organic", "Broad-match Google Ads alongside 30+ landing pages."),
                  ("Booking value", "\u20b9800\u20132,500", "Grooming from \u20b9799; full packages higher."),
                  ("Model", "Marketplace", "Take-rate across lines; recurring every 2\u20134 weeks.")],
        illustrative_traffic=True,
    )
    render_pdf(build_prospect_brief(prospect), "prospect_brief.pdf")
    print("wrote prospect_brief.pdf")