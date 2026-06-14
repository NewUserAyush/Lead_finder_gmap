#!/usr/bin/env python3
"""
Lead Finder — a tiny local web app.

Type a locality + a business category, hit Search, and get back:
  - LEADS: businesses with NO website (your prospects), with phone numbers
  - COMPETITORS: same category + area businesses that DO have a website (pitch ammo)

The Google Places API (New) is called server-side, so your API key never touches
the browser and there are no CORS issues.

SETUP:
  export GOOGLE_MAPS_API_KEY="your_key"
  pip install flask requests openpyxl
  python app.py
  # open http://127.0.0.1:5000

COST NOTE: phone numbers (Enterprise SKU, 1,000 free/mo) are fetched only for leads,
never for competitors. The website check rides on the cheaper Pro SKU search call.
"""

import os
import io
import json
import time
import hashlib
import tempfile
import requests
import secrets
from datetime import datetime, timedelta
from flask import (Flask, request, jsonify, render_template_string, send_file,
                  redirect, make_response)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAIL_URL = "https://places.googleapis.com/v1/places/{pid}"
SEARCH_MASK = ("places.id,places.displayName,places.formattedAddress,"
               "places.websiteUri,places.primaryTypeDisplayName,"
               "places.googleMapsUri,places.rating,places.userRatingCount,"
               "nextPageToken")
DETAIL_MASK = "nationalPhoneNumber,internationalPhoneNumber"
MAX_COMPETITORS = 5
PAGES = 2

app = Flask(__name__)

# --------------------------- Access gate ----------------------------------
# Set ACCESS_TOKEN to a long random string to lock the whole app (page + APIs).
# Generate one with:  python -c "import secrets; print(secrets.token_urlsafe(32))"
# Share the link as:  https://your-host/?key=THAT_TOKEN
# If ACCESS_TOKEN is unset, the gate is OFF (handy for local dev).
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")


@app.before_request
def access_gate():
    if not ACCESS_TOKEN:
        return  # gate disabled
    cookie = request.cookies.get("access", "")
    if secrets.compare_digest(cookie, ACCESS_TOKEN):
        return  # already let in
    key = request.args.get("key", "")
    if secrets.compare_digest(key, ACCESS_TOKEN):
        # valid link: drop a cookie, then redirect to a clean URL so the
        # token stops showing in the address bar / forward history
        resp = make_response(redirect(request.path))
        resp.set_cookie("access", ACCESS_TOKEN, max_age=60 * 60 * 24 * 30,
                        httponly=True, samesite="Lax", secure=request.is_secure)
        return resp
    return ("Not found", 404)  # don't advertise that anything is here


# --------------------------- Places API helpers ---------------------------
def text_search(category, place):
    out, token = [], None
    for _ in range(PAGES):
        body = {"textQuery": f"{category} in {place}", "regionCode": "IN", "pageSize": 20}
        if token:
            body["pageToken"] = token
        r = requests.post(SEARCH_URL, json=body, timeout=30, headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": API_KEY,
            "X-Goog-FieldMask": SEARCH_MASK,
        })
        if r.status_code != 200:
            raise RuntimeError(f"Places search failed ({r.status_code}): {r.text[:300]}")
        data = r.json()
        out.extend(data.get("places", []))
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(0.6)
    return out


def get_phone(pid):
    r = requests.get(DETAIL_URL.format(pid=pid), timeout=30, headers={
        "X-Goog-Api-Key": API_KEY, "X-Goog-FieldMask": DETAIL_MASK})
    if r.status_code != 200:
        return ""
    d = r.json()
    return d.get("nationalPhoneNumber") or d.get("internationalPhoneNumber") or ""


def name_of(p):
    return (p.get("displayName") or {}).get("text", "").strip()


def run_search(category, place, search_type="no_website"):
    places = text_search(category, place)

    if search_type == "low_visibility":
        with_sites = [p for p in places if p.get("websiteUri") and name_of(p)]
        if not with_sites:
            return {"leads": [], "competitors": [], "total": len(places),
                    "category": category, "place": place, "search_type": search_type,
                    "avg_reviews": 0}

        for p in with_sites:
            p["_reviews"] = p.get("userRatingCount") or 0

        avg_reviews = sum(p["_reviews"] for p in with_sites) / len(with_sites)
        with_sites.sort(key=lambda p: p["_reviews"])

        leads_raw = [p for p in with_sites if p["_reviews"] < avg_reviews]
        comps_raw = [p for p in with_sites if p["_reviews"] >= avg_reviews]

        leads = []
        for l in leads_raw:
            phone = get_phone(l["id"])
            leads.append({
                "name": name_of(l),
                "category": category,
                "area": place,
                "mobile": phone,
                "website": l.get("websiteUri", ""),
                "maps": l.get("googleMapsUri", ""),
                "rating": l.get("rating") or 0,
                "reviews": l["_reviews"],
                "address": l.get("formattedAddress", ""),
            })
            time.sleep(0.4)

        competitors = [{
            "name": name_of(c),
            "website": c.get("websiteUri", ""),
            "maps": c.get("googleMapsUri", ""),
            "rating": c.get("rating") or 0,
            "reviews": c["_reviews"],
        } for c in sorted(comps_raw, key=lambda p: p["_reviews"], reverse=True)[:MAX_COMPETITORS]]

        return {"leads": leads, "competitors": competitors,
                "total": len(places), "category": category, "place": place,
                "search_type": search_type, "avg_reviews": int(avg_reviews)}

    # --- default: no website ---
    leads_raw = [p for p in places if not p.get("websiteUri")]
    comps_raw = [p for p in places if p.get("websiteUri")]

    competitors = [{
        "name": name_of(c),
        "website": c.get("websiteUri", ""),
        "maps": c.get("googleMapsUri", ""),
    } for c in comps_raw[:MAX_COMPETITORS] if name_of(c)]

    leads = []
    for lead in leads_raw:
        if not name_of(lead):
            continue
        phone = get_phone(lead["id"])
        if not phone:
            continue
        leads.append({
            "name": name_of(lead),
            "category": category,
            "area": place,
            "mobile": phone,
            "address": lead.get("formattedAddress", ""),
            "maps": lead.get("googleMapsUri", ""),
        })
        time.sleep(0.4)

    return {"leads": leads, "competitors": competitors,
            "total": len(places), "category": category, "place": place,
            "search_type": "no_website"}


