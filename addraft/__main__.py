"""命令行查询入口：python -m addraft <技能名关键词>"""

import sys

from .snapshot import Snapshot


def fmt_pct(x: float | None) -> str:
    return f"{x * 100:.1f}%" if x is not None else "—"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python -m addraft <技能名关键词>")
        return 1
    query = " ".join(sys.argv[1:])
    snap = Snapshot.load()
    print(f"[快照 {snap.version} | patch {snap.patch}]")

    hits = snap.find(query)
    if not hits:
        print(f"没找到匹配 '{query}' 的技能")
        return 1

    a = hits[0]
    others = ", ".join(h.english_name for h in hits[1:6])
    if others:
        print(f"(其他匹配: {others})\n")

    kind = "英雄身板" if a.is_hero_body else ("大招" if a.is_ultimate else "普通技能")
    print(f"{a.english_name}  [{kind}]  ({a.short_name})")
    if a.stats:
        s = a.stats
        print(f"  胜率 {fmt_pct(s.winrate)} | 场次 {s.num_picks} | "
              f"平均顺位 {s.avg_pick_position:.2f} | 登场率 {fmt_pct(s.pick_rate)}")
        if a.high_skill_stats:
            print(f"  高分段: 胜率 {fmt_pct(a.high_skill_stats.winrate)} | 场次 {a.high_skill_stats.num_picks}")
        if a.valuation is not None:
            print(f"  windrun 价值分: {a.valuation:+.4f}")
    else:
        print("  本 patch 无 AD 统计数据（未进池或过冷门）")
    print(f"  图标: {a.icon_url}")

    combos = snap.synergies(a.id)[:8]
    if combos:
        print("\n  最佳已知组合（按组合胜率）:")
        for other, p in combos:
            print(f"    {fmt_pct(p.winrate)}  x{p.num_picks:>5}  {other.english_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
