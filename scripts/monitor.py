#!/usr/bin/env python3
"""Fetch Nerima JHS sites server-side and write a stable monitoring snapshot."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "status.json"
USER_AGENT = "Nerima-JHS-HP-monitor/2.0 (+https://github.com/didi-gogo/Nerima-JHS-HP-monitor)"

SCHOOLS = [
    (1, "練馬区立旭丘中学校", "asahigaoka-j"), (2, "練馬区立豊玉中学校", "toyotama-j"),
    (3, "練馬区立豊玉第二中学校", "toyotama2-j"), (4, "練馬区立中村中学校", "nakamura-j"),
    (5, "練馬区立開進第一中学校", "kaishin1-j"), (6, "練馬区立開進第二中学校", "kaishin2-j"),
    (7, "練馬区立開進第三中学校", "kaishin3-j"), (8, "練馬区立開進第四中学校", "kaishin4-j"),
    (9, "練馬区立北町中学校", "kitamachi-j"), (10, "練馬区立練馬中学校", "nerima-j"),
    (11, "練馬区立練馬東中学校", "nerima-e-j"), (12, "練馬区立貫井中学校", "nukui-j"),
    (13, "練馬区立田柄中学校", "tagara-j"), (14, "練馬区立豊渓中学校", "hokei-j"),
    (15, "練馬区立光が丘第一中学校", "hikarigaoka1-j"), (16, "練馬区立光が丘第二中学校", "hikarigaoka2-j"),
    (17, "練馬区立光が丘第三中学校", "hikarigaoka3-j"), (18, "練馬区立石神井中学校", "shakujii-j"),
    (19, "練馬区立石神井東中学校", "shakujiihigashi-j"), (20, "練馬区立石神井西中学校", "shakujiinishi-j"),
    (21, "練馬区立石神井南中学校", "shakujiiminami-j"), (22, "練馬区立上石神井中学校", "kamishakujii-j"),
    (23, "練馬区立南が丘中学校", "minamigaoka-j"), (24, "練馬区立谷原中学校", "yawara-j"),
    (25, "練馬区立三原台中学校", "miharadai-j"), (26, "練馬区立大泉中学校", "ooizumi-j"),
    (27, "練馬区立大泉第二中学校", "ooizumi2-j"), (28, "練馬区立大泉西中学校", "ooizuminishi-j"),
    (29, "練馬区立大泉北中学校", "ooizumikita-j"), (30, "練馬区立大泉学園中学校", "ooizumigakuen-j"),
    (31, "練馬区立大泉学園桜中学校", "ooizumigakuensakura-j"), (32, "練馬区立関中学校", "seki-j"),
    (33, "練馬区立八坂中学校", "yasaka-j"),
]
CMS_ID_OVERRIDES = {31: 159}  # 大泉学園桜中は小中一貫校「大泉桜学園」の共通サイト


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def decode_body(body: bytes, content_type: str = "") -> str:
    match = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type, re.I)
    if not match:
        head = body[:2048].decode("ascii", errors="ignore")
        match = re.search(r"charset\s*=\s*['\"]?([\w-]+)", head, re.I)
    charset = match.group(1).lower() if match else "utf-8"
    aliases = {"euc-jp": "euc_jp", "shift_jis": "cp932", "x-sjis": "cp932"}
    try:
        return body.decode(aliases.get(charset, charset), errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def fetch(url: str, attempts: int = 3, timeout: int = 30) -> tuple[str, dict[str, str]]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache", "Pragma": "no-cache",
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                headers = {key.lower(): value for key, value in response.headers.items()}
                return decode_body(body, headers.get("content-type", "")), headers
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last_error}")


def normalize_html(document: str) -> str:
    document = re.sub(r"<!--.*?-->", " ", document, flags=re.S)
    document = re.sub(r"<(script|style)\b.*?</\1>", " ", document, flags=re.I | re.S)
    # The CMS access counter changes on every cache refresh and is not school content.
    document = re.sub(r"<div\b[^>]*class=['\"][^'\"]*\bstatistics\b[^'\"]*['\"][^>]*>.*?</div>", " ", document, flags=re.I | re.S)
    document = re.sub(r"<span\b[^>]*class=['\"][^'\"]*\baccesscount\b[^'\"]*['\"][^>]*>.*?</span>", " ", document, flags=re.I | re.S)
    document = re.sub(r"\bid=['\"]page_[0-9a-f]+['\"]", "", document, flags=re.I)
    document = re.sub(r"[?&](?:_monitor_ts|t)=\d+", "", document)
    return re.sub(r"\s+", " ", document).strip()


def discover_targets(root_html: str, root_url: str) -> tuple[str | None, str | None]:
    rss_match = re.search(r"<link\b[^>]*type=['\"]application/rss\+xml['\"][^>]*href=['\"]([^'\"]+)", root_html, re.I)
    if not rss_match:
        rss_match = re.search(r"https://cms\.nerima-tky\.ed\.jp/weblog/rss2\.php\?id=\d+", root_html, re.I)
    frame_match = re.search(r"<frame\b[^>]*src=['\"]([^'\"]+)", root_html, re.I)
    rss_value = rss_match.group(1) if rss_match and rss_match.lastindex else (rss_match.group(0) if rss_match else None)
    rss_url = urllib.parse.urljoin(root_url, rss_value) if rss_value else None
    cms_url = urllib.parse.urljoin(root_url, frame_match.group(1)) if frame_match else None
    return rss_url, cms_url


def parse_rss(rss_text: str) -> tuple[list[dict[str, str]], dict[str, str] | None]:
    root = ET.fromstring(rss_text.lstrip("\ufeff\x00 \r\n\t"))
    items: list[dict[str, str]] = []
    for element in root.findall("./channel/item"):
        def value(name: str) -> str:
            return (element.findtext(name) or "").strip()
        items.append({
            "guid": value("guid"), "title": html.unescape(value("title")),
            "link": html.unescape(value("link")), "publishedAt": value("pubDate"),
            "description": normalize_html(value("description")),
        })
    latest = {key: items[0][key] for key in ("title", "link", "publishedAt")} if items else None
    return items, latest


def digest(parts: dict[str, object]) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def monitor_school(school: tuple[int, str, str], previous: dict, checked_at: str) -> dict:
    school_id, name, slug = school
    legacy_url = f"https://www.nerima-tky.ed.jp/{slug}/"
    cms_id = CMS_ID_OVERRIDES.get(school_id, 200 + school_id if school_id <= 17 else 201 + school_id)
    fallback_cms_url = f"https://cms.nerima-tky.ed.jp/swas/index.php?id={cms_id}"
    fallback_rss_url = f"https://cms.nerima-tky.ed.jp/weblog/rss2.php?id={cms_id}"
    result = {
        "id": school_id, "name": name, "url": fallback_cms_url, "checkedAt": checked_at,
        "currentHash": previous.get("currentHash"), "lastChangedAt": previous.get("lastChangedAt"),
        "latest": previous.get("latest"), "sources": previous.get("sources", {}), "warning": None, "error": None,
    }
    try:
        root_html = ""
        root_headers: dict[str, str] = {}
        warning = None
        try:
            root_html, root_headers = fetch(legacy_url)
            discovered_rss, discovered_cms = discover_targets(root_html, legacy_url)
            rss_url = discovered_rss or fallback_rss_url
            cms_url = discovered_cms or fallback_cms_url
        except RuntimeError as error:
            rss_url, cms_url = fallback_rss_url, fallback_cms_url
            warning = f"旧公開URLは利用できないためCMSを直接監視: {error}"
        cms_html = ""
        rss_items: list[dict[str, str]] = []
        latest = None
        component_errors = []
        if cms_url:
            try:
                cms_html, _ = fetch(cms_url)
            except RuntimeError as error:
                component_errors.append(str(error))
        if rss_url:
            try:
                rss_text, _ = fetch(rss_url)
                rss_items, latest = parse_rss(rss_text)
            except (RuntimeError, ET.ParseError) as error:
                component_errors.append(str(error))
        if not cms_html and not rss_items:
            raise RuntimeError(" / ".join(component_errors) or "CMS内容を取得できません")
        source_hashes = {
            "legacyHomepage": digest({"html": normalize_html(root_html)}),
            "cms": digest({"html": normalize_html(cms_html)}),
            "rss": digest({"items": rss_items}),
        }
        content_hash = digest(source_hashes)
        previous_hash = previous.get("currentHash")
        result.update({
            "url": cms_url,
            "currentHash": content_hash,
            "lastChangedAt": checked_at if previous_hash and previous_hash != content_hash else previous.get("lastChangedAt"),
            "latest": latest,
            "sources": {"legacyHomepage": legacy_url, "homepage": cms_url, "rss": rss_url, "legacyHomepageLastModified": root_headers.get("last-modified"), "hashes": source_hashes},
            "warning": warning,
            "error": " / ".join(component_errors) if component_errors else None,
        })
    except Exception as error:
        result["error"] = str(error)
    return result


def load_previous(path: Path) -> dict[int, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {int(item["id"]): item for item in data.get("schools", [])}
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return {}


def run(output: Path, workers: int = 5) -> dict:
    checked_at = iso_now()
    previous = load_previous(output)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(monitor_school, school, previous.get(school[0], {}), checked_at) for school in SCHOOLS]
        schools = [future.result() for future in futures]
    schools.sort(key=lambda item: item["id"])
    result = {
        "schemaVersion": 2, "checkedAt": checked_at, "schoolCount": len(schools),
        "successCount": sum(not item["error"] for item in schools),
        "errorCount": sum(bool(item["error"]) for item in schools), "schools": schools,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    result = run(args.output, args.workers)
    print(f"checked={result['schoolCount']} success={result['successCount']} errors={result['errorCount']}")
    return 0 if result["successCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
