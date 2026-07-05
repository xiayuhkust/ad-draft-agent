"""发布端：打包一次可分发的更新（dist/）。

产出：
    dist/manifest.json   版本清单（appVersion + dataVersion + 全文件哈希）
    dist/files/...       按仓库相对路径存放的发布文件

把 dist/ 整个同步到你的静态托管（自有服务器 / GitHub 仓库均可），
玩家端 updater 按清单增量拉取。

发布集 = 代码 + 页面 + 数据包 + 图标（图标靠哈希增量，出新英雄才有下载量）。
"""

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

INCLUDE = [
    "VERSION",
    "server.py",
    "addraft/__init__.py",
    "addraft/snapshot.py",
    "addraft/draft.py",
    "addraft/strategy.py",
    "addraft/vision.py",
    "addraft/updater.py",
    "plugin/hotkey_capture.py",
    "plugin/overlay.py",
    "web/index.html",
    "web/overlay.html",
    "web/data/bundle.js",
]
INCLUDE_DIRS = ["web/img"]  # 图标：全部列入清单，哈希不变不下载

# "热更"路径前缀（无需重启/无需新安装包）：整个 web/ ——
# 页面是 webview 加载的内容而非编译进 exe 的代码，UI 修复可直达安装版用户
DATA_PREFIXES = ("web/",)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main():
    app_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    bundle = (ROOT / "web/data/bundle.js").read_text(encoding="utf-8")
    data_version = json.loads(bundle.split("=", 1)[1].rstrip(";"))["version"]

    paths = [Path(p) for p in INCLUDE]
    for d in INCLUDE_DIRS:
        paths += [p.relative_to(ROOT) for p in (ROOT / d).rglob("*") if p.is_file()]

    if DIST.exists():
        shutil.rmtree(DIST)
    files = {}
    for rel in paths:
        src = ROOT / rel
        if not src.exists():
            print(f"跳过缺失文件: {rel}")
            continue
        key = rel.as_posix()
        files[key] = sha(src)
        dst = DIST / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    manifest = {
        "appVersion": app_version,
        "dataVersion": data_version,
        "publishedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dataPrefixes": list(DATA_PREFIXES),
        "files": files,
    }
    (DIST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    total_mb = sum((DIST / "files" / k).stat().st_size for k in files) / 1024 / 1024
    print(f"发布就绪: app {app_version} / data {data_version} / "
          f"{len(files)} 个文件 {total_mb:.1f} MB → {DIST}")
    print("下一步：把 dist/ 同步到你的静态托管，玩家端 update_url.txt 指向该地址")


if __name__ == "__main__":
    main()
