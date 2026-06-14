"""
data_sources.py — fetch the measured numbers for a results report so they
don't have to be typed into the config.

Pulls:
  - Google Search Console : impressions, clicks, avg position (per window)
  - GA4 Data API          : organic sessions, avg session duration,
                            and conv_rate + AOV IF ecommerce tracking exists
  - DataForSEO Labs       : keyword ranking bands (top3 / top10 / total) per window

Auth:
  - Google: one service account JSON, added as a user on BOTH the GSC property
    and the GA4 property (Viewer is enough). Point GOOGLE_APPLICATION_CREDENTIALS
    at the JSON file. Scopes: webmasters.readonly + analytics.readonly.
  - DataForSEO: same DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD basic auth as elsewhere.

Honest scope:
  - Traffic / ranking values are MEASURED — fetched, not guessed.
  - conv_rate and AOV are pulled ONLY when GA4 ecommerce reports real transactions.
    Otherwise they are left as None and MUST be supplied (client actuals or a
    labeled benchmark). They are never silently invented.
  - kw_aio (AI Overview citations) has no clean historical per-domain endpoint,
    so it stays a manual/optional input.
"""

from __future__ import annotations

import base64
import os

import requests

from report_builder import ResultsData, USD, INR

MONEY = {"usd": USD, "inr": INR}

GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
DFS_HISTORICAL = "https://api.dataforseo.com/v3/dataforseo_labs/google/historical_rank_overview/live"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}m {seconds % 60:02d}s"

def _dur_to_sec(s: str) -> int:
    m, sec = 0, 0
    for part in s.split():
        if part.endswith("m"):
            m = int(part[:-1])
        elif part.endswith("s"):
            sec = int(part[:-1])
    return m * 60 + sec

def _pct(before: float, after: float) -> str:
    if before == 0:
        return "new"
    p = (after - before) / before * 100
    return f"+{p:.0f}%" if p >= 0 else f"{p:.0f}%"

def _sa_credentials(scopes, creds_path=None):
    from google.oauth2 import service_account
    path = creds_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not path:
        raise RuntimeError("Set GOOGLE_APPLICATION_CREDENTIALS to your service-account JSON path.")
    return service_account.Credentials.from_service_account_file(path, scopes=scopes)


# --------------------------------------------------------------------------- #
# Google Search Console
# --------------------------------------------------------------------------- #
def gsc_window(site_url: str, start: str, end: str, creds_path=None) -> dict:
    """Aggregate clicks / impressions / position for one date window.
    site_url is 'sc-domain:example.com' (domain property) or 'https://example.com/'."""
    from googleapiclient.discovery import build
    creds = _sa_credentials([GSC_SCOPE], creds_path)
    svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    body = {"startDate": start, "endDate": end, "dimensions": [], "type": "web"}
    resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
    rows = resp.get("rows", [])
    if not rows:
        return {"clicks": 0, "impressions": 0, "position": 0.0}
    r = rows[0]
    return {"clicks": r.get("clicks", 0), "impressions": r.get("impressions", 0),
            "position": r.get("position", 0.0)}


# --------------------------------------------------------------------------- #
# GA4 Data API
# --------------------------------------------------------------------------- #
def ga4_window(property_id: str, start: str, end: str, creds_path=None) -> dict:
    """Organic-search sessions, avg session duration, and ecommerce (if present)."""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Metric, Filter, FilterExpression)

    creds = _sa_credentials([GA4_SCOPE], creds_path)
    client = BetaAnalyticsDataClient(credentials=creds)
    req = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        metrics=[Metric(name="sessions"), Metric(name="averageSessionDuration"),
                 Metric(name="purchaseRevenue"), Metric(name="transactions")],
        dimension_filter=FilterExpression(filter=Filter(
            field_name="sessionDefaultChannelGroup",
            string_filter=Filter.StringFilter(value="Organic Search"))),
    )
    resp = client.run_report(req)
    if not resp.rows:
        return {"sessions": 0, "avg_duration": 0.0, "revenue": 0.0, "transactions": 0}
    vals = [m.value for m in resp.rows[0].metric_values]
    sessions, avg_dur, revenue, txns = float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3])
    return {"sessions": sessions, "avg_duration": avg_dur,
            "revenue": revenue, "transactions": txns}