# ------------------------------- Routes ------------------------------------
@app.route("/")
def home():
    return render_template_string(PAGE)


@app.route("/api/search", methods=["POST"])
def api_search():
    if not API_KEY:
        return jsonify({"error": "GOOGLE_MAPS_API_KEY is not set on the server."}), 400
    body = request.get_json(force=True)
    place = (body.get("place") or "").strip()
    category = (body.get("category") or "").strip()
    search_type = (body.get("search_type") or "no_website").strip()
    if not place or not category:
        return jsonify({"error": "Enter both a place and a category."}), 400
    try:
        return jsonify(run_search(category, place, search_type))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/export", methods=["POST"])
def api_export():
    """Build an Excel from results already on screen (no extra API spend)."""
    data = request.get_json(force=True)
    leads = data.get("leads", [])
    competitors = data.get("competitors", [])

    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    headers = ["Lead (no website)", "Category", "Area", "Mobile", "Address", "Maps Link"]
    for i in range(1, MAX_COMPETITORS + 1):
        headers += [f"Competitor {i}", f"Competitor {i} Website"]
    ws.append(headers)
    fill = PatternFill("solid", fgColor="15171C")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = fill
        c.alignment = Alignment(vertical="center")

    for lead in leads:
        row = [lead["name"], lead["category"], lead["area"],
               lead["mobile"], lead["address"], lead["maps"]]
        for comp in competitors[:MAX_COMPETITORS]:
            row += [comp["name"], comp["website"]]
        while len(row) < len(headers):
            row.append("")
        ws.append(row)

    widths = [32, 18, 22, 16, 40, 28] + [24, 32] * MAX_COMPETITORS
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"leads_{data.get('place','area')}_{data.get('category','cat')}.xlsx".replace(" ", "_")
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


CACHE_DIR = os.path.join(os.path.dirname(__file__), "report_cache")
CACHE_TTL = timedelta(days=30)


def _cache_key(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _cache_get(key: str):
    meta_path = os.path.join(CACHE_DIR, f"{key}.json")
    pdf_path  = os.path.join(CACHE_DIR, f"{key}.pdf")
    if not os.path.exists(meta_path) or not os.path.exists(pdf_path):
        return None, None
    with open(meta_path) as f:
        meta = json.load(f)
    created = datetime.fromisoformat(meta["created_at"])
    if datetime.utcnow() - created > CACHE_TTL:
        try:
            os.unlink(meta_path)
            os.unlink(pdf_path)
        except Exception:
            pass
        return None, None
    return pdf_path, meta["filename"]


def _cache_put(key: str, pdf_bytes: bytes, filename: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    pdf_path  = os.path.join(CACHE_DIR, f"{key}.pdf")
    meta_path = os.path.join(CACHE_DIR, f"{key}.json")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    with open(meta_path, "w") as f:
        json.dump({"created_at": datetime.utcnow().isoformat(), "filename": filename}, f)


@app.route("/api/generate-report", methods=["POST"])
def api_generate_report():
    data = request.get_json(force=True)
    mode = data.get("mode", "auto")

    cache_key = _cache_key(data)
    cached_path, cached_fname = _cache_get(cache_key)
    if cached_path:
        with open(cached_path, "rb") as f:
            buf = io.BytesIO(f.read())
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=cached_fname,
                         mimetype="application/pdf")

    try:
        if mode == "auto":
            from data_sources import fetch_results_data
            rd = fetch_results_data(data)
        else:
            from report_builder import ResultsData, USD, INR
            money = INR if data.get("currency") == "inr" else USD
            rd = ResultsData(
                client_name=data["client_name"],
                domain=data["domain"],
                window_before=data["window_before"],
                window_after=data["window_after"],
                engagement_label=data.get("engagement_label", ""),
                impressions=(float(data["impressions_before"]), float(data["impressions_after"])),
                clicks=(float(data["clicks_before"]), float(data["clicks_after"])),
                avg_position=(float(data["avg_position_before"]), float(data["avg_position_after"])),
                sessions=(float(data["sessions_before"]), float(data["sessions_after"])),
                engagement=(data["engagement_before"], data["engagement_after"]),
                engagement_pct=data["engagement_pct"],
                kw_top3=(int(data["kw_top3_before"]), int(data["kw_top3_after"])),
                kw_top10=(int(data["kw_top10_before"]), int(data["kw_top10_after"])),
                kw_total=(int(data["kw_total_before"]), int(data["kw_total_after"])),
                kw_aio=(int(data.get("kw_aio_before", 0)), int(data.get("kw_aio_after", 0))),
                conv_rate=float(data["conv_rate"]),
                aov=float(data["aov"]),
                conv_source=data.get("conv_source", "Client's actual (GA4)"),
                money=money,
                illustrative=bool(data.get("illustrative", False)),
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    tmp_path = None
    try:
        from report_builder import build_results_report, render_pdf
        html_out = build_results_report(rd)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        render_pdf(html_out, tmp_path)
        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(tmp_path)
        tmp_path = None

        fname = f"report_{rd.domain.replace('.', '_')}.pdf"
        _cache_put(cache_key, pdf_bytes, fname)

        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype="application/pdf")
    except Exception as e:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500


# ------------------------------- Frontend ----------------------------------
PAGE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lead Finder</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=Inter:wght@400;500;600&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root{
    --ink:#15171C; --paper:#FBFAF7; --line:#E4E0D6;
    --lead:#E8852B; --lead-bg:#FCF1E4; --comp:#2D6E72; --comp-bg:#EAF1F1;
    --beam:#4B2EBE; --muted:#6B6B63;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);
       font-family:Inter,system-ui,sans-serif;line-height:1.5}
  .mono{font-family:"Space Mono",monospace}
  header{border-bottom:1px solid var(--line);padding:22px 28px;display:flex;
         align-items:baseline;gap:14px;flex-wrap:wrap}
  .brand{font-family:"Bricolage Grotesque",sans-serif;font-weight:700;
         font-size:26px;letter-spacing:-.02em}
  .brand b{color:var(--beam)}
  .tag{color:var(--muted);font-size:13px}
  main{max-width:1040px;margin:0 auto;padding:28px}
  form{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;
       background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px}
  .stype-wrap{display:flex;gap:0;background:var(--paper);border:1px solid var(--line);
              border-radius:9px;padding:3px;align-self:flex-end}
  .stype-btn{font:inherit;font-size:13px;font-weight:600;cursor:pointer;border:none;
             background:none;padding:8px 14px;border-radius:7px;color:var(--muted);
             white-space:nowrap;transition:all .15s}
  .stype-btn.active{background:#fff;color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.12)}
  .low-vis .card{border-left-color:var(--comp)}
  .review-badge{font-size:12px;font-weight:600;padding:3px 8px;border-radius:6px;
                background:var(--lead-bg);color:var(--lead)}
  .review-badge.ok{background:var(--comp-bg);color:var(--comp)}
  .field{display:flex;flex-direction:column;gap:6px;flex:1;min-width:200px}
  label{font-size:12px;font-weight:600;text-transform:uppercase;
        letter-spacing:.06em;color:var(--muted)}
  input{font:inherit;padding:11px 13px;border:1px solid var(--line);
        border-radius:9px;background:var(--paper);width:100%}
  input:focus{outline:2px solid var(--beam);outline-offset:0;border-color:transparent}
  button{font:inherit;font-weight:600;cursor:pointer;border:none;border-radius:9px;
         padding:12px 22px;background:var(--ink);color:#fff;transition:transform .08s}
  button:hover{transform:translateY(-1px)}
  button:disabled{opacity:.5;cursor:wait;transform:none}
  .ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
  .summary{display:flex;gap:26px;margin:26px 2px 14px;flex-wrap:wrap}
  .stat{display:flex;flex-direction:column}
  .stat .n{font-family:"Bricolage Grotesque",sans-serif;font-size:32px;
           font-weight:700;line-height:1}
  .stat .l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
  .stat.lead .n{color:var(--lead)} .stat.comp .n{color:var(--comp)}
  .section-h{display:flex;align-items:center;gap:10px;margin:30px 2px 12px}
  .section-h h2{font-family:"Bricolage Grotesque",sans-serif;font-size:18px;margin:0}
  .pill{font-size:11px;font-weight:700;padding:3px 9px;border-radius:99px}
  .pill.lead{background:var(--lead-bg);color:var(--lead)}
  .pill.comp{background:var(--comp-bg);color:var(--comp)}
  .card{background:#fff;border:1px solid var(--line);border-radius:12px;
        padding:16px 18px;margin-bottom:10px;border-left:3px solid var(--lead)}
  .card .top{display:flex;justify-content:space-between;gap:12px;align-items:baseline;flex-wrap:wrap}
  .card .name{font-weight:600;font-size:16px}
  .card .meta{color:var(--muted);font-size:13px;margin-top:2px}
  .phone{font-size:15px}
  .phone.none{color:var(--muted);font-style:italic;font-family:Inter}
  .copy-wrap{display:inline-flex;align-items:center;gap:6px}
  .copy-btn{font-size:11px;font-weight:600;cursor:pointer;border:1px solid var(--line);
            background:#fff;border-radius:6px;padding:3px 8px;color:var(--muted);
            transition:all .12s;white-space:nowrap}
  .copy-btn:hover{background:var(--ink);color:#fff;border-color:var(--ink)}
  .copy-btn.copied{background:#0f6e56;color:#fff;border-color:#0f6e56}
  .links a{color:var(--beam);text-decoration:none;font-size:13px}
  .links a:hover{text-decoration:underline}
  .comp-row{display:flex;justify-content:space-between;gap:12px;padding:9px 0;
            border-bottom:1px solid var(--line);align-items:center}
  .comp-row:last-child{border-bottom:none}
  .comp-row .site{font-size:13px}
  .empty{text-align:center;color:var(--muted);padding:60px 20px;font-size:15px}
  .err{background:#FCEDED;border:1px solid #E7B7B7;color:#9A2B2B;
       padding:12px 15px;border-radius:9px;margin-top:16px}
  .loading{display:none;color:var(--muted);margin-top:18px}
  .loading.on{display:block}
  @media (prefers-reduced-motion:reduce){button{transition:none}}
  /* --- Tabs --- */
  .tab-nav{display:flex;gap:0;border-bottom:1px solid var(--line);background:#fff;padding:0 28px}
  .tab-nav-btn{font:inherit;font-size:14px;font-weight:600;cursor:pointer;border:none;
               background:none;padding:14px 22px;color:var(--muted);
               border-bottom:3px solid transparent;margin-bottom:-1px;transition:color .15s}
  .tab-nav-btn:hover{color:var(--ink)}
  .tab-nav-btn.active{color:var(--beam);border-bottom-color:var(--beam)}
  .tab-panel{display:none}
  .tab-panel.active{display:block}
  /* --- Report form --- */
  .report-section{background:#fff;border:1px solid var(--line);border-radius:14px;
                  padding:22px 24px;margin-bottom:16px;width:100%}
  .report-section h3{font-family:"Bricolage Grotesque",sans-serif;font-size:15px;
                     font-weight:700;margin:0 0 16px;padding-bottom:10px;
                     border-bottom:1px solid var(--line);color:var(--ink)}
  .field-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
  .field-grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
  .ba-header{display:grid;grid-template-columns:180px 1fr 1fr;gap:12px;
             font-size:11px;font-weight:700;text-transform:uppercase;
             letter-spacing:.06em;color:var(--muted);margin-bottom:6px}
  .ba-row{display:grid;grid-template-columns:180px 1fr 1fr;gap:12px;
          margin-bottom:10px;align-items:center}
  .ba-row .row-label{font-size:13px;font-weight:500;color:var(--ink)}
  .mode-toggle{display:flex;gap:0;background:var(--paper);border:1px solid var(--line);
               border-radius:10px;padding:3px;width:fit-content;margin-bottom:20px}
  .mode-btn{font:inherit;font-size:13px;font-weight:600;cursor:pointer;border:none;
            background:none;padding:8px 18px;border-radius:8px;color:var(--muted);transition:all .15s}
  .mode-btn.active{background:#fff;color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.12)}
  select{font:inherit;padding:11px 13px;border:1px solid var(--line);border-radius:9px;
         background:var(--paper);width:100%}
  select:focus{outline:2px solid var(--beam);outline-offset:0;border-color:transparent}
  .gen-btn{font:inherit;font-weight:700;font-size:15px;cursor:pointer;border:none;
           border-radius:10px;padding:14px 36px;background:var(--beam);color:#fff;
           transition:transform .08s;margin-top:8px}
  .gen-btn:hover{transform:translateY(-1px)}
  .gen-btn:disabled{opacity:.5;cursor:wait;transform:none}
  .rpt-status{margin-top:14px;font-size:13px;color:var(--muted);font-family:"Space Mono",monospace}
  .rpt-status.err{color:#9A2B2B}
  .rpt-status.ok{color:#0f6e56;font-weight:600}
  .info-note{font-size:12px;color:var(--muted);margin-top:6px;padding:8px 12px;
             background:var(--paper);border-radius:7px;border:1px solid var(--line)}
  /* ---- Mobile ---- */
  @media(max-width:640px){
    header{padding:14px 16px;gap:6px}
    .brand{font-size:21px}
    .tag{font-size:12px}
    .tab-nav{padding:0 12px;overflow-x:auto}
    .tab-nav-btn{font-size:13px;padding:12px 14px}
    main{padding:14px 12px}
    form{padding:14px;gap:10px;flex-direction:column}
    .field{min-width:0;width:100%}
    .stype-wrap{width:100%}
    .stype-btn{flex:1;text-align:center}
    button#go{width:100%}
    .summary{gap:14px;margin:18px 0 12px}
    .stat .n{font-size:26px}
    .section-h{margin:22px 0 10px}
    .section-h h2{font-size:15px}
    .card{padding:13px 14px}
    .card .top{flex-direction:column;align-items:flex-start;gap:8px}
    .card .top > div:last-child{width:100%;display:flex;flex-wrap:wrap;
                                align-items:center;gap:8px}
    .copy-wrap{flex-wrap:wrap}
    .comp-row{flex-direction:column;align-items:flex-start;gap:6px}
    .summary > div:last-child{margin-left:0!important;width:100%}
    .summary > div:last-child button{width:100%}
    /* report form */
    .mode-toggle{width:100%}
    .mode-btn{flex:1;text-align:center}
    .report-section{padding:14px}
    .field-grid{grid-template-columns:1fr}
    .field-grid-3{grid-template-columns:1fr}
    .ba-header{grid-template-columns:1fr 1fr 1fr;font-size:10px}
    .ba-header span:first-child{display:none}
    .ba-row{grid-template-columns:1fr 1fr;gap:8px}
    .ba-row .row-label{grid-column:1/-1;font-size:12px;font-weight:600;
                       color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
    .gen-btn{width:100%;padding:14px}
  }
  @media(max-width:400px){
    .ba-header{display:none}
    .ba-row{grid-template-columns:1fr 1fr}
    .ba-row input{padding:8px 10px;font-size:13px}
  }
</style>
</head>
<body>
<header>
  <span class="brand">Lead<b>·</b>Finder</span>
  <span class="tag">Businesses with no website, and the competitors who have one.</span>
</header>

<nav class="tab-nav">
  <button class="tab-nav-btn active" data-tab="finder">Lead Finder</button>
  <button class="tab-nav-btn" data-tab="report">Generate Report</button>
</nav>

<div id="tab-finder" class="tab-panel active">
<main>
  <form id="f">
    <div class="field">
      <label for="place">Locality</label>
      <input id="place" placeholder="Indiranagar, Bangalore" autocomplete="off">
    </div>
    <div class="field">
      <label for="category">Business category</label>
      <input id="category" placeholder="dentists" autocomplete="off">
    </div>
    <div>
      <label style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);display:block;margin-bottom:6px">Search type</label>
      <div class="stype-wrap">
        <button type="button" class="stype-btn active" data-stype="no_website">No Website</button>
        <button type="button" class="stype-btn" data-stype="low_visibility">Low Visibility</button>
      </div>
    </div>
    <button id="go" type="submit">Search</button>
  </form>

  <div id="loading" class="loading mono">Scanning…</div>
  <div id="error"></div>
  <div id="results">
    <div class="empty">Enter a locality and a category to surface businesses with no website.</div>
  </div>
</main>
</div><!-- /tab-finder -->

<div id="tab-report" class="tab-panel">
<main>
  <div class="mode-toggle">
    <button class="mode-btn active" data-mode="auto">Auto-Fetch (DataForSEO)</button>
    <button class="mode-btn" data-mode="manual">Manual Entry</button>
  </div>

  <!-- AUTO MODE FORM -->
  <div id="mode-auto">
    <form id="rpt-auto">
      <div class="report-section">
        <h3>Client Info</h3>
        <div class="field-grid">
          <div class="field">
            <label for="ra-domain">Domain</label>
            <input id="ra-domain" placeholder="acme.com" required oninput="autoClientName('ra')">
          </div>
          <div class="field">
            <label for="ra-client">Client name <span style="font-weight:400;font-size:11px">(auto-filled)</span></label>
            <input id="ra-client" placeholder="Acme Corp" required>
          </div>
          <div class="field">
            <label for="ra-currency">Currency</label>
            <select id="ra-currency">
              <option value="usd">USD ($)</option>
              <option value="inr" selected>INR (₹)</option>
            </select>
          </div>
          <div class="field">
            <label for="ra-eng-label">Engagement label</label>
            <select id="ra-eng-label">
              <option value="9-month engagement">9-month engagement</option>
              <option value="6-month engagement">6-month engagement</option>
            </select>
          </div>
        </div>
      </div>

      <div class="report-section">
        <h3>Time Windows</h3>
        <div class="field-grid">
          <div class="field">
            <label for="ra-before-start">Before — start date</label>
            <input id="ra-before-start" type="date" required oninput="autoLabel('ra-before')">
          </div>
          <div class="field">
            <label for="ra-before-end">Before — end date</label>
            <input id="ra-before-end" type="date" required oninput="autoLabel('ra-before')">
          </div>
          <div class="field" style="display:none">
            <input id="ra-before-label" placeholder="Jun–Aug 2025" readonly>
          </div>
        </div>
        <div class="field-grid" style="margin-top:12px">
          <div class="field">
            <label for="ra-after-start">After — start date</label>
            <input id="ra-after-start" type="date" required oninput="autoLabel('ra-after')">
          </div>
          <div class="field">
            <label for="ra-after-end">After — end date</label>
            <input id="ra-after-end" type="date" required oninput="autoLabel('ra-after')">
          </div>
          <div class="field" style="display:none">
            <input id="ra-after-label" placeholder="Mar–May 2026" readonly>
          </div>
        </div>
      </div>

      <div class="report-section">
        <h3>Data Sources</h3>
        <div class="field-grid">
          <div class="field">
            <label for="ra-traffic-src">Traffic source</label>
            <select id="ra-traffic-src" onchange="toggleTrafficSrc()">
              <option value="dataforseo">DataForSEO (estimated)</option>
              <option value="gsc">Google Search Console (measured)</option>
            </select>
          </div>
          <div class="field" id="ra-loc-wrap">
            <label for="ra-location">DataForSEO location</label>
            <select id="ra-location">
              <option value="2356" selected>India (2356)</option>
              <option value="2840">USA (2840)</option>
            </select>
          </div>
          <div class="field" style="display:none" id="ra-gsc-wrap">
            <label for="ra-gsc-url">GSC site URL</label>
            <input id="ra-gsc-url" placeholder="sc-domain:acme.com">
          </div>
          <div class="field" style="display:none">
            <input id="ra-ga4" placeholder="">
          </div>
        </div>
        <p class="info-note">Credentials are read from server environment variables: <code>DATAFORSEO_LOGIN</code>, <code>DATAFORSEO_PASSWORD</code>, <code>GOOGLE_APPLICATION_CREDENTIALS</code>.</p>
      </div>

      <div class="report-section">
        <h3>Revenue Model</h3>
        <div class="field-grid">
          <div class="field">
            <label for="ra-conv">Conversion rate (e.g. 0.03 = 3%)</label>
            <input id="ra-conv" type="number" step="0.001" min="0" max="1" value="0.03" required>
          </div>
          <div class="field">
            <label for="ra-aov">Average order value</label>
            <input id="ra-aov" type="number" min="0" placeholder="210" required>
          </div>
        </div>
      </div>

      <div class="report-section">
        <h3>AI Overviews (optional)</h3>
        <div class="ba-header"><span></span><span>Before</span><span>After</span></div>
        <div class="ba-row">
          <span class="row-label">AIO citations</span>
          <input type="number" min="0" id="ra-aio-b" placeholder="0" value="0">
          <input type="number" min="0" id="ra-aio-a" placeholder="0" value="0">
        </div>
      </div>

      <button type="submit" class="gen-btn">Generate Report PDF</button>
      <div id="rpt-auto-status" class="rpt-status"></div>
    </form>
  </div><!-- /mode-auto -->

  <!-- MANUAL MODE FORM -->
  <div id="mode-manual" style="display:none">
    <form id="rpt-manual">
      <div class="report-section">
        <h3>Client Info</h3>
        <div class="field-grid">
          <div class="field">
            <label for="rm-domain">Domain</label>
            <input id="rm-domain" placeholder="acme.com" required oninput="autoClientName('rm')">
          </div>
          <div class="field">
            <label for="rm-client">Client name <span style="font-weight:400;font-size:11px">(auto-filled)</span></label>
            <input id="rm-client" placeholder="Acme Corp" required>
          </div>
          <div class="field">
            <label for="rm-currency">Currency</label>
            <select id="rm-currency">
              <option value="usd">USD ($)</option>
              <option value="inr" selected>INR (₹)</option>
            </select>
          </div>
          <div class="field">
            <label for="rm-eng-label">Engagement label</label>
            <select id="rm-eng-label">
              <option value="9-month engagement">9-month engagement</option>
              <option value="6-month engagement">6-month engagement</option>
            </select>
          </div>
          <div class="field">
            <label for="rm-win-before">Before window label</label>
            <input id="rm-win-before" placeholder="Jun–Aug 2025" required>
          </div>
          <div class="field">
            <label for="rm-win-after">After window label</label>
            <input id="rm-win-after" placeholder="Mar–May 2026" required>
          </div>
        </div>
      </div>

      <div class="report-section">
        <h3>Search Console Metrics</h3>
        <div class="ba-header"><span></span><span>Before</span><span>After</span></div>
        <div class="ba-row">
          <span class="row-label">Impressions / mo</span>
          <input type="number" min="0" id="rm-imp-b" placeholder="98000" required>
          <input type="number" min="0" id="rm-imp-a" placeholder="271000" required>
        </div>
        <div class="ba-row">
          <span class="row-label">Clicks / mo</span>
          <input type="number" min="0" id="rm-clk-b" placeholder="2400" required>
          <input type="number" min="0" id="rm-clk-a" placeholder="7600" required>
        </div>
        <div class="ba-row">
          <span class="row-label">Avg. position</span>
          <input type="number" min="0" step="0.1" id="rm-pos-b" placeholder="31.0" required>
          <input type="number" min="0" step="0.1" id="rm-pos-a" placeholder="9.4" required>
        </div>
      </div>

      <div class="report-section">
        <h3>GA4 Metrics</h3>
        <div class="ba-header"><span></span><span>Before</span><span>After</span></div>
        <div class="ba-row">
          <span class="row-label">Organic sessions / mo</span>
          <input type="number" min="0" id="rm-ses-b" placeholder="2100" required>
          <input type="number" min="0" id="rm-ses-a" placeholder="7300" required>
        </div>
        <div class="ba-row">
          <span class="row-label">Avg. engagement time</span>
          <input id="rm-eng-b" placeholder="0m 58s" required>
          <input id="rm-eng-a" placeholder="1m 33s" required>
        </div>
        <div class="field" style="max-width:220px;margin-top:4px">
          <label for="rm-eng-pct">Engagement % change</label>
          <input id="rm-eng-pct" placeholder="+60%" required>
        </div>
      </div>

      <div class="report-section">
        <h3>Keyword Rankings</h3>
        <div class="ba-header"><span></span><span>Before</span><span>After</span></div>
        <div class="ba-row">
          <span class="row-label">Top-3 keywords</span>
          <input type="number" min="0" id="rm-kw3-b" placeholder="2" required>
          <input type="number" min="0" id="rm-kw3-a" placeholder="19" required>
        </div>
        <div class="ba-row">
          <span class="row-label">Top-10 keywords</span>
          <input type="number" min="0" id="rm-kw10-b" placeholder="11" required>
          <input type="number" min="0" id="rm-kw10-a" placeholder="64" required>
        </div>
        <div class="ba-row">
          <span class="row-label">Total keywords</span>
          <input type="number" min="0" id="rm-kwt-b" placeholder="180" required>
          <input type="number" min="0" id="rm-kwt-a" placeholder="540" required>
        </div>
        <div class="ba-row">
          <span class="row-label">AIO citations</span>
          <input type="number" min="0" id="rm-aio-b" placeholder="0" value="0">
          <input type="number" min="0" id="rm-aio-a" placeholder="0" value="0">
        </div>
      </div>

      <div class="report-section">
        <h3>Revenue Model</h3>
        <div class="field-grid">
          <div class="field">
            <label for="rm-conv">Conversion rate (e.g. 0.03 = 3%)</label>
            <input id="rm-conv" type="number" step="0.001" min="0" max="1" value="0.03" required>
          </div>
          <div class="field">
            <label for="rm-aov">Average order value</label>
            <input id="rm-aov" type="number" min="0" placeholder="240" required>
          </div>
          <div class="field">
            <label for="rm-conv-src">Conversion source label</label>
            <input id="rm-conv-src" placeholder="Client's actual (GA4)">
          </div>
        </div>
        <div style="margin-top:12px">
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer">
            <input type="checkbox" id="rm-illustrative"> Mark figures as illustrative
          </label>
        </div>
      </div>

      <button type="submit" class="gen-btn">Generate Report PDF</button>
      <div id="rpt-manual-status" class="rpt-status"></div>
    </form>
  </div><!-- /mode-manual -->

</main>
</div><!-- /tab-report -->

<script>
const f=document.getElementById('f'), go=document.getElementById('go'),
      loading=document.getElementById('loading'), errBox=document.getElementById('error'),
      results=document.getElementById('results');
let last=null, currentStype='no_website';

// Search type toggle
document.querySelectorAll('.stype-btn').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.stype-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    currentStype=btn.dataset.stype;
  });
});

f.addEventListener('submit', async (e)=>{
  e.preventDefault();
  const place=document.getElementById('place').value.trim();
  const category=document.getElementById('category').value.trim();
  errBox.innerHTML=''; results.innerHTML='';
  if(!place||!category){ errBox.innerHTML='<div class="err">Enter both a locality and a category.</div>'; return; }
  go.disabled=true; loading.textContent='Scanning '+place+' for '+category+'…'; loading.classList.add('on');
  try{
    const r=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({place,category,search_type:currentStype})});
    const data=await r.json();
    if(!r.ok){ throw new Error(data.error||'Search failed.'); }
    last=data; render(data);
  }catch(err){ errBox.innerHTML='<div class="err">'+err.message+'</div>'; }
  finally{ go.disabled=false; loading.classList.remove('on'); }
});

function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function host(u){try{return new URL(u).hostname.replace('www.','');}catch{return u;}}

function phoneHtml(mobile){
  if(!mobile) return '<span class="phone none">no number listed</span>';
  const id='cp-'+Math.random().toString(36).slice(2);
  return `<span class="copy-wrap">
    <span class="phone mono">${esc(mobile)}</span>
    <button class="copy-btn" id="${id}" onclick="copyPhone(this,'${esc(mobile)}')">Copy</button>
  </span>`;
}

function copyPhone(btn, num){
  navigator.clipboard.writeText(num).then(()=>{
    btn.textContent='Copied!'; btn.classList.add('copied');
    setTimeout(()=>{ btn.textContent='Copy'; btn.classList.remove('copied'); }, 1800);
  });
}

function stars(rating){
  if(!rating) return '<span style="color:var(--muted);font-size:12px">no rating</span>';
  const full=Math.floor(rating), half=(rating-full)>=0.5?1:0, empty=5-full-half;
  return '<span style="color:#f5a623;font-size:13px">'+'★'.repeat(full)+(half?'½':'')+
         '<span style="color:#ddd">'+'★'.repeat(empty)+'</span></span>'+
         ` <span style="font-size:12px;color:var(--muted)">${rating.toFixed(1)}</span>`;
}

function render(d){
  if(!d.leads.length && !d.competitors.length){
    results.innerHTML='<div class="empty">No listings found for that locality and category. Try a broader area or a different term.</div>';
    return;
  }
  const isLowVis = d.search_type==='low_visibility';

  let html=`<div class="summary">
    <div class="stat lead"><span class="n">${d.leads.length}</span>
      <span class="l">${isLowVis?'Low visibility leads':'Leads · no website'}</span></div>
    <div class="stat comp"><span class="n">${d.competitors.length}</span>
      <span class="l">${isLowVis?'High visibility competitors':'Competitors · have a website'}</span></div>
    <div class="stat"><span class="n mono">${d.total}</span><span class="l">Listings scanned</span></div>
    <div style="margin-left:auto;align-self:center">
      <button class="ghost" id="dl">Download Excel</button></div>
  </div>`;

  if(isLowVis){
    html+=`<div class="section-h"><span class="pill lead">LOW VISIBILITY</span>
      <h2>Have a website — but reviews below average (${d.avg_reviews})</h2></div>`;
    if(!d.leads.length){ html+='<div class="empty">All businesses here have strong review counts.</div>'; }
    d.leads.forEach(l=>{
      html+=`<div class="card low-vis">
        <div class="top">
          <div>
            <div class="name">${esc(l.name)}</div>
            <div class="meta">${esc(l.category)} · ${esc(l.area)}${l.address?' · '+esc(l.address):''}</div>
          </div>
          <div style="text-align:right">
            ${phoneHtml(l.mobile)}<br>
            <span class="review-badge" style="margin-top:4px;display:inline-block">${l.reviews} reviews</span><br>
            <span style="margin-top:4px;display:inline-block">${stars(l.rating)}</span>
          </div>
        </div>
        <div class="links" style="margin-top:8px;display:flex;gap:14px">
          ${l.website?`<a href="${esc(l.website)}" target="_blank" rel="noopener">${esc(host(l.website))} ↗</a>`:''}
          ${l.maps?`<a href="${esc(l.maps)}" target="_blank" rel="noopener">Maps ↗</a>`:''}
        </div></div>`;
    });
    if(d.competitors.length){
      html+=`<div class="section-h"><span class="pill comp">HIGH VISIBILITY</span>
        <h2>Same category — strong review presence</h2></div><div class="card" style="border-left-color:var(--comp)">`;
      d.competitors.forEach(c=>{
        html+=`<div class="comp-row">
          <span class="name">${esc(c.name)}</span>
          <span style="display:flex;align-items:center;gap:10px">
            ${stars(c.rating)}
            <span class="review-badge ok">${c.reviews} reviews</span>
            <a class="links" href="${esc(c.website)}" target="_blank" rel="noopener" style="color:var(--comp)">${esc(host(c.website))} ↗</a>
          </span></div>`;
      });
      html+=`</div>`;
    }
  } else {
    html+=`<div class="section-h"><span class="pill lead">LEADS</span>
      <h2>Prospects with no website</h2></div>`;
    if(!d.leads.length){ html+='<div class="empty">No website-less businesses here — this area is saturated.</div>'; }
    d.leads.forEach(l=>{
      html+=`<div class="card">
        <div class="top">
          <div><div class="name">${esc(l.name)}</div>
            <div class="meta">${esc(l.category)} · ${esc(l.area)}${l.address?' · '+esc(l.address):''}</div></div>
          <div>${phoneHtml(l.mobile)}</div>
        </div>
        <div class="links" style="margin-top:8px">
          ${l.maps?`<a href="${esc(l.maps)}" target="_blank" rel="noopener">View on Maps ↗</a>`:''}
        </div></div>`;
    });
    if(d.competitors.length){
      html+=`<div class="section-h"><span class="pill comp">COMPETITORS</span>
        <h2>Same category, same area — already online</h2></div><div class="card" style="border-left-color:var(--comp)">`;
      d.competitors.forEach(c=>{
        html+=`<div class="comp-row"><span class="name">${esc(c.name)}</span>
          <span class="site"><a class="links" href="${esc(c.website)}" target="_blank" rel="noopener" style="color:var(--comp)">${esc(host(c.website))} ↗</a></span></div>`;
      });
      html+=`</div>`;
    }
  }
  results.innerHTML=html;
  const dl=document.getElementById('dl');
  if(dl) dl.addEventListener('click', downloadExcel);
}

async function downloadExcel(){
  if(!last) return;
  const r=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(last)});
  const blob=await r.blob();
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='leads.xlsx'; a.click(); URL.revokeObjectURL(a.href);
}

// ---------- Tab switching ----------
document.querySelectorAll('.tab-nav-btn').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.tab-nav-btn').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-'+btn.dataset.tab).classList.add('active');
  });
});

