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
import argparse
import json
import sys
from typing import Any, Iterable
from urllib.parse import urlsplit
import requests

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
def read_stdin(filepath: str) -> set[tuple[str, str, Any]]:
    # TODO
    return 42


def check_proxy(session: requests.Session, proxy: str) -> bool:
    """
    TODO: Make this function work in parallel with multiple workers.
    The number of workers should be coherent with the threads of the machines
    """
    proxies = {
        "http": proxy,
        "https": proxy,
    }
    try:
        r = session.get("https://httpbin.org/ip", proxies=proxies, timeout=(10, 20))
        r.raise_for_status()

        origin = r.json().get("origin") # check if the response is valid
        if not isinstance(origin, str):
            return False

        return True
    except requests.RequestException:
        return False
    except requests.exceptions.JSONDecodeError:
        return False


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


    with requests.Session() as session:
        proxies = [proxy for proxy in proxies if check_proxy(session, f"{proxy[0]}://{proxy[1]}:{proxy[2]}")]

    print(proxies)

if __name__ == "__main__":
    main()
