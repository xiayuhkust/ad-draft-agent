"""快照数据查询层。

ID 约定（windrun 数据自身的约定，三类文件一致）：
- 正数 id：真实技能（Valve ability id）
- 负数 id：英雄身板，abs(id) = 英雄 id（AD 草稿里身板也是可选项）

用法：
    from addraft import Snapshot
    snap = Snapshot.load()
    a = snap.find("mana break")[0]
    snap.synergies(a.id)[:5]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshot"
CDN_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react"


@dataclass(frozen=True)
class Stats:
    num_picks: int
    wins: int
    winrate: float
    pick_rate: float | None = None
    avg_pick_position: float | None = None
    pick_pos_std_dev: float | None = None


@dataclass(frozen=True)
class Hero:
    id: int
    english_name: str
    short_name: str
    stats: Stats | None = None

    @property
    def icon_url(self) -> str:
        return f"{CDN_BASE}/heroes/{self.short_name}.png"


@dataclass(frozen=True)
class Ability:
    id: int  # 负数 = 英雄身板
    english_name: str
    short_name: str
    tooltip: str | None
    owner_hero_id: int | None
    is_ultimate: bool | None
    has_scepter: bool | None
    has_shard: bool | None
    stats: Stats | None = None
    high_skill_stats: Stats | None = None
    valuation: float | None = None
    high_skill_valuation: float | None = None

    @property
    def is_hero_body(self) -> bool:
        return self.id < 0

    @property
    def icon_url(self) -> str:
        folder = "heroes" if self.is_hero_body else "abilities"
        return f"{CDN_BASE}/{folder}/{self.short_name}.png"


@dataclass(frozen=True)
class PairStats:
    ability_id_one: int
    ability_id_two: int
    num_picks: int
    wins: int
    winrate: float


def _stats_from(raw: dict) -> Stats:
    return Stats(
        num_picks=raw["numPicks"],
        wins=raw["wins"],
        winrate=raw["winrate"],
        pick_rate=raw.get("pickRate"),
        avg_pick_position=raw.get("avgPickPosition"),
        pick_pos_std_dev=raw.get("pickPosStdDev"),
    )


def _pair_key(id_one: int, id_two: int) -> tuple[int, int]:
    return (id_one, id_two) if id_one <= id_two else (id_two, id_one)


@dataclass
class Snapshot:
    patch: str
    version: str
    abilities: dict[int, Ability]          # id -> Ability（含英雄身板）
    heroes: dict[int, Hero]                # heroId(正数) -> Hero
    pairs: dict[tuple[int, int], PairStats]
    _by_ability: dict[int, list[PairStats]] = field(default_factory=dict)

    # ---------- 加载 ----------

    @classmethod
    def load(cls, snapshot_dir: Path | str = DEFAULT_SNAPSHOT_DIR) -> "Snapshot":
        d = Path(snapshot_dir)
        read = lambda name: json.loads((d / name).read_text(encoding="utf-8"))["data"]
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))

        static_abilities = read("static_abilities.json")
        static_heroes = read("static_heroes.json")
        ability_data = read("abilities.json")
        high_skill = read("ability_high_skill.json")["highSkillData"]
        hero_data = read("heroes.json")
        pair_data = read("ability_pairs.json")

        patch = ability_data["patches"]["overall"][0]

        stats_by_id = {s["abilityId"]: _stats_from(s) for s in ability_data["abilityStats"]}
        hs_stats_by_id = {s["abilityId"]: _stats_from(s) for s in high_skill["abilityStats"]}
        valuations = {int(k): v for k, v in ability_data["abilityValuations"].items()}
        hs_valuations = {int(k): v for k, v in high_skill["abilityValuations"].items()}

        abilities: dict[int, Ability] = {}
        for raw in static_abilities:
            aid = raw.get("valveId")
            if aid is None:
                continue
            abilities[aid] = Ability(
                id=aid,
                english_name=raw.get("englishName") or raw["shortName"],
                short_name=raw["shortName"],
                tooltip=raw.get("tooltip"),
                owner_hero_id=raw.get("ownerHeroId"),
                is_ultimate=raw.get("isUltimate"),
                has_scepter=raw.get("hasScepter"),
                has_shard=raw.get("hasShard"),
                stats=stats_by_id.get(aid),
                high_skill_stats=hs_stats_by_id.get(aid),
                valuation=valuations.get(aid),
                high_skill_valuation=hs_valuations.get(aid),
            )

        heroes: dict[int, Hero] = {}
        for hid_str, raw in static_heroes.items():
            hid = int(hid_str)
            patch_stats = hero_data["heroStats"].get(hid_str, {}).get(patch)
            heroes[hid] = Hero(
                id=hid,
                english_name=raw["englishName"],
                short_name=raw["shortName"],
                stats=Stats(
                    num_picks=patch_stats["numGames"],
                    wins=patch_stats["wins"],
                    winrate=patch_stats["winrate"],
                ) if patch_stats else None,
            )

        pairs: dict[tuple[int, int], PairStats] = {}
        by_ability: dict[int, list[PairStats]] = {}
        for raw in pair_data["abilityPairs"]:
            p = PairStats(
                ability_id_one=raw["abilityIdOne"],
                ability_id_two=raw["abilityIdTwo"],
                num_picks=raw["numPicks"],
                wins=raw["wins"],
                winrate=raw["winrate"],
            )
            pairs[_pair_key(p.ability_id_one, p.ability_id_two)] = p
            by_ability.setdefault(p.ability_id_one, []).append(p)
            by_ability.setdefault(p.ability_id_two, []).append(p)

        return cls(
            patch=patch,
            version=manifest["snapshotVersion"],
            abilities=abilities,
            heroes=heroes,
            pairs=pairs,
            _by_ability=by_ability,
        )

    # ---------- 查询 ----------

    def ability(self, ability_id: int) -> Ability | None:
        return self.abilities.get(ability_id)

    def hero(self, hero_id: int) -> Hero | None:
        return self.heroes.get(hero_id)

    def find(self, query: str) -> list[Ability]:
        """按英文名 / shortName 子串搜索（不区分大小写），带统计的排前面。"""
        q = query.lower().strip()
        hits = [
            a for a in self.abilities.values()
            if q in a.english_name.lower() or q in a.short_name.lower()
        ]
        return sorted(hits, key=lambda a: (a.stats is None, -(a.stats.num_picks if a.stats else 0)))

    def pair(self, id_one: int, id_two: int) -> PairStats | None:
        return self.pairs.get(_pair_key(id_one, id_two))

    def synergies(self, ability_id: int, min_picks: int = 200) -> list[tuple[Ability, PairStats]]:
        """某技能的已知组合，按组合胜率降序。只含 windrun 头部 7500 对，缺失≠不强。"""
        out = []
        for p in self._by_ability.get(ability_id, []):
            other_id = p.ability_id_two if p.ability_id_one == ability_id else p.ability_id_one
            other = self.abilities.get(other_id)
            if other is not None and p.num_picks >= min_picks:
                out.append((other, p))
        return sorted(out, key=lambda t: -t[1].winrate)

    def draftable(self) -> list[Ability]:
        """本 patch 实际进过 AD 池的条目（有统计数据），含英雄身板。"""
        return [a for a in self.abilities.values() if a.stats is not None]

    def best_pair_with(
        self, candidate_id: int, picked_ids: list[int], min_picks: int = 200
    ) -> tuple[Ability, PairStats] | None:
        """候选技能与"我已选条目"(身板+技能)的最佳配对；无数据返回 None。

        对应草稿 UI 里技能图标下方的第二个文本框。
        """
        best: tuple[Ability, PairStats] | None = None
        for pid in picked_ids:
            p = self.pair(candidate_id, pid)
            if p is None or p.num_picks < min_picks:
                continue
            if best is None or p.winrate > best[1].winrate:
                other = self.abilities[pid]
                best = (other, p)
        return best