// ---------- Mode toggle (Auto / Manual) ----------
document.querySelectorAll('.mode-btn').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.mode-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('mode-auto').style.display = btn.dataset.mode==='auto' ? '' : 'none';
    document.getElementById('mode-manual').style.display = btn.dataset.mode==='manual' ? '' : 'none';
  });
});

// ---------- Auto traffic source toggle ----------
function toggleTrafficSrc(){
  const src = document.getElementById('ra-traffic-src').value;
  document.getElementById('ra-loc-wrap').style.display = src==='dataforseo' ? '' : 'none';
  document.getElementById('ra-gsc-wrap').style.display = src==='gsc' ? '' : 'none';
}

// ---------- Auto-fill client name from domain ----------
function autoClientName(prefix){
  const domEl = document.getElementById(prefix+'-domain');
  const clientEl = document.getElementById(prefix+'-client');
  const domain = domEl.value.trim();
  if(!domain) return;
  // extract name part before first dot, capitalise words
  const raw = domain.replace(/^https?:\/\//,'').split('/')[0].split('.')[0];
  clientEl.value = raw.charAt(0).toUpperCase() + raw.slice(1);
}

// ---------- Auto-generate date range label ----------
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function autoLabel(prefix){
  const startEl = document.getElementById(prefix+'-start');
  const endEl   = document.getElementById(prefix+'-end');
  const labelEl = document.getElementById(prefix+'-label');
  const s = startEl.value, e = endEl.value;
  if(!s && !e){ labelEl.value=''; return; }
  const fmt = iso => {
    const d = new Date(iso+'T00:00:00');
    return MONTHS[d.getMonth()]+' '+d.getFullYear();
  };
  if(s && e){
    const sd = new Date(s+'T00:00:00'), ed = new Date(e+'T00:00:00');
    if(sd.getMonth()===ed.getMonth() && sd.getFullYear()===ed.getFullYear()){
      labelEl.value = fmt(s);
    } else if(sd.getFullYear()===ed.getFullYear()){
      labelEl.value = MONTHS[sd.getMonth()]+'–'+fmt(e);
    } else {
      labelEl.value = fmt(s)+'–'+fmt(e);
    }
  } else {
    labelEl.value = fmt(s||e);
  }
}

// ---------- Generic PDF download helper ----------
async function fetchPdf(url, payload, statusEl, btnEl){
  statusEl.textContent='Generating report…'; statusEl.className='rpt-status';
  btnEl.disabled=true;
  try{
    const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!r.ok){
      const j=await r.json();
      throw new Error(j.error||'Unknown error');
    }
    const blob=await r.blob();
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    const cd=r.headers.get('Content-Disposition')||'';
    const m=cd.match(/filename="?([^"]+)"?/);
    a.download=m?m[1]:'report.pdf';
    a.click(); URL.revokeObjectURL(a.href);
    statusEl.textContent='Report downloaded.'; statusEl.className='rpt-status ok';
  }catch(err){
    statusEl.textContent='Error: '+err.message; statusEl.className='rpt-status err';
  }finally{
    btnEl.disabled=false;
  }
}

