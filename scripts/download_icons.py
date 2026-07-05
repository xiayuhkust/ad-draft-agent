"""把全部进池条目的图标从 Valve CDN 下载到 web/img/，供前端本地引用。

- 技能 → web/img/abilities/<shortName>.png
- 英雄身板/头像 → web/img/heroes/<shortName>.png
- 已存在的跳过（增量），8 线程并发，失败列表最后汇总
"""

import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from addraft import Snapshot

CDN = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react"
IMG_DIR = Path(__file__).resolve().parent.parent / "web" / "img"


def fetch(job):
    url, dest = job
    if dest.exists():
        return None
    # windrun 的部分 shortName 带 "_ad" 后缀（AD 特化变体），CDN 上是无后缀原名
    candidates = [url]
    if url.endswith("_ad.png"):
        candidates.append(url[:-7] + ".png")
    last_err = None
    for u in candidates:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                dest.write_bytes(resp.read())
            return None
        except Exception as e:
            last_err = str(e)
    return (url, last_err)


def main():
    snap = Snapshot.load()
    (IMG_DIR / "abilities").mkdir(parents=True, exist_ok=True)
    (IMG_DIR / "heroes").mkdir(parents=True, exist_ok=True)

    jobs = []
    for a in snap.draftable():
        folder = "heroes" if a.is_hero_body else "abilities"
        jobs.append((f"{CDN}/{folder}/{a.short_name}.png",
                     IMG_DIR / folder / f"{a.short_name}.png"))

    with ThreadPoolExecutor(max_workers=8) as ex:
        failures = [r for r in ex.map(fetch, jobs) if r]

    total_files = sum(1 for _ in IMG_DIR.rglob("*.png"))
    total_mb = sum(f.stat().st_size for f in IMG_DIR.rglob("*.png")) / 1024 / 1024
    print(f"完成：本地图标 {total_files} 个，共 {total_mb:.1f} MB，失败 {len(failures)}")
    for url, err in failures[:10]:
        print("  失败:", url, err)


if __name__ == "__main__":
    main()
