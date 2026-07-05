"""windrun.io 数据快照抓取器。

设计原则：对源站压力最小化 ——
- 每次运行对每个端点只发 1 个请求（全量 6 个请求），请求间隔 1.5 秒
- 内容没变化时不发布新快照（用内容哈希判断）
- 客户端永远从发布的快照读数据，不直连 windrun

用法：
    python scripts/fetch_snapshot.py            # 抓取并在有变化时写入新快照
    python scripts/fetch_snapshot.py --force    # 忽略哈希对比，强制写入
"""

import argparse
import gzip
import hashlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://api.windrun.io/api/v2"
# Cloudflare 会拦截非浏览器 UA，必须带浏览器 UA
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
REQUEST_INTERVAL_SECONDS = 1.5

# 端点名 -> 快照文件名
ENDPOINTS = {
    "static/abilities": "static_abilities.json",
    "static/heroes": "static_heroes.json",
    "abilities": "abilities.json",
    "ability-pairs": "ability_pairs.json",
    "heroes": "heroes.json",
    "ability-high-skill": "ability_high_skill.json",
}

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "snapshot"
MANIFEST_PATH = SNAPSHOT_DIR / "manifest.json"


def fetch_endpoint(endpoint: str) -> dict:
    url = f"{API_BASE}/{endpoint}"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def content_hash(payloads: dict[str, dict]) -> str:
    canonical = json.dumps(payloads, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def extract_patch(payloads: dict[str, dict]) -> str:
    for data in payloads.values():
        patches = data.get("data", {}).get("patches") if isinstance(data.get("data"), dict) else None
        if patches and patches.get("overall"):
            return patches["overall"][0]
    return "unknown"


def load_previous_hash() -> str | None:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("contentHash")
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="内容未变化也强制写入快照")
    args = parser.parse_args()

    payloads: dict[str, dict] = {}
    for i, endpoint in enumerate(ENDPOINTS):
        if i > 0:
            time.sleep(REQUEST_INTERVAL_SECONDS)
        print(f"fetching {endpoint} ...", flush=True)
        payloads[endpoint] = fetch_endpoint(endpoint)

    new_hash = content_hash(payloads)
    if not args.force and new_hash == load_previous_hash():
        print(f"内容无变化（hash={new_hash}），跳过发布。")
        return 0

    patch = extract_patch(payloads)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot_version = f"{patch}-{generated_at[:10]}"

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    files = {}
    for endpoint, filename in ENDPOINTS.items():
        path = SNAPSHOT_DIR / filename
        text = json.dumps(payloads[endpoint], ensure_ascii=False)
        path.write_text(text, encoding="utf-8")
        files[filename] = {
            "endpoint": endpoint,
            "bytes": len(text.encode("utf-8")),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        }

    manifest = {
        "snapshotVersion": snapshot_version,
        "patch": patch,
        "generatedAt": generated_at,
        "contentHash": new_hash,
        "source": "https://windrun.io (unofficial API, fetched at most once per run)",
        "files": files,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    total_kb = sum(f["bytes"] for f in files.values()) / 1024
    print(f"已发布快照 {snapshot_version}（patch {patch}，共 {total_kb:.0f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