// ---------- Auto form submit ----------
document.getElementById('rpt-auto').addEventListener('submit', async(e)=>{
  e.preventDefault();
  const payload={
    mode:'auto',
    client_name: document.getElementById('ra-client').value.trim(),
    domain: document.getElementById('ra-domain').value.trim(),
    currency: document.getElementById('ra-currency').value,
    engagement_label: document.getElementById('ra-eng-label').value,
    traffic_source: document.getElementById('ra-traffic-src').value,
    location_code: parseInt(document.getElementById('ra-location').value),
    conv_rate: parseFloat(document.getElementById('ra-conv').value),
    aov: parseFloat(document.getElementById('ra-aov').value),
    kw_aio: [
      parseInt(document.getElementById('ra-aio-b').value)||0,
      parseInt(document.getElementById('ra-aio-a').value)||0
    ],
    before:{
      start: document.getElementById('ra-before-start').value,
      end:   document.getElementById('ra-before-end').value,
      label: document.getElementById('ra-before-label').value ||
             document.getElementById('ra-before-start').value
    },
    after:{
      start: document.getElementById('ra-after-start').value,
      end:   document.getElementById('ra-after-end').value,
      label: document.getElementById('ra-after-label').value ||
             document.getElementById('ra-after-start').value
    },
  };
  const ga4=document.getElementById('ra-ga4').value.trim();
  if(ga4) payload.ga4_property_id=ga4;
  if(payload.traffic_source==='gsc'){
    payload.gsc_site_url=document.getElementById('ra-gsc-url').value.trim();
  }
  const btn=e.submitter||document.querySelector('#rpt-auto .gen-btn');
  fetchPdf('/api/generate-report', payload,
           document.getElementById('rpt-auto-status'), btn);
});