# --------------------------------------------------------------------------- #
# DataForSEO — historical ranking bands
# --------------------------------------------------------------------------- #
def _dfs_post(url: str, payload: list, timeout: int = 30) -> dict:
    login = os.environ.get("DATAFORSEO_LOGIN")
    pwd = os.environ.get("DATAFORSEO_PASSWORD")
    if not login or not pwd:
        raise RuntimeError("Set DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD (API password).")
    token = base64.b64encode(f"{login}:{pwd}".encode()).decode()
    resp = requests.post(url, headers={"Authorization": f"Basic {token}",
                                       "Content-Type": "application/json"},
                         json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status_code") != 20000:
        raise RuntimeError(f"DataForSEO error: {data.get('status_message')}")
    return data


def dfs_rank_bands(domain: str, date_from: str, date_to: str,
                   location_code: int = 2840) -> dict:
    """Ranking bands for the latest monthly snapshot inside the window."""
    payload = [{"target": domain, "location_code": location_code,
                "language_code": "en", "date_from": date_from, "date_to": date_to}]
    data = _dfs_post(DFS_HISTORICAL, payload)
    items = data["tasks"][0]["result"][0]["items"]
    if not items:
        return {"top3": 0, "top10": 0, "total": 0}
    org = (items[-1].get("metrics") or {}).get("organic") or {}
    pos1 = org.get("pos_1", 0)
    pos23 = org.get("pos_2_3", 0)
    pos410 = org.get("pos_4_10", 0)
    return {"top3": pos1 + pos23, "top10": pos1 + pos23 + pos410,
            "total": org.get("count", 0)}


_POS_MIDPOINTS = {"pos_1": 1, "pos_2_3": 2.5, "pos_4_10": 7, "pos_11_20": 15.5,
                  "pos_21_30": 25.5, "pos_31_40": 35.5, "pos_41_50": 45.5,
                  "pos_51_60": 55.5, "pos_61_70": 65.5, "pos_71_80": 75.5,
                  "pos_81_90": 85.5, "pos_91_100": 95.5}


def dfs_traffic_estimate(domain: str, date_from: str, date_to: str,
                         location_code: int = 2840) -> dict:
    """ESTIMATED clicks/impressions/position from DataForSEO (NOT GSC actuals).
    clicks  ~ organic ETV ; impressions ~ impressions_etv ;
    position ~ count-weighted average of ranking-band midpoints.
    Use only as a fallback when GSC is unavailable, and label as estimated."""
    payload = [{"target": domain, "location_code": location_code,
                "language_code": "en", "date_from": date_from, "date_to": date_to}]
    data = _dfs_post(DFS_HISTORICAL, payload)
    items = data["tasks"][0]["result"][0]["items"]
    if not items:
        return {"clicks": 0.0, "impressions": 0.0, "position": 0.0}
    org = (items[-1].get("metrics") or {}).get("organic") or {}
    num = den = 0.0
    for band, mid in _POS_MIDPOINTS.items():
        c = org.get(band, 0)
        num += c * mid
        den += c
    return {"clicks": org.get("etv", 0.0),
            "impressions": org.get("impressions_etv", 0.0),
            "position": (num / den) if den else 0.0}


# --------------------------------------------------------------------------- #
# Orchestrator: config -> fetched ResultsData
# --------------------------------------------------------------------------- #
def fetch_results_data(cfg: dict, creds_path=None) -> ResultsData:
    """cfg keys:
      client_name, domain, gsc_site_url, ga4_property_id,
      before {start,end,label}, after {start,end,label},
      location_code (DataForSEO), currency,
      conv_rate / aov   (optional — pulled from GA4 ecommerce if omitted),
      kw_aio            (optional [before,after], default [0,0]),
      engagement_label  (optional, defaults to "<before> -> <after>")
    """
    b, a = cfg["before"], cfg["after"]
    loc = cfg.get("location_code", 2840)
    money = MONEY.get(cfg.get("currency", "usd"), USD)

    # --- GSC: client-provided numbers, DataForSEO estimate, or API pull ---
    g = cfg.get("gsc")
    traffic_source, traffic_estimated = "Search Console", False
    if g and "clicks" in g:
        gsc_b = {"impressions": g["impressions"][0], "clicks": g["clicks"][0], "position": g["avg_position"][0]}
        gsc_a = {"impressions": g["impressions"][1], "clicks": g["clicks"][1], "position": g["avg_position"][1]}
    elif cfg.get("traffic_source") == "dataforseo":
        gsc_b = dfs_traffic_estimate(cfg["domain"], b["start"], b["end"], loc)
        gsc_a = dfs_traffic_estimate(cfg["domain"], a["start"], a["end"], loc)
        traffic_source, traffic_estimated = "Estimated (DataForSEO)", True
    else:
        gsc_b = gsc_window(cfg["gsc_site_url"], b["start"], b["end"], creds_path)
        gsc_a = gsc_window(cfg["gsc_site_url"], a["start"], a["end"], creds_path)

    # --- GA4: provided block, API pull, or skipped if no property ID ---
    _no_ga4 = {"sessions": 0, "avg_duration": 0.0, "revenue": 0.0, "transactions": 0}
    g4 = cfg.get("ga4")
    if g4 and "sessions" in g4:
        es = g4.get("engagement_sec", [0, 0])
        rev = g4.get("revenue", [0, 0])
        txn = g4.get("transactions", [0, 0])
        ga_b = {"sessions": g4["sessions"][0], "avg_duration": es[0], "revenue": rev[0], "transactions": txn[0]}
        ga_a = {"sessions": g4["sessions"][1], "avg_duration": es[1], "revenue": rev[1], "transactions": txn[1]}
    elif cfg.get("ga4_property_id"):
        ga_b = ga4_window(cfg["ga4_property_id"], b["start"], b["end"], creds_path)
        ga_a = ga4_window(cfg["ga4_property_id"], a["start"], a["end"], creds_path)
    else:
        ga_b = ga_a = _no_ga4

    # --- Rankings: provided block or DataForSEO pull ---
    rk = cfg.get("rankings")
    if rk and "top3" in rk:
        rb_b = {"top3": rk["top3"][0], "top10": rk["top10"][0], "total": rk["total"][0]}
        rb_a = {"top3": rk["top3"][1], "top10": rk["top10"][1], "total": rk["total"][1]}
    else:
        rb_b = dfs_rank_bands(cfg["domain"], b["start"], b["end"], loc)
        rb_a = dfs_rank_bands(cfg["domain"], a["start"], a["end"], loc)

    eng_b = _fmt_duration(ga_b["avg_duration"])
    eng_a = _fmt_duration(ga_a["avg_duration"])

    # conv_rate / aov: explicit override > GA4 ecommerce > error (never guessed)
    conv_rate, aov = cfg.get("conv_rate"), cfg.get("aov")
    conv_source = "Client's actual (provided)"
    if conv_rate is None or aov is None:
        if ga_a.get("transactions", 0) > 0:
            conv_rate = ga_a["transactions"] / ga_a["sessions"] if ga_a["sessions"] else 0
            aov = ga_a["revenue"] / ga_a["transactions"]
            conv_source = "Measured (GA4 ecommerce)"
        else:
            raise RuntimeError(
                "conv_rate and aov are required when GA4 is not connected. "
                "Add them to the config or form.")

    aio = cfg.get("kw_aio", [0, 0])

    return ResultsData(
        client_name=cfg["client_name"], domain=cfg["domain"],
        window_before=b["label"], window_after=a["label"],
        engagement_label=cfg.get("engagement_label", f'{b["label"]} \u2192 {a["label"]}'),
        impressions=(gsc_b["impressions"], gsc_a["impressions"]),
        clicks=(gsc_b["clicks"], gsc_a["clicks"]),
        avg_position=(gsc_b["position"], gsc_a["position"]),
        sessions=(ga_b["sessions"], ga_a["sessions"]),
        engagement=(eng_b, eng_a),
        engagement_pct=_pct(ga_b["avg_duration"], ga_a["avg_duration"]),
        kw_top3=(rb_b["top3"], rb_a["top3"]),
        kw_top10=(rb_b["top10"], rb_a["top10"]),
        kw_total=(rb_b["total"], rb_a["total"]),
        kw_aio=tuple(aio),
        conv_rate=float(conv_rate), aov=float(aov),
        conv_source=conv_source, money=money, illustrative=False,
        traffic_source=traffic_source, traffic_estimated=traffic_estimated,
    )


AUTO_TEMPLATE = {
    "client_name": "Acme Corp", "domain": "acme.com",
    "gsc_site_url": "sc-domain:acme.com", "ga4_property_id": "123456789",
    "before": {"start": "2025-06-01", "end": "2025-08-31", "label": "Jun\u2013Aug 2025"},
    "after": {"start": "2026-03-01", "end": "2026-05-31", "label": "Mar\u2013May 2026"},
    "location_code": 2840, "currency": "usd",
    "conv_rate": 0.03, "aov": 240,
    "kw_aio": [0, 8],
}