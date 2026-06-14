"""
traffic_estimate.py — pull organic ETV and keyword count for a domain from DataForSEO.

Used by generate.py prospect when --visitors is not passed.
Requires DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD environment variables.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta

from data_sources import _dfs_post, DFS_HISTORICAL


@dataclass
class TrafficSplit:
    organic_visitors: float
    organic_keywords: int


def get_domain_traffic(domain: str, location_code: int = 2356) -> TrafficSplit:
    """Return the latest monthly organic ETV and keyword count for a domain."""
    today = date.today()
    date_from = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    payload = [{"target": domain, "location_code": location_code,
                "language_code": "en", "date_from": date_from, "date_to": date_to}]
    data = _dfs_post(DFS_HISTORICAL, payload)
    items = data["tasks"][0]["result"][0]["items"]

    if not items:
        return TrafficSplit(organic_visitors=0.0, organic_keywords=0)

    org = (items[-1].get("metrics") or {}).get("organic") or {}
    return TrafficSplit(
        organic_visitors=float(org.get("etv", 0.0)),
        organic_keywords=int(org.get("count", 0)),
    )
