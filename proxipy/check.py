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
        proxies = 42

    elif args.proxies_json:
        proxies = 42

    elif not sys.stdin.isatty():
        proxies = 42

    else:
        parser.error("No input provided. Use -iL FILE, -iJ FILE, or pipe data via stdin.")


if __name__ == "__main__":
    main()
