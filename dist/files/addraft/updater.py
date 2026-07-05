"""玩家端更新器：按清单增量同步，数据热更、代码提示重启。

启用方式：根目录放 update_url.txt，内容一行 = dist 目录的 URL
（http(s):// 或 file:// 均可；没有该文件 = 更新关闭，纯本地运行）。

- 数据文件（web/data/、web/img/）：直接替换，立即生效（页面刷新即用新数据）
- 代码文件：替换后需重启 server/盒子 生效（只提示，不强杀）
- 任何失败都不影响本地运行（网络问题静默跳过）
"""

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL_FILE = ROOT / "update_url.txt"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ad-draft-agent-updater"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def check_and_update() -> dict:
    """返回 {enabled, updated:[...], codeChanged:bool, appVersion, dataVersion} 。"""
    if not URL_FILE.exists():
        return {"enabled": False}
    base = URL_FILE.read_text(encoding="utf-8").strip().rstrip("/")
    if not base:
        return {"enabled": False}

    manifest = json.loads(_fetch(f"{base}/manifest.json"))
    data_prefixes = tuple(manifest.get("dataPrefixes", ()))
    updated, code_changed = [], False
    for rel, remote_hash in manifest["files"].items():
        local = ROOT / rel
        if local.exists() and _sha(local) == remote_hash:
            continue
        data = _fetch(f"{base}/files/{rel}")
        if hashlib.sha256(data).hexdigest()[:16] != remote_hash:
            continue  # 传输损坏，跳过本文件，下次再试
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_suffix(local.suffix + ".new")
        tmp.write_bytes(data)
        tmp.replace(local)
        updated.append(rel)
        if not rel.startswith(data_prefixes):
            code_changed = True
    return {
        "enabled": True,
        "updated": updated,
        "codeChanged": code_changed,
        "appVersion": manifest.get("appVersion"),
        "dataVersion": manifest.get("dataVersion"),
    }
