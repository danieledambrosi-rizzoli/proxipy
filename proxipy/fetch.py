"""
Python wrapper around the ProxyScrape v4 public API.

Writes:
  <out_dir>/proxies.{txt,json}

The "all" shard is fetched in one call (with a generous limit). Protocol and
country shards are derived from that response by filtering — keeping one API
call per run and guaranteeing the shards stay internally consistent (no
inter-shard skew from upstream churn between calls).

Schema notes (upstream):
  - protocol ∈ {http, socks4, socks5}  (HTTPS is a CAPABILITY flag on HTTP,
    not its own protocol value — exposed via `ssl: true`)
  - uptime is reported as a 0–100 percentage by ProxyScrape; we round to 2dp
  - times_alive / times_dead expose the underlying check history

Published columns (JSON):
  protocol, ip, port, country, country_code, city, anonymity, ssl,
  uptime_percent, asn, isp, latency_ms, last_checked

TXT format: <protocol>://<ip>:<port>  (one per line)

Exits non-zero on any HTTP/parse failure so the workflow surfaces it.
"""
from __future__ import annotations
from dataclasses import dataclass

import json
import os
import sys
import argparse
import datetime
import time
import urllib.error
import urllib.request
import urllib.parse
from typing import Any, Iterable

# The API caps each call at 2000 proxies regardless of the requested limit,
# so we paginate with skip until nextpage is false. PAGE_SIZE is the per-call
# cap; MAX_PAGES is a safety stop to avoid runaway loops if the API
# misreports nextpage.
PAGE_SIZE = 2000
MAX_PAGES = 30  # 30 * 2000 = 60k headroom over the current ~22k pool

API_BASE = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?"
)

@dataclass
class ProxyQuery:
    protocol: str = "all"
    ssl:      str = "all"
    country:  str = "all"
    anonymity: str = "all"
    skip:     int = 0

    def to_url(self) -> str:
        params = {
            "request":      "get_proxies",
            "proxy_format": "protocolipport",
            "format":       "json",
            "limit":        PAGE_SIZE,
            "protocol":     self.protocol,
            "ssl":          self.ssl,
            "country":      self.country,
            "anonymity":    self.anonymity,
            "skip":         self.skip,
        }
        return f"{API_BASE}{urllib.parse.urlencode(params)}"

REQUEST_DELAY_S = 1.5  # polite delay between pages to avoid upstream 5xx
MAX_RETRIES = 4

"""
Default dir is used when an out directory is not provided
If you intend to include this script in automations you should change the Format
"""
DEFAULT_DIR = f"./{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}_proxies/"

def fetch_page(query: ProxyQuery) -> dict[str, Any]:
    skip = query.skip
    url = query.to_url()
    req = urllib.request.Request(
        url,
        headers={
            # remember to be nice
            # remember to add the github repo
            "User-Agent": "proxipy/ ty for the proxies"
        },
    )
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                if resp.status != 200:
                    raise SystemExit(f"API returned HTTP {resp.status} (skip={skip})")
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 5xx / 429 — retry with exponential backoff. 4xx other than 429
            # is a real client error, no point retrying.
            if e.code in (429, 500, 502, 503, 504):
                last_err = e
                backoff = 2 ** attempt
                print(
                    f"[update] skip={skip} got HTTP {e.code}; retry in {backoff}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            backoff = 2 ** attempt
            print(
                f"[update] skip={skip} network error: {e}; retry in {backoff}s",
                file=sys.stderr,
            )
            time.sleep(backoff)
    raise SystemExit(f"API failed after {MAX_RETRIES} retries (skip={skip}): {last_err}")


def fetch_all(query: ProxyQuery) -> list[dict[str, Any]]:
    """Page through the API until nextpage is false (or MAX_PAGES safety).

    The upstream API has a deep-pagination issue where requests beyond
    skip ≈ 10,000 currently return 500 due to a query-ordering bug
    (orderBy applied after skip/limit). If we hit that wall partway
    through, we keep whatever was fetched from successful pages rather
    than aborting the entire run. A snapshot of ~10k proxies is still
    useful — better than failing the workflow and shipping no update.
    First-page failures are real outages and re-raise.
    """
    out: list[dict[str, Any]] = []
    skip = 0
    for page in range(MAX_PAGES):
        try:
            payload = fetch_page(query=query)
        except SystemExit as err:
            if not out:
                raise
            print(
                f"[update] Pagination ended at page {page + 1} (skip={skip}) — {err}. "
                f"Keeping {len(out)} proxies fetched so far.",
                file=sys.stderr,
            )
            break
        proxies = payload.get("proxies")
        if not isinstance(proxies, list):
            raise SystemExit("API response missing 'proxies' array")
        if not proxies:
            break
        out.extend(proxies)
        if not payload.get("nextpage"):
            break
        skip += PAGE_SIZE
        query.skip = skip
        print(
            f"[update] Page {page + 1}: {len(proxies)} (running total {len(out)})",
            file=sys.stderr,
        )
        time.sleep(REQUEST_DELAY_S)
    return out


def round_uptime(uptime: Any) -> float | None:
    try:
        v = float(uptime)
    except (TypeError, ValueError):
        return None
    return round(v, 2)


def flatten(proxy: dict[str, Any]) -> dict[str, Any]:
    """Reduce upstream shape to the flat record we publish."""
    ip_data = proxy.get("ip_data") or {}
    # `ip_data.as` is a string like "AS131293 TOT Public Company Limited".
    # We split it into ASN + ASN org to match the conventions used by
    # GeoNode and ProxyDB.
    as_field = ip_data.get("as") or ""
    asn = ""
    if as_field.startswith("AS"):
        asn = as_field.split(" ", 1)[0]  # "AS131293"
    return {
        "protocol": (proxy.get("protocol") or "").lower(),
        "ip": proxy.get("ip") or "",
        "port": proxy.get("port"),
        "country": ip_data.get("country") or "",
        "country_code": (ip_data.get("countryCode") or "").upper(),
        "city": ip_data.get("city") or "",
        "anonymity": (proxy.get("anonymity") or "").lower(),
        "ssl": bool(proxy.get("ssl")),
        "uptime_percent": round_uptime(proxy.get("uptime")),
        "asn": asn,
        "isp": ip_data.get("isp") or "",
        "latency_ms": (
            round(float(proxy["timeout"]), 2)
            if isinstance(proxy.get("timeout"), (int, float))
            else None
        ),
        "last_checked": proxy.get("last_seen"),
    }


def render_txt(rows: Iterable[dict[str, Any]]) -> str:
    lines = []
    for r in rows:
        if not r["ip"] or not r["port"] or not r["protocol"]:
            continue
        lines.append(f"{r['protocol']}://{r['ip']}:{r['port']}")
    return "\n".join(lines) + ("\n" if lines else "")


def render_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"


def write_shard(dirpath: str, rows: list[dict[str, Any]]) -> None:
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, "proxies.txt"), "w", encoding="utf-8") as f:
        f.write(render_txt(rows))
    with open(os.path.join(dirpath, "proxies.json"), "w", encoding="utf-8") as f:
        f.write(render_json(rows))


VALID_PROTOCOLS=list(sorted(["all","http","https","socks4","socks5"]))

def protocol_list(value):
    protocols = {p.strip() for p in value.split(",")}
    for p in protocols:
        if p not in VALID_PROTOCOLS:
            raise argparse.ArgumentTypeError(
                f"Invalid protocol '{p}'. Valid options: {', '.join(VALID_PROTOCOLS)}"
            )
    return protocols

# Official ISO codes scraped from the wikipedia page
VALID_ISO_CODES = {"AD","AE","AF","AG","AI","AL","AM","AO","AQ","AR","AS","AT","AU","AW","AX","AZ","BA","BB","BD","BE","BF","BG","BH","BI","BJ","BL","BM","BN","BO","BQ","BR","BS","BT","BV","BW","BY","BZ","CA","CC","CD","CF","CG","CH","CI","CK","CL","CM","CN","CO","CR","CU","CV","CW","CX","CY","CZ","DE","DJ","DK","DM","DO","DZ","EC","EE","EG","EH","ER","ES","ET","FI","FJ","FK","FM","FO","FR","GA","GB","GD","GE","GF","GG","GH","GI","GL","GM","GN","GP","GQ","GR","GS","GT","GU","GW","GY","HK","HM","HN","HR","HT","HU","ID","IE","IL","IM","IN","IO","IQ","IR","IS","IT","JE","JM","JO","JP","KE","KG","KH","KI","KM","KN","KP","KR","KW","KY","KZ","LA","LB","LC","LI","LK","LR","LS","LT","LU","LV","LY","MA","MC","MD","ME","MF","MG","MH","MK","ML","MM","MN","MO","MP","MQ","MR","MS","MT","MU","MV","MW","MX","MY","MZ","NA","NC","NE","NF","NG","NI","NL","NO","NP","NR","NU","NZ","OM","PA","PE","PF","PG","PH","PK","PL","PM","PN","PR","PS","PT","PW","PY","QA","RE","RO","RS","RU","RW","SA","SB","SC","SD","SE","SG","SH","SI","SJ","SK","SL","SM","SN","SO","SR","SS","ST","SV","SX","SY","SZ","TC","TD","TF","TG","TH","TJ","TK","TL","TM","TN","TO","TR","TT","TV","TW","TZ","UA","UG","UM","US","UY","UZ","VA","VC","VE","VG","VI","VN","VU","WF","WS","YE","YT","ZA","ZM","ZW"}
# Official API silently fails when the country code does not exist... you don't want that right?
def country_list(value):
    countries = {c.strip().upper() for c in value.split(",")}
    if "ALL" in countries: return ["all"] # Just go with all if present
    for c in countries:
        if c not in VALID_ISO_CODES:
            raise argparse.ArgumentTypeError(
                f"Invalid Alpha-2 iso code '{c}'. {len(VALID_ISO_CODES)} valid options: {', '.join(VALID_PROTOCOLS[:5])} ..."
            )
    return countries


# Lookup table for anonymity levels
VALID_ANONYMITY_LEVELS = [
    "transparent",
    "anonymous",
    "elite",
    "all"
]

def anonymity_level(value):
    levels = {int(v.strip()) for v in value.split(",")}
    if 3 in levels: return {VALID_ANONYMITY_LEVELS[3]}
    for l in levels:
        if l < 0 or l >= len(VALID_ANONYMITY_LEVELS):
            raise argparse.ArgumentTypeError(
                f"""Invalid anonymity level '{l}'.
                Valid options: [0..=3], {', '.join(VALID_ANONYMITY_LEVELS)}"""
            )
    return set(map(lambda index: VALID_ANONYMITY_LEVELS[index], levels))

# Maps (want_http, want_https) → ssl param value.
# "https" is just http+ssl=yes; they share protocol=http on the API.
_SSL_MATRIX = {
    (True,  True ): "all",   # want both
    (True,  False): "no",    # HTTP only
    (False, True ): "yes",   # SSL-capable only
    (False, False): "all",   # Default fallback
}

def resolve_api_params(selected: set[str]) -> tuple[str, str]:
    if "all" in selected:
        return "all", "all"

    want_http  = "http"  in selected
    want_https = "https" in selected

    # Collapse "https" → "http" + "ssl"
    api_protocols = {"http" if p == "https" else p for p in selected}

    return ",".join(api_protocols), _SSL_MATRIX[want_http, want_https]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="proxypy-fetch",
        description="Fetch proxies from a public and free proxy list",
    )

    parser.add_argument(
        "-p",
        "--protocol",
        type=protocol_list,
        default=["all"],
        metavar="Protocol[,Protocol...]",
        help="Protocols to use. Multiple: comma-separated. Options: all, http, https, sock4, sock5 (default: all).",
    )

    parser.add_argument(
        "-i",
        "--iso2",
        type=country_list,
        default=["all"],
        metavar="CountryCode[,CountryCode...]",
        help=f"Alpha-2 ISO country code or all. Multiple: comma-separated. Options: {', '.join(list(VALID_ISO_CODES)[:7])} (default: all).",
    )

    parser.add_argument(
        "-a",
        "--anonymity",
        type=anonymity_level,
        default=["all"],
        metavar="int[,int...]",
        help="Anonymity level (HTTP only). Multiple: comma-separated. Options: [0=transparent, 1=anonymous, 2=elite, 3=all] (default: all)"
    )

    parser.add_argument(
        "-d",
        "--directory",
        type=str,
        default=DEFAULT_DIR,
        metavar="DIR",
        help="Output dir. If the dir already has the proxy file they will be replaced. (default: TIME()_proxies)",
    )

    args = parser.parse_args()

    # CASES:
    # ALL => &protocol=all&ssl=all
    # HTTP and !HTTPS => &protocol=[protocols],http&ssl=no
    # !HTTP and HTTPS => &protocol=[protocols],http&ssl=yes
    # HTTP and HTTPS  => &protocol=[protocols],http&ssl=all
    # ANY OTHER CASE  => &protocol=[protocols]
    protocol, ssl = resolve_api_params(args.protocol)
    country       = ",".join(args.iso2)
    anonymity     = ",".join(args.anonymity)

    query = ProxyQuery(
        protocol  = protocol,
        ssl       = ssl,
        country   = country,
        anonymity = anonymity,
    )

    print(f"[update] Fetching from {query.to_url()}", file=sys.stderr)
    raw = fetch_all(query=query)
    rows = [flatten(p) for p in raw]
    rows = [r for r in rows if r["ip"] and r["port"] and r["protocol"]]

    # Dedupe on (protocol, ip, port). Upstream pagination currently isn't
    # stable (orderBy is applied after skip/limit server-side), so the same
    # proxy can appear on multiple pages. Keeping the first occurrence is
    # fine — all duplicates carry identical identifying fields.
    seen: set[tuple[str, str, Any]] = set()
    deduped: list[dict[str, Any]] = []
    for r in rows:
        key = (r["protocol"], r["ip"], r["port"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    if len(deduped) != len(rows):
        print(
            f"[update] Deduped {len(rows) - len(deduped)} duplicate proxies",
            file=sys.stderr,
        )
    rows = deduped

    """
    TODO: Implement some sorting logic
        sort by uptime,
        sort by protocol,
        sort by country,
        sort by last_checked,
    """

    print(f"[update] Final unique proxy count: {len(rows)}", file=sys.stderr)
    write_shard(args.directory, rows)
    print(f"[update] Out dir: {args.directory}", file=sys.stderr)


if __name__ == "__main__":
    main()
