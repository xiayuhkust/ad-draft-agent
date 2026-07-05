"""模拟草稿 UI 两个文本框的数据：随机抽候选技能实测。

场景：我是 10 人之一，已有一个英雄身板（+已选技能），轮到我选。
对池子里每个候选技能图标，下方显示：
  [文本框1] 技能自身胜率
  [文本框2] 与我已选条目的最高配对胜率（如有数据）
"""

import random
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from addraft import Snapshot


def pct(x):
    return f"{x * 100:.1f}%"


def main():
    snap = Snapshot.load()
    pool = snap.draftable()
    bodies = [a for a in pool if a.is_hero_body]
    skills = [a for a in pool if not a.is_hero_body]

    my_body = random.choice(bodies)
    my_picked_skill = random.choice(skills)
    my_ids = [my_body.id, my_picked_skill.id]
    candidates = random.sample([s for s in skills if s.id not in my_ids], 2)

    print(f"[快照 {snap.version}]")
    print(f"我的身板: {my_body.english_name}   已选: {my_picked_skill.english_name} "
          f"(胜率 {pct(my_picked_skill.stats.winrate)})")
    print()

    for a in candidates:
        best = snap.best_pair_with(a.id, my_ids)
        print(f"候选技能: {a.english_name}  ({'大招' if a.is_ultimate else '普通'})")
        print(f"  ┌─[文本框1] 自身胜率: {pct(a.stats.winrate)}  ({a.stats.num_picks} 场)")
        if best:
            other, p = best
            print(f"  └─[文本框2] 最高配对: {pct(p.winrate)}  与「{other.english_name}」({p.num_picks} 场)")
        else:
            print(f"  └─[文本框2] 最高配对: —  (与我已选条目无足量配对数据)")
        # 参考：该技能全局最佳搭档（不限于我已选的）
        top = snap.synergies(a.id)[:3]
        if top:
            refs = ", ".join(f"{o.english_name} {pct(p.winrate)}" for o, p in top)
            print(f"     (参考·全局最佳搭档: {refs})")
        print()


if __name__ == "__main__":
    main()
