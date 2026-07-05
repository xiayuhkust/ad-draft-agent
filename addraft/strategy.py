"""AI 玩家选取策略。

v1 贪心：得分 = 自身强度 + 与已选条目的最佳配对增益，少量噪声防止 9 个 AI 千篇一律。
数据缺失时回退到 0（等于"中性"），不会崩。
"""

from __future__ import annotations

import random

from .draft import DraftState, PlayerDraft
from .snapshot import Ability

BASELINE = 0.5          # 胜率基准线
SYNERGY_WEIGHT = 0.8    # 配对增益权重
NOISE = 0.01            # 决策噪声（标准差）


def score_pick(state: DraftState, player: PlayerDraft, a: Ability) -> float:
    base = (a.stats.winrate - BASELINE) if a.stats else 0.0
    synergy = 0.0
    if player.pick_ids:
        best = state.snapshot.best_pair_with(a.id, player.pick_ids)
        if best is not None:
            synergy = (best[1].winrate - BASELINE) * SYNERGY_WEIGHT
    return base + synergy


def greedy_pick(state: DraftState, player: PlayerDraft, rng: random.Random) -> Ability:
    legal = state.legal_picks(player)
    return max(legal, key=lambda a: score_pick(state, player, a) + rng.gauss(0, NOISE))
