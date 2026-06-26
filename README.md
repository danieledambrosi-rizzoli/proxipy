# Proxypy

A small Python tool that fetches free proxies from the public [ProxyScrape](https://github.com/ProxyScrape/free-proxy-list) API and saves them to disk in `.txt` and `.json` formats.

## What it does

- Pulls the full free-proxy list in a single paginated pass.
- Lets you filter by **protocol**, **country**, and **anonymity** level.
- Writes the results into an output directory of your choice.

## Requirements

- Python 3.10+
- No third-party dependencies — only the standard library is used.

## Get the script

Clone the repo:

```bash
git clone https://github.com/DanieleDAmbrosi/proxypy.git
cd proxypy
```

## Usage

Run the script with no arguments to fetch every proxy and save them to the current folder:

```bash
python proxipy.py
```

### Options

```text
-p, --protocol    Protocol(s) to fetch.    Comma-separated.  Default: all
-i, --iso2        Country code(s).         Comma-separated.  Default: all
-a, --anonymity   Anonymity level.         0=transparent, 1=anonymous, 2=elite, 3=all.  Default: all
-d, --directory   Output directory.        Default: ./
```

### Examples

Fetch only HTTP proxies from the US:

```bash
python proxipy.py -p http -i US
```

Fetch elite-only SOCKS5 proxies into a custom folder:

```bash
python proxipy.py -p socks5 -a 2 -d ./my-proxies
```

Fetch HTTP, HTTPS, and SOCKS4 at once:

```bash
python proxipy.py -p http,https,socks4
```

## Output

For every run, the script writes `data.txt` and `data.json` into the chosen output directory. The text file looks like:

```text
http://123.45.67.89:8080
socks5://98.76.54.32:1080
...
```

## Credits

Proxies are scraped from the public ProxyScrape API:
https://api.proxyscrape.com/

Inspired by: https://github.com/ProxyScrape/free-proxy-list