// ---------- Manual form submit ----------
document.getElementById('rpt-manual').addEventListener('submit', async(e)=>{
  e.preventDefault();
  const payload={
    mode:'manual',
    client_name:  document.getElementById('rm-client').value.trim(),
    domain:       document.getElementById('rm-domain').value.trim(),
    currency:     document.getElementById('rm-currency').value,
    engagement_label: document.getElementById('rm-eng-label').value,
    window_before: document.getElementById('rm-win-before').value.trim(),
    window_after:  document.getElementById('rm-win-after').value.trim(),
    impressions_before: parseFloat(document.getElementById('rm-imp-b').value),
    impressions_after:  parseFloat(document.getElementById('rm-imp-a').value),
    clicks_before: parseFloat(document.getElementById('rm-clk-b').value),
    clicks_after:  parseFloat(document.getElementById('rm-clk-a').value),
    avg_position_before: parseFloat(document.getElementById('rm-pos-b').value),
    avg_position_after:  parseFloat(document.getElementById('rm-pos-a').value),
    sessions_before: parseFloat(document.getElementById('rm-ses-b').value),
    sessions_after:  parseFloat(document.getElementById('rm-ses-a').value),
    engagement_before: document.getElementById('rm-eng-b').value.trim(),
    engagement_after:  document.getElementById('rm-eng-a').value.trim(),
    engagement_pct: document.getElementById('rm-eng-pct').value.trim(),
    kw_top3_before: parseInt(document.getElementById('rm-kw3-b').value)||0,
    kw_top3_after:  parseInt(document.getElementById('rm-kw3-a').value)||0,
    kw_top10_before: parseInt(document.getElementById('rm-kw10-b').value)||0,
    kw_top10_after:  parseInt(document.getElementById('rm-kw10-a').value)||0,
    kw_total_before: parseInt(document.getElementById('rm-kwt-b').value)||0,
    kw_total_after:  parseInt(document.getElementById('rm-kwt-a').value)||0,
    kw_aio_before: parseInt(document.getElementById('rm-aio-b').value)||0,
    kw_aio_after:  parseInt(document.getElementById('rm-aio-a').value)||0,
    conv_rate:  parseFloat(document.getElementById('rm-conv').value),
    aov:        parseFloat(document.getElementById('rm-aov').value),
    conv_source: document.getElementById('rm-conv-src').value||"Client's actual (GA4)",
    illustrative: document.getElementById('rm-illustrative').checked,
  };
  const btn=e.submitter||document.querySelector('#rpt-manual .gen-btn');
  fetchPdf('/api/generate-report', payload,
           document.getElementById('rpt-manual-status'), btn);
});

// ---------- Default date ranges on page load ----------
(function initReportDates(){
  const today = new Date();
  const fmt = d => d.toISOString().split('T')[0];

  // Before window: 12 months ago → 9 months ago
  const bStart = new Date(today); bStart.setMonth(bStart.getMonth() - 12);
  const bEnd   = new Date(today); bEnd.setMonth(bEnd.getMonth() - 9);

  // After window: 9 months ago → today
  const aStart = new Date(today); aStart.setMonth(aStart.getMonth() - 9);
  const aEnd   = new Date(today);

  document.getElementById('ra-before-start').value = fmt(bStart);
  document.getElementById('ra-before-end').value   = fmt(bEnd);
  document.getElementById('ra-after-start').value  = fmt(aStart);
  document.getElementById('ra-after-end').value    = fmt(aEnd);

  autoLabel('ra-before');
  autoLabel('ra-after');
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True, port=5000)