"""玩家端更新器：按清单增量同步，数据热更、代码提示重启。

启用方式：根目录放 update_url.txt，内容一行 = dist 目录的 URL
（http(s):// 或 file:// 均可；没有该文件 = 更新关闭，纯本地运行）。

- 数据文件（web/data/、web/img/）：直接替换，立即生效（页面刷新即用新数据）
- 代码文件：替换后需重启 server/盒子 生效（只提示，不强杀）
- 任何失败都不影响本地运行（网络问题静默跳过）
"""

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .paths import EXE_DIR, IS_FROZEN, ROOT

URL_FILE = EXE_DIR / "update_url.txt"


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

    # CDN（CloudBase/jsdelivr）对静态文件缓存极久：清单加当前时间戳、
    # 文件加发布时间戳作查询串，保证每次发布后拉到的都是新对象
    manifest = json.loads(_fetch(f"{base}/manifest.json?t={int(time.time())}"))
    stamp = urllib.parse.quote(str(manifest.get("publishedAt", "")))
    data_prefixes = tuple(manifest.get("dataPrefixes", ()))
    updated, code_changed = [], False
    for rel, remote_hash in manifest["files"].items():
        is_data = rel.startswith(data_prefixes)
        if IS_FROZEN and not is_data:
            continue  # exe 里代码已编译，替换 .py 无效；出新版走安装包
        local = ROOT / rel
        if local.exists() and _sha(local) == remote_hash:
            continue
        data = _fetch(f"{base}/files/{rel}?v={stamp}")
        if hashlib.sha256(data).hexdigest()[:16] != remote_hash:
            continue  # 传输损坏，跳过本文件，下次再试
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_suffix(local.suffix + ".new")
        tmp.write_bytes(data)
        tmp.replace(local)
        updated.append(rel)
        if not rel.startswith(data_prefixes):
            code_changed = True
    local_app = (ROOT / "VERSION").read_text(encoding="utf-8").strip() \
        if (ROOT / "VERSION").exists() else "?"
    return {
        "enabled": True,
        "updated": updated,
        "codeChanged": code_changed,
        "appVersion": manifest.get("appVersion"),
        "dataVersion": manifest.get("dataVersion"),
        # 冻结版代码不热更：远端 app 版本更高时提示下载新安装包
        "newInstaller": IS_FROZEN and manifest.get("appVersion") != local_app,
        "installerUrl": manifest.get("installerUrl"),
        "localVersion": local_app,
    }
