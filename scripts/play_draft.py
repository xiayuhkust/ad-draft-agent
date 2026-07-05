"""可玩的草稿模拟器 CLI（v1）。

我是 10 人之一，其余 9 人由贪心 AI 扮演。
推荐引擎 = 开关（--no-assist 关闭，草稿中输入 a 切换）：
开启时每个候选条目后显示两个"文本框"——自身胜率 | 最高配对。

用法：
    python scripts/play_draft.py                # 随机座位，开助手
    python scripts/play_draft.py --seat 0 --seed 42
    python scripts/play_draft.py --auto         # 全 AI 自动跑一局（测试用）
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

from addraft import DraftState, Snapshot
from addraft.strategy import greedy_pick


def pct(x):
    return f"{x * 100:.1f}%"


def assist_boxes(state: DraftState, player, a) -> str:
    """两个文本框：[自身胜率] [最高配对]。★=与我已选的实测配对，○=池内潜在搭档。"""
    box1 = pct(a.stats.winrate) if a.stats else "  —  "
    best_mine = state.snapshot.best_pair_with(a.id, player.pick_ids) if player.pick_ids else None
    if best_mine:
        other, p = best_mine
        box2 = f"★{pct(p.winrate)} 配 {other.english_name}"
    else:
        in_pool = [
            (o, p) for o, p in state.snapshot.synergies(a.id, min_picks=200)
            if o.id in state.pool and o.id != a.id
        ]
        if in_pool:
            other, p = in_pool[0]
            box2 = f"○{pct(p.winrate)} 潜在搭档 {other.english_name}"
        else:
            box2 = "—"
    return f"{box1:>6} | {box2}"


def render_pool(state: DraftState, player, assist: bool):
    groups = [
        ("身板", [a for a in state.pool.values() if a.is_hero_body]),
        ("大招", [a for a in state.pool.values() if not a.is_hero_body and a.is_ultimate]),
        ("普通", [a for a in state.pool.values() if not a.is_hero_body and not a.is_ultimate]),
    ]
    legal_ids = {a.id for a in state.legal_picks(player)}
    for title, items in groups:
        if not items:
            continue
        print(f"  ── {title} ──")
        for a in sorted(items, key=lambda x: -(x.stats.winrate if x.stats else 0)):
            mark = "  " if a.id in legal_ids else "✗ "
            line = f"   {mark}[{a.id:>5}] {a.english_name:<28}"
            if assist:
                line += "  " + assist_boxes(state, player, a)
            print(line)


def show_build(p, label=""):
    body = p.body.english_name if p.body else "?"
    parts = [f"{a.english_name}{'(大)' if a.is_ultimate else ''}" for a in p.abilities]
    print(f"  {label}P{p.index} {body:<24} " + " / ".join(parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", type=int, default=None, help="我的座位 0-9（默认随机）")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--auto", action="store_true", help="全 AI 自动跑一局")
    ap.add_argument("--no-assist", action="store_true", help="关闭推荐显示")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    snap = Snapshot.load()
    state = DraftState.new_game(snap, seed=args.seed)
    my_seat = None if args.auto else (args.seat if args.seat is not None else rng.randrange(10))
    assist = not args.no_assist

    print(f"[快照 {snap.version}] 我的座位: {'—(全AI)' if my_seat is None else f'P{my_seat}'}"
          f"  规则: 1 身板 + 3 普通 + 1 大招")

    while not state.is_complete:
        player = state.current_player
        if player.index != my_seat:
            pick = greedy_pick(state, player, rng)
            state.apply_pick(player, pick.id)
            if my_seat is not None:
                print(f"  P{player.index} 选了 {pick.english_name}")
            continue

        print(f"\n━━ 第 {state.pick_no + 1}/50 手，轮到你 ━━")
        show_build(player, label="当前阵容: ")
        render_pool(state, player, assist)
        while True:
            raw = input("输入条目编号 (a=切换助手, q=退出): ").strip().lower()
            if raw == "q":
                return
            if raw == "a":
                assist = not assist
                print(f"  助手已{'开启' if assist else '关闭'}")
                render_pool(state, player, assist)
                continue
            try:
                state.apply_pick(player, int(raw))
                break
            except (ValueError, KeyError) as e:
                print(f"  无效: {e}")

    print("\n═══ 草稿结束 ═══")
    print("天辉 (P0-P4):")
    for p in state.players[:5]:
        show_build(p, label="→ " if p.index == my_seat else "  ")
    print("夜魇 (P5-P9):")
    for p in state.players[5:]:
        show_build(p, label="→ " if p.index == my_seat else "  ")


if __name__ == "__main__":
    main()
