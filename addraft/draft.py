"""草稿规则引擎：池生成、选取合法性、状态推进。

组成约束（用户定，2026-07-04）：
- 每名玩家最终 = 1 个英雄身板 + 4 个技能
- 选取顺序自由（身板可先可后）
- 不能拿第 2 个身板
- 大招规则可配置：标准 AD 为"恰好 1 个大招"(exactly_one)，也可放开(free)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from .snapshot import Ability, Snapshot

NUM_PLAYERS = 10
POOL_HEROES = 12
ABILITIES_PER_PLAYER = 4


class UltRule(str, Enum):
    EXACTLY_ONE = "exactly_one"  # 标准 AD：3 普通 + 1 大招
    FREE = "free"                # 不限制大招数量


@dataclass
class PlayerDraft:
    index: int
    body: Ability | None = None
    abilities: list[Ability] = field(default_factory=list)

    @property
    def picks(self) -> list[Ability]:
        return ([self.body] if self.body else []) + self.abilities

    @property
    def pick_ids(self) -> list[int]:
        return [a.id for a in self.picks]

    @property
    def is_complete(self) -> bool:
        return self.body is not None and len(self.abilities) == ABILITIES_PER_PLAYER

    def ult_count(self) -> int:
        return sum(1 for a in self.abilities if a.is_ultimate)


@dataclass
class DraftState:
    snapshot: Snapshot
    pool: dict[int, Ability]              # 仍可选的条目 id -> Ability
    players: list[PlayerDraft]
    pick_order: list[int]                 # 每一手轮到的玩家 index（默认蛇形）
    ult_rule: UltRule = UltRule.EXACTLY_ONE
    pick_no: int = 0                      # 已完成的选取数（全局手数）

    # ---------- 构造 ----------

    @classmethod
    def new_game(
        cls,
        snapshot: Snapshot,
        seed: int | None = None,
        ult_rule: UltRule = UltRule.EXACTLY_ONE,
    ) -> "DraftState":
        """随机 12 英雄开局：池 = 12 身板 + 它们的技能（需大招规则可满足）。"""
        rng = random.Random(seed)
        skills_by_hero: dict[int, list[Ability]] = {}
        for a in snapshot.draftable():
            if not a.is_hero_body and a.owner_hero_id:
                skills_by_hero.setdefault(a.owner_hero_id, []).append(a)
        eligible = [
            h for h, ss in skills_by_hero.items()
            if -h in snapshot.abilities
            and sum(1 for s in ss if s.is_ultimate) >= 1
            and sum(1 for s in ss if not s.is_ultimate) >= 3
        ]
        game_heroes = rng.sample(eligible, POOL_HEROES)

        pool: dict[int, Ability] = {}
        for h in game_heroes:
            pool[-h] = snapshot.abilities[-h]
            ults = [s for s in skills_by_hero[h] if s.is_ultimate]
            normals = [s for s in skills_by_hero[h] if not s.is_ultimate]
            for s in ults[:1] + normals[:3]:  # 每英雄进池：1 大招 + 3 普通
                pool[s.id] = s

        picks_per_player = 1 + ABILITIES_PER_PLAYER
        forward = list(range(NUM_PLAYERS))
        order = []
        for rnd in range(picks_per_player):
            order += forward if rnd % 2 == 0 else forward[::-1]  # 蛇形

        return cls(
            snapshot=snapshot,
            pool=pool,
            players=[PlayerDraft(i) for i in range(NUM_PLAYERS)],
            pick_order=order,
            ult_rule=ult_rule,
        )

    # ---------- 规则 ----------

    @property
    def current_player(self) -> PlayerDraft | None:
        if self.pick_no >= len(self.pick_order):
            return None
        return self.players[self.pick_order[self.pick_no]]

    def legal_picks(self, player: PlayerDraft) -> list[Ability]:
        """当前池中该玩家可合法选取的条目。"""
        remaining_ability_slots = ABILITIES_PER_PLAYER - len(player.abilities)
        legal = []
        for a in self.pool.values():
            if a.is_hero_body:
                if player.body is not None:
                    continue  # 不能拿第 2 个身板
            else:
                if remaining_ability_slots == 0:
                    continue
                if self.ult_rule == UltRule.EXACTLY_ONE:
                    if a.is_ultimate and player.ult_count() >= 1:
                        continue  # 已有大招
                    if (not a.is_ultimate
                            and player.ult_count() == 0
                            and remaining_ability_slots == 1):
                        continue  # 最后一个技能位必须留给大招
            legal.append(a)
        return legal

    def apply_pick(self, player: PlayerDraft, ability_id: int) -> Ability:
        a = self.pool.get(ability_id)
        if a is None:
            raise ValueError(f"条目 {ability_id} 不在池中（已被拿走或不存在）")
        if a.id not in {x.id for x in self.legal_picks(player)}:
            raise ValueError(f"玩家 {player.index} 选取 {a.english_name} 不合法")
        del self.pool[a.id]
        if a.is_hero_body:
            player.body = a
        else:
            player.abilities.append(a)
        self.pick_no += 1
        return a

    @property
    def is_complete(self) -> bool:
        return all(p.is_complete for p in self.players)
