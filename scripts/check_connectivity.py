#!/usr/bin/env python3
"""Record public endpoint connectivity after a failed monitoring run."""

import argparse
import concurrent.futures
import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from monitor import USER_AGENT

TIMEOUT = 8
HOSTS = ("cms.nerima-tky.ed.jp", "www.nerima-tky.ed.jp")
PATHS = (
    (HOSTS[0], "/swas/index.php?id=206"),
    (HOSTS[0], "/weblog/rss2.php?id=206"),
    (HOSTS[1], "/kaishin2-j/"),
)


def check_port(host, port):
    result = {"host": host, "port": port}
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT):
            result["connected"] = True
    except OSError as error:
        result.update(connected=False, error=f"{type(error).__name__}: {error}")
    return result


def check_http(probe):
    url, user_agent = probe
    result = {"url": url, "userAgent": user_agent}
    request = urllib.request.Request(url, headers={
        "User-Agent": user_agent, "Cache-Control": "no-cache",
        "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            result.update(status=response.status, finalUrl=response.url,
                          contentType=response.headers.get("Content-Type"),
                          sampleBytes=len(response.read(2048)))
    except urllib.error.HTTPError as error:
        result.update(status=error.code, error=str(error))
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        result["error"] = f"{type(reason).__name__}: {reason}"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "data" / "connectivity.json")
    args = parser.parse_args()
    result = {"checkedAt": datetime.now(timezone.utc).isoformat(), "dns": {}}
    for host in HOSTS:
        try:
            result["dns"][host] = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        except OSError as error:
            result["dns"][host] = {"error": str(error)}
    probes = [(f"{scheme}://{host}{path}", USER_AGENT)
              for scheme in ("https", "http") for host, path in PATHS]
    probes.extend((f"{scheme}://{HOSTS[0]}{PATHS[0][1]}", "Mozilla/5.0")
                  for scheme in ("https", "http"))
    probes.append(("https://www.city.nerima.tokyo.jp/", USER_AGENT))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        result["ports"] = list(executor.map(lambda pair: check_port(*pair),
                                           [(host, port) for host in HOSTS for port in (443, 80)]))
        result["requests"] = list(executor.map(check_http, probes))
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(encoded)
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
