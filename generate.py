#!/usr/bin/env python3
"""
generate.py — CLI for GrowthPack360 reports.

  # Cold prospect brief — pulls organic traffic from DataForSEO automatically
  python3 generate.py prospect pawspace.in --currency inr --aov 1500 --take-rate 0.25 --location 2356

  # ...or skip the pull and pass traffic yourself
  python3 generate.py prospect acme.com --currency usd --aov 240 --visitors 12000

  # Before/after results report — reads a JSON config of measured numbers
  python3 generate.py results client.json
  python3 generate.py results --template > client.json   # write a starter config

Requires report_builder.py (always) and traffic_estimate.py (only for live pulls).
"""

import argparse
import json
import sys

from report_builder import (ResultsData, ProspectData, build_results_report,
                             build_prospect_brief, render_pdf, USD, INR)

MONEY = {"usd": USD, "inr": INR}

RESULTS_TEMPLATE = {
    "client_name": "Acme Corp", "domain": "acme.com",
    "window_before": "Jun\u2013Aug 2025", "window_after": "Mar\u2013May 2026",
    "engagement_label": "9-month engagement",
    "impressions": [98000, 271000], "clicks": [2400, 7600],
    "avg_position": [31.0, 9.4], "sessions": [2100, 7300],
    "engagement": ["0m 58s", "1m 33s"], "engagement_pct": "+60%",
    "kw_top3": [2, 19], "kw_top10": [11, 64], "kw_total": [180, 540], "kw_aio": [0, 8],
    "conv_rate": 0.03, "aov": 240, "conv_source": "Client's actual (GA4)",
    "currency": "usd", "illustrative": False,
}


def _slug(domain: str) -> str:
    return domain.replace("https://", "").replace("http://", "").split("/")[0].replace(".", "_")


def cmd_prospect(args) -> None:
    money = MONEY[args.currency]

    if args.visitors is not None:
        visitors = float(args.visitors)
        illustrative = False
        print(f"Using provided traffic: {visitors:,.0f} visitors/mo")
    else:
        try:
            from traffic_estimate import get_domain_traffic
        except ImportError:
            sys.exit("traffic_estimate.py not found. Add it, or pass --visitors N to skip the pull.")
        try:
            split = get_domain_traffic(args.domain, location_code=args.location)
        except Exception as exc:               # loud, never silent
            sys.exit(f"DataForSEO pull failed: {exc}\nPass --visitors N to render without a live pull.")
        visitors = split.organic_visitors
        illustrative = False
        print(f"Pulled organic ETV: {visitors:,.0f} visitors/mo "
              f"({split.organic_keywords:,} keywords); paid is a floor only.")

    data = ProspectData(
        name=args.name or args.domain, domain=args.domain,
        descriptor=args.descriptor or "", aov=float(args.aov),
        take_rate=float(args.take_rate), organic_visitors=visitors,
        money=money, illustrative_traffic=illustrative,
    )
    out = args.out or f"brief_{_slug(args.domain)}.pdf"
    render_pdf(build_prospect_brief(data), out)
    print(f"Wrote {out}")


def cmd_results(args) -> None:
    if args.template:
        json.dump(RESULTS_TEMPLATE, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return
    if not args.config:
        sys.exit("Provide a config file (python3 generate.py results client.json) "
                 "or --template to print a starter.")
    if args.auto:
        try:
            from data_sources import fetch_results_data
        except ImportError:
            sys.exit("data_sources.py not found. Cannot use --auto.")
        with open(args.config, encoding="utf-8") as fh:
            cfg = json.load(fh)
        try:
            data = fetch_results_data(cfg)
        except Exception as exc:
            sys.exit(f"Data fetch failed: {exc}")
        out = args.out or f"report_{_slug(cfg['domain'])}.pdf"
        render_pdf(build_results_report(data), out)
        print(f"Wrote {out}")
        return
    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)

    money = MONEY.get(cfg.get("currency", "usd"), USD)
    data = ResultsData(
        client_name=cfg["client_name"], domain=cfg["domain"],
        window_before=cfg["window_before"], window_after=cfg["window_after"],
        engagement_label=cfg["engagement_label"],
        impressions=tuple(cfg["impressions"]), clicks=tuple(cfg["clicks"]),
        avg_position=tuple(cfg["avg_position"]), sessions=tuple(cfg["sessions"]),
        engagement=tuple(cfg["engagement"]), engagement_pct=cfg["engagement_pct"],
        kw_top3=tuple(cfg["kw_top3"]), kw_top10=tuple(cfg["kw_top10"]),
        kw_total=tuple(cfg["kw_total"]), kw_aio=tuple(cfg["kw_aio"]),
        conv_rate=float(cfg["conv_rate"]), aov=float(cfg["aov"]),
        conv_source=cfg.get("conv_source", "Client's actual (GA4)"),
        money=money, illustrative=bool(cfg.get("illustrative", False)),
    )
    out = args.out or f"report_{_slug(cfg['domain'])}.pdf"
    render_pdf(build_results_report(data), out)
    print(f"Wrote {out}  (added ~{money.full(data.added_monthly())}/mo, "
          f"~{money.full(data.added_annual())}/yr organic-attributable)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate GrowthPack360 reports.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prospect", help="cold revenue-opportunity brief (modeled)")
    p.add_argument("domain")
    p.add_argument("--name", default=None)
    p.add_argument("--descriptor", default=None)
    p.add_argument("--aov", default=1500)
    p.add_argument("--take-rate", default=0.25)
    p.add_argument("--location", type=int, default=2356, help="DataForSEO location_code (2356=India, 2840=US)")
    p.add_argument("--currency", choices=MONEY, default="inr")
    p.add_argument("--visitors", default=None, help="skip the DataForSEO pull and use this number")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_prospect)

    r = sub.add_parser("results", help="before/after performance report (measured)")
    r.add_argument("config", nargs="?", default=None, help="JSON config of measured numbers")
    r.add_argument("--template", action="store_true", help="print a starter config and exit")
    r.add_argument("--auto", action="store_true",
                   help="auto-fetch metrics from DataForSEO/GSC/GA4 (requires data_sources.py + credentials)")
    r.add_argument("--out", default=None)
    r.set_defaults(func=cmd_results)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()