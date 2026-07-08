"""
Test a list of for proxy being up.

Reads a file:
  (JSON):
    protocol, ip, port, country, country_code, city, anonymity, ssl,
    uptime_percent, asn, isp, latency_ms, last_checked

  (TXT):
    <protocol>://<ip>:<port> (one per line)

Writes a file with only the working proxies:
  (JSON):
    protocol, ip, port, country, country_code, city, anonymity, ssl,
    uptime_percent, asn, isp, latency_ms, last_checked

  (TXT):
    <protocol>://<ip>:<port> (one per line)

Exits non-zero on any HTTP/parse failure so the workflow surfaces it.
"""
import os
import sys
import time
import json
import argparse
import threading
from typing import Any
from dataclasses import dataclass

import urllib3
from urllib3 import ProxyManager
from urllib3.util import Timeout
from urllib3.util.retry import Retry
from urllib.parse import urlsplit
from urllib3.contrib.socks import SOCKSProxyManager
from concurrent.futures import ThreadPoolExecutor, as_completed

"""
Reads a list of proxies from a text file.
In: the path to the text file.
Out: A list of proxies.
Input format: <protocol>://<ip>:<port> (one per line)
Output format: set[<protocol>, <ip>, <port>]
"""
def read_text(filepath: str) -> set[tuple[str, str, Any]]:
    proxies: set[tuple[str, str, Any]] = set()
    with open(filepath, "r", encoding="utf-8") as infile:
        while block := infile.readlines(64):
            for proxy_str in block:
                url = urlsplit(proxy_str)
                if not url.scheme or not url.hostname or not url.port: continue # invalid format
                proxy_key = (url.scheme, url.hostname, url.port)
                if proxy_key in proxies: continue # we already saw this key
                proxies.add(proxy_key)
    return proxies


"""
Reads a list of proxies from a json file.
In: the path to the json file.
Out: A list of proxies.
Input format:
    proxy_list: [
        proxy: {
            protocol: str
            ip: str
            port: Any
            country: str
            country_code: str
            anonymity: str,
            ssl: bool,
            uptime_percent: float | None,
            asn: str,
            isp: str,
            latency_ms: float | None,
            last_checked: float (time_stamp)
        }
    ]
Output format: set[<protocol>, <ip>, <port>]
"""
def read_json(filepath: str) -> set[tuple[str, str, Any]]:
    # TODO
    return 42


"""
Reads a list of proxies from the stdint.
Out: A list of proxies.
Input format: <protocol>://<ip>:<port> (one per line)
Output format: set[<protocol>, <ip>, <port>]
"""
def read_stdin() -> set[tuple[str, str, Any]]:
    # TODO
    return 42


@dataclass(slots=True)
class ProxyCheckResult:
    proxy: str
    ok: bool
    latency_ms: float | None
    status_code: int | None
    origin: str | None
    error: str | None


def make_manager(proxy: tuple[str, str, Any]):
    scheme = proxy[0]
    proxy = f"{proxy[0]}://{proxy[1]}:{proxy[2]}" # transform from proxy tuple to proxy string
    common_kwargs = dict(
        num_pools=1,
        maxsize=1,
        block=False,
        timeout=Timeout(connect=5.0, read=10.0),
        retries=Retry(total=0, connect=0, read=0, redirect=0),
        headers={
            "Accept": "application/json",
            "Connection": "keep-alive",
            "User-Agent": "proxy-checker/1.0",
        },
    )

    if scheme in ("http", "https"):
        return ProxyManager(proxy_url=proxy, **common_kwargs)

    if scheme in ("socks4", "socks4a", "socks5", "socks5h"):
        return SOCKSProxyManager(proxy_url=proxy, **common_kwargs)

    raise ValueError(f"Unsupported proxy scheme: {scheme}")


def check_proxy(proxy: tuple[str, str, Any]) -> ProxyCheckResult:
    try:
        http = make_manager(proxy)
    except ValueError as e:
        return ProxyCheckResult(
            proxy=proxy,
            ok=False,
            latency_ms=None,
            status_code=None,
            origin=None,
            error=e,
        )

    proxy = f"{proxy[0]}://{proxy[1]}:{proxy[2]}" # transform from proxy tuple to proxy string

    print(f"[update] Checking {proxy} ...", file=sys.stderr)
    start = time.perf_counter()

    try:
        r = http.request(
            "GET",
            "https://httpbin.org/ip",
            preload_content=True,
        )

        latency_ms = (time.perf_counter() - start) * 1000.0

        if r.status != 200:
            return ProxyCheckResult(
                proxy=proxy,
                ok=False,
                latency_ms=latency_ms,
                status_code=r.status,
                origin=None,
                error=f"unexpected status {r.status}",
            )

        try:
            data = json.loads(r.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ProxyCheckResult(
                proxy=proxy,
                ok=False,
                latency_ms=latency_ms,
                status_code=r.status,
                origin=None,
                error="invalid json",
            )

        origin = data.get("origin")
        if not isinstance(origin, str):
            return ProxyCheckResult(
                proxy=proxy,
                ok=True,
                latency_ms=latency_ms,
                status_code=r.status,
                origin=None,
                error="missing origin",
            )

        print(f"[update] Proxy {proxy} OK in {latency_ms:.1f} ms", file=sys.stderr)

        return ProxyCheckResult(
            proxy=proxy,
            ok=True,
            latency_ms=latency_ms,
            status_code=r.status,
            origin=origin,
            error=None,
        )

    except urllib3.exceptions.HTTPError as e:
        latency_ms = (time.perf_counter() - start) * 1000.0
        print(f"[update] Proxy {proxy} Not ok ({e.__class__.__name__})", file=sys.stderr)
        return ProxyCheckResult(
            proxy=proxy,
            ok=False,
            latency_ms=latency_ms,
            status_code=None,
            origin=None,
            error=e,
        )
    finally:
        http.clear()


def check_proxies_parallel(proxies: list[str], max_workers: int | None = None) -> list[ProxyCheckResult]:
    if max_workers is None:
        max_workers = min(64, (os.cpu_count() or 4) * 4) # Fallback to 4

    results: list[ProxyCheckResult] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(check_proxy, proxy) for proxy in proxies]

        for future in as_completed(futures):
            results.append(future.result())

    results.sort(
        key=lambda x: (not x.ok, x.latency_ms if x.latency_ms is not None else float("inf"))
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="proxypy-check",
        description="Checks which proxies work given a list of proxies",
    )

    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "-iL",
        "--proxies_list",
        type=str,
        metavar="FILE",
        help="Reads from a text file. Format: <protocol>://<ip>:<port> (one per line)",
    )

    group.add_argument(
        "-iJ",
        "--proxies_json",
        type=str,
        metavar="FILE",
        help="Reads from a json formatted file. Fields: protocol, ip, port, country, country_code, city, anonymity, ssl, uptime_percent, asn, isp, latency_ms, last_checked",
    )

    """
    TODO:
    Argument -t --threads (Thread Count)
    Argument -d --directory (Output Directory)
    """

    args = parser.parse_args()

    if args.proxies_list:
        # read from Text
        proxies = read_text(args.proxies_list)

    elif args.proxies_json:
        # read from Json
        proxies = read_json(args.proxies_json)

    elif not sys.stdin.isatty():
        # read from Pipe
        proxies = read_stdin()

    else:
        parser.error("No input provided.")

    results = check_proxies_parallel(proxies)

    working = [r for r in results if r.ok]
    for r in working[:10]:
        print(r.proxy, f"{r.latency_ms:.1f} ms", r.origin)

if __name__ == "__main__":
    main()
