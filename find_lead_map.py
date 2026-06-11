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
import time
import requests
import secrets
from flask import (Flask, request, jsonify, render_template_string, send_file,
                  redirect, make_response)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAIL_URL = "https://places.googleapis.com/v1/places/{pid}"
SEARCH_MASK = ("places.id,places.displayName,places.formattedAddress,"
               "places.websiteUri,places.primaryTypeDisplayName,"
               "places.googleMapsUri,nextPageToken")
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


def run_search(category, place):
    places = text_search(category, place)
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
            continue  # qualify only leads that have a contact number
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
            "total": len(places), "category": category, "place": place}


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
    if not place or not category:
        return jsonify({"error": "Enter both a place and a category."}), 400
    try:
        return jsonify(run_search(category, place))
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
  .field{display:flex;flex-direction:column;gap:6px;flex:1;min-width:200px}
  label{font-size:12px;font-weight:600;text-transform:uppercase;
        letter-spacing:.06em;color:var(--muted)}
  input{font:inherit;padding:11px 13px;border:1px solid var(--line);
        border-radius:9px;background:var(--paper)}
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
</style>
</head>
<body>
<header>
  <span class="brand">Lead<b>·</b>Finder</span>
  <span class="tag">Businesses with no website, and the competitors who have one.</span>
</header>

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
    <button id="go" type="submit">Search</button>
  </form>

  <div id="loading" class="loading mono">Scanning…</div>
  <div id="error"></div>
  <div id="results">
    <div class="empty">Enter a locality and a category to surface businesses with no website.</div>
  </div>
</main>

<script>
const f=document.getElementById('f'), go=document.getElementById('go'),
      loading=document.getElementById('loading'), errBox=document.getElementById('error'),
      results=document.getElementById('results');
let last=null;

f.addEventListener('submit', async (e)=>{
  e.preventDefault();
  const place=document.getElementById('place').value.trim();
  const category=document.getElementById('category').value.trim();
  errBox.innerHTML=''; results.innerHTML='';
  if(!place||!category){ errBox.innerHTML='<div class="err">Enter both a locality and a category.</div>'; return; }
  go.disabled=true; loading.textContent='Scanning '+place+' for '+category+'…'; loading.classList.add('on');
  try{
    const r=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({place,category})});
    const data=await r.json();
    if(!r.ok){ throw new Error(data.error||'Search failed.'); }
    last=data; render(data);
  }catch(err){ errBox.innerHTML='<div class="err">'+err.message+'</div>'; }
  finally{ go.disabled=false; loading.classList.remove('on'); }
});

function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function host(u){try{return new URL(u).hostname.replace('www.','');}catch{return u;}}

function render(d){
  if(!d.leads.length && !d.competitors.length){
    results.innerHTML='<div class="empty">No listings found for that locality and category. Try a broader area or a different term.</div>';
    return;
  }
  let html=`<div class="summary">
    <div class="stat lead"><span class="n">${d.leads.length}</span><span class="l">Leads · no website</span></div>
    <div class="stat comp"><span class="n">${d.competitors.length}</span><span class="l">Competitors · have a website</span></div>
    <div class="stat"><span class="n mono">${d.total}</span><span class="l">Listings scanned</span></div>
    <div style="margin-left:auto;align-self:center">
      <button class="ghost" id="dl">Download Excel</button></div>
  </div>`;

  html+=`<div class="section-h"><span class="pill lead">LEADS</span>
    <h2>Prospects with no website</h2></div>`;
  if(!d.leads.length){ html+='<div class="empty">No website-less businesses here — this area is saturated.</div>'; }
  d.leads.forEach(l=>{
    const phone = l.mobile ? `<span class="phone mono">${esc(l.mobile)}</span>`
                           : `<span class="phone none">no number listed</span>`;
    html+=`<div class="card">
      <div class="top">
        <div><div class="name">${esc(l.name)}</div>
          <div class="meta">${esc(l.category)} · ${esc(l.area)}${l.address?' · '+esc(l.address):''}</div></div>
        <div>${phone}</div>
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
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True, port=5000)