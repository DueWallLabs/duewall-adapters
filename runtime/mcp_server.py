#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DueWall MCP server - exposes the public duewall.com API as Model Context Protocol
tools, so AI agents (Claude Desktop, Claude Code, any MCP client) can answer
tokenized-credit questions with the same data behind duewall.com.

Run (stdio):  pip install mcp  &&  python runtime/mcp_server.py
See README.md (MCP section) for the Claude Desktop config snippet.

All data: CC-BY, free, light use without a key; heavy programmatic use gets a
free key at https://duewall.com/account (1,000 req/day) sent as Bearer.
Not investment advice.
"""
import json
import os
import urllib.request

try:
    from mcp.server.fastmcp import FastMCP  # mcp 1.x
except ImportError:  # mcp 2.x renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP

API = "https://duewall.com/api/v1"
API_KEY_FILE = os.environ.get("DUEWALL_API_KEY_FILE", "")  # optional Bearer key
mcp = FastMCP("duewall")


def _get(path):
    headers = {"User-Agent": "DueWallMCP/1.0 (github.com/DueWallLabs/duewall-adapters)"}
    if API_KEY_FILE and os.path.exists(API_KEY_FILE):
        headers["Authorization"] = "Bearer " + open(API_KEY_FILE).read().strip()
    req = urllib.request.Request(API + "/" + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


@mcp.tool()
def get_dli() -> str:
    """DueWall Lending Index (DLI) - equal-weight tokenized-credit index, daily,
    inception 2026-10-31 = 100, rules-hash verifiable. Returns latest value + series length."""
    d = _get("index.json")
    vals = d.get("values") or []
    if not vals:
        return "no DLI values"
    return json.dumps({
        "latest_date": vals[-1][0], "dli": vals[-1][1],
        "previous": vals[-2][1] if len(vals) >= 2 else None,
        "inception": d.get("inception"), "base": d.get("base"),
        "methodology_version": d.get("methodology_version"),
        "rules_hash": d.get("rules_hash"), "points": len(vals),
    })


@mcp.tool()
def get_dcr() -> str:
    """DCR/SSR - DeFi Credit Rate reference leg (R1), exact daily on-chain prints."""
    d = _get("dcr.json")
    vals = [v for v in d.get("values", []) if v[2] is not None]
    if not vals:
        return "no DCR values"
    return json.dumps({"index": d.get("index"), "category": d.get("category"),
                       "latest_date": vals[-1][0], "rate_pct": vals[-1][2],
                       "rules_hash": d.get("rules_hash"), "points": len(vals)})


@mcp.tool()
def get_events(event_type: str = "", limit: int = 20) -> str:
    """Structured events, newest first. Optional event_type filter: maturity,
    maturity_resolution, redemption_window, window_open, gate_open,
    liquidity_window, rate_decision, nav_report. Records carry source_url,
    verified_by, status, grade. limit max 50."""
    ev = _get("events.json")
    if event_type:
        ev = [e for e in ev if e.get("event_type") == event_type]
    ev.sort(key=lambda e: e.get("date") or "", reverse=True)
    out = []
    for e in ev[: max(1, min(int(limit), 50))]:
        out.append({k: e.get(k) for k in ("date", "token", "issuer", "event_type",
                                          "amount_usd", "grade", "status", "source_url")})
    return json.dumps({"total_matching": len(ev), "shown": len(out), "events": out})


@mcp.tool()
def get_upcoming_maturities(days: int = 90) -> str:
    """Future-dated maturities within N days - the liability layer that on-chain
    sources do not publish (incl. document-layer entries like tokenised MAS Bills)."""
    from datetime import datetime, timedelta, timezone
    ev = _get("events.json")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    far = (datetime.now(timezone.utc) + timedelta(days=min(int(days), 365))).strftime("%Y-%m-%d")
    sel = sorted((e for e in ev if e.get("event_type") == "maturity"
                  and today <= e.get("date", "") <= far),
                 key=lambda e: e.get("date"))
    out = [{"date": e.get("date"), "token": e.get("token"), "issuer": e.get("issuer"),
            "amount_usd": e.get("amount_usd"), "grade": e.get("grade"),
            "source_url": e.get("source_url")} for e in sel[:20]]
    return json.dumps({"window_days": int(days), "count": len(sel), "upcoming": out})


@mcp.tool()
def get_terms(token: str = "") -> str:
    """Human-verified liquidity terms per fund (structure, liquidity, settlement,
    min investment, fees, domicile). Optional token substring filter."""
    rows = _get("terms.json")
    if token:
        rows = [r for r in rows if token.lower() in (r.get("token") or "").lower()
                or token.lower() in (r.get("issuer") or "").lower()]
    return json.dumps({"count": len(rows), "funds": rows[:30]})


@mcp.tool()
def get_pools() -> str:
    """Pool snapshot: Centrifuge pools + DefiLlama RWA pools (TVL/APY triage layer)."""
    d = _get("pools.json")
    out = {"fetched_at": d.get("fetched_at"), "pools": []}
    for src, items in (d.get("sources") or {}).items():
        for p in (items or [])[:40]:
            out["pools"].append({"source": src, "name": p.get("name") or p.get("pool"),
                                 "chain": p.get("chain"), "tvl_usd": p.get("tvl_usd"),
                                 "apy": p.get("apy")})
    return json.dumps(out)


@mcp.tool()
def get_verification(fund: str = "") -> str:
    """Claim-vs-observed verification: issuer claims (factsheets, official calendars)
    checked against on-chain/document-layer observations. Three-state verdicts:
    consistent / discrepant / untestable, each with evidence links. Optional fund
    substring filter. Discrepant findings are the signal - e.g. a fund claiming
    monthly redemptions while the contract runs 14-day epochs."""
    d = _get("verification.json")
    verdicts = d.get("verdicts") or []
    if fund:
        verdicts = [v for v in verdicts
                    if fund.lower() in (v.get("token") or "").lower()
                    or fund.lower() in (v.get("issuer") or "").lower()]
    return json.dumps({"generated": d.get("generated"),
                       "counts": d.get("counts"),
                       "shown": len(verdicts[:40]),
                       "verdicts": verdicts[:40]})


@mcp.tool()
def get_allowlist() -> str:
    """Rule-based verified-issuer allow-list for investment-policy engines: funds
    with grade-A human-verified terms AND zero discrepant checks. Rules-hashed,
    append-only history, Bitcoin-anchored. Membership changes publish with
    evidence — no discretionary overrides (earned, never bought)."""
    d = _get("allowlist.json")
    return json.dumps({"generated": d.get("generated"), "date": d.get("date"),
                       "rules_hash": d.get("rules_hash"),
                       "counts": d.get("counts"),
                       "members": [{"name": m.get("name"), "issuer": m.get("issuer"),
                                    "liquidity": (m.get("terms") or {}).get("liquidity"),
                                    "settlement": (m.get("terms") or {}).get("settlement"),
                                    "domicile": (m.get("terms") or {}).get("domicile"),
                                    "checks": m.get("checks")}
                                   for m in (d.get("members") or [])],
                       "excluded": d.get("excluded"),
                       "events": d.get("events")})


@mcp.tool()
def get_flows(fund: str = "") -> str:
    """Per-fund daily NET capital flows (FLW3) from on-chain totalIssuance daily
    anchors: net_shares / net_usd / tvl_usd per day. Conservation telescopes
    exactly within the observed window; mid-life series are full quality (all-time
    aggregates are floors); structural discontinuities flagged degraded. Optional fund
    substring filter (e.g. jaaa). Daily series trimmed to the most recent 90 days
    per fund; all-time in/out/net aggregates always included. Full series:
    https://duewall.com/api/v1/flows.json"""
    from datetime import datetime, timedelta, timezone
    d = _get("flows.json")
    funds = d.get("funds") or []
    if fund:
        funds = [f for f in funds
                 if fund.lower() in (f.get("token") or "").lower()
                 or fund.lower() in (f.get("name") or "").lower()]
    out = []
    for f in funds:
        out.append({"token": f.get("token"), "name": f.get("name"),
                    "grade": f.get("grade"), "tvl_usd": f.get("tvl_usd"),
                    "all_time": f.get("all_time"),
                    "daily": (f.get("daily") or [])[-90:]})
    return json.dumps({"generated": d.get("generated"), "rules_hash": d.get("rules_hash"),
                       "counts": {**d.get("counts", {}), "shown": len(out)},
                       "funds": out,
                       "events": (d.get("events") or [])[:20],
                       "note": "daily trimmed to most recent 90 days per fund; events = large executions (|USD|>=1M) at minute-level"})


if __name__ == "__main__":
    mcp.run()
