"""把快照瘦身导出为前端数据包 web/data/bundle.js。

只保留进池条目 + 必要字段 + 双方都进池的配对，并按英雄归组全部
可征召技能（ult/norm 变长，可为空——前端组池时从局外英雄补位）。

导出为 window.AD_BUNDLE = {...} 的 JS 文件（而非 JSON），
这样 index.html 双击用 file:// 打开也能加载，无需起服务器。
"""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from addraft import Snapshot

ATTRS_CACHE = Path(__file__).resolve().parent.parent / "data" / "hero_attrs.json"
ATTRS_URL = "https://raw.githubusercontent.com/odota/dotaconstants/master/build/heroes.json"


def load_hero_attrs() -> dict[int, str]:
    """英雄主属性 (str/agi/int/all)，来自 OpenDota dotaconstants，本地缓存只拉一次。"""
    if not ATTRS_CACHE.exists():
        req = urllib.request.Request(ATTRS_URL, headers={"User-Agent": "ad-draft-agent"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read())
        ATTRS_CACHE.write_text(
            json.dumps({k: v["primary_attr"] for k, v in raw.items()}, ensure_ascii=False),
            encoding="utf-8",
        )
    return {int(k): v for k, v in json.loads(ATTRS_CACHE.read_text(encoding="utf-8")).items()}


def main():
    snap = Snapshot.load()
    drafted = {a.id: a for a in snap.draftable()}

    entries = []
    for a in drafted.values():
        entries.append({
            "id": a.id,
            "n": a.english_name.replace("Hero: ", ""),
            "s": a.short_name,
            "u": bool(a.is_ultimate),
            "h": a.owner_hero_id,
            "wr": round(a.stats.winrate, 4),
            "np": a.stats.num_picks,
            "ap": round(a.stats.avg_pick_position, 1) if a.stats.avg_pick_position else None,
            "hs": round(a.high_skill_stats.winrate, 4) if a.high_skill_stats else None,
        })

    pairs = [
        [p.ability_id_one, p.ability_id_two, p.num_picks, round(p.winrate, 4)]
        for p in snap.pairs.values()
        if p.ability_id_one in drafted and p.ability_id_two in drafted
    ]

    heroes = []
    skills_by_hero = {}
    for a in drafted.values():
        if not a.is_hero_body and a.owner_hero_id:
            skills_by_hero.setdefault(a.owner_hero_id, []).append(a)
    attrs = load_hero_attrs()
    for h, ss in skills_by_hero.items():
        ults = [s.id for s in ss if s.is_ultimate]
        normals = [s.id for s in ss if not s.is_ultimate]
        if -h in drafted:
            heroes.append({"id": h, "body": -h, "ult": ults, "norm": normals,
                           "attr": attrs.get(h, "all")})

    bundle = {
        "version": snap.version,
        "patch": snap.patch,
        "entries": entries,
        "pairs": pairs,
        "heroes": heroes,
    }
    out = Path(__file__).resolve().parent.parent / "web" / "data" / "bundle.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "window.AD_BUNDLE = " + json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + ";"
    out.write_text(text, encoding="utf-8")
    print(f"已导出 {out}")
    print(f"  条目 {len(entries)}, 配对 {len(pairs)}, 可开局英雄 {len(heroes)}, "
          f"大小 {len(text.encode('utf-8'))/1024:.0f} KB")


if __name__ == "__main__":
    main()
