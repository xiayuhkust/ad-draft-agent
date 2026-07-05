"""结构化指派：三路证据（大招/小招/身板）联合推断 12 英雄池。

结构先验：
- 大招格 2×6 = 12 个，可由角标区几何直接生成（角标框对称包住大招网格）
- 标准区每行 [身板][6技能][身板]，行中心 = 角标区中心（共中心对称）
- 每个英雄：恰好 1 大招 + 3 小招 + 1 身板

英雄总分 = w_ult·大招证据 + Σtop3(小招证据) + w_body·身板证据
证据 = 对应模板在对应类别格子上的最高 NCC 分（减基线 0.45，负分记 0）
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from addraft import Snapshot
from scripts.detect_brackets import find_bracket_corners, imread_u
from scripts.detect_slots import fit_rows
from scripts.rectify_match import (ICON_TO_ZONE, load_templates, match, pick_quads,
                                   rectify, validate_quad)

BASE = 0.55          # 证据基线：48 格取最大的噪声地板约 0.55，低于此视为无证据
W_ULT, W_BODY = 1.5, 0.75
TRUTH = {"Techies", "Silencer", "Marci", "Batrider", "Shadow Shaman", "Snapfire",
         "Magnus", "Keeper of the Light", "Juggernaut", "Pudge", "Warlock",
         "Legion Commander"}


def cell_scores(warped, cx, cy, cell_px, templates):
    """一个格子对一组模板的全部分数 {ability_id: score}。"""
    m = int(cell_px * 0.5)
    x0, y0 = int(cx - cell_px / 2 - m), int(cy - cell_px / 2 - m)
    x1, y1 = int(cx + cell_px / 2 + m), int(cy + cell_px / 2 + m)
    if x0 < 0 or y0 < 0 or x1 > warped.shape[1] or y1 > warped.shape[0]:
        return {}
    crop = warped[y0:y1, x0:x1]
    out = {}
    for a, tpl in templates:
        t = cv2.resize(tpl, (cell_px, cell_px), interpolation=cv2.INTER_AREA)
        if crop.shape[0] <= cell_px or crop.shape[1] <= cell_px:
            continue
        _, v, _, _ = cv2.minMaxLoc(cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED))
        out[a.id] = v
    return out


def main():
    img = imread_u(Path(sys.argv[1] if len(sys.argv) > 1 else "input/real1.jpg"))
    snap = Snapshot.load()
    templates = load_templates(snap)
    t_ult = [(a, t) for a, t in templates if a.is_ultimate]
    t_std = [(a, t) for a, t in templates if not a.is_ultimate and not a.is_hero_body]
    t_hero = [(a, t) for a, t in templates if a.is_hero_body]

    quads = pick_quads(find_bracket_corners(img)[1], img.shape[1], img.shape[0])
    quad = next(q for q in quads if validate_quad(img, q, templates)[0] >= 6)
    warped, zw, zh, (ox, oy) = rectify(img, quad)
    icon = int(zw * ICON_TO_ZONE)
    center = ox + zw / 2

    # ---- 锚点（供行/列距估计）----
    scales = (int(icon * 0.85), icon, int(icon * 1.15))
    hits = match(warped, templates, scales)
    in_board = lambda h: (ox - 0.6 * zw <= h["x"] + h["size"] / 2 <= ox + 1.6 * zw)
    ult_anchors = [h for h in hits if in_board(h)
                   and oy - 0.1 * zh <= h["y"] + h["size"] / 2 <= oy + 1.1 * zh]
    std_anchors = [h for h in hits if in_board(h)
                   and oy + 1.1 * zh <= h["y"] + h["size"] / 2 <= oy + 4.8 * zh]

    # ---- 大招格：角标区几何直接生成 2×6 ----
    u_rows = fit_rows(ult_anchors, icon)
    u_cys = sorted(r["cy"] for r in u_rows if len(r["hits"]) >= 2)
    if len(u_cys) < 2:
        u_cys = [oy + 0.26 * zh, oy + 0.76 * zh]
    u_steps = [d for r in u_rows
               for d in np.diff(sorted(h["x"] + h["size"] / 2 for h in r["hits"]))
               if icon * 1.1 < d < icon * 2.2]
    sp_u = float(np.median(u_steps)) if u_steps else zw * 0.172
    ult_cells = [(center + (i - 2.5) * sp_u, cy) for cy in u_cys[:2] for i in range(6)]

    # ---- 标准区行 → 技能格 + 身板格（共中心对称）----
    s_rows = fit_rows(std_anchors, icon)
    good = []
    for r in s_rows:
        cs = sorted(h["x"] + h["size"] / 2 for h in r["hits"])
        steps = [d for d in np.diff(cs) if icon * 1.1 < d < icon * 2.2]
        if steps:
            good.append((r["cy"], float(np.median(steps))))
    # 透视模型：列距随行深线性变化（样本≥2 则拟合，否则常数）
    if len(good) >= 2:
        sp_fit = np.polyfit([g[0] for g in good], [g[1] for g in good], 1)
        sp_of = lambda cy: float(np.polyval(sp_fit, cy))
    else:
        sp_of = lambda cy: good[0][1] if good else icon * 1.6
    row_cys = sorted(r["cy"] for r in s_rows if len(r["hits"]) >= 1)
    # 行去重（近邻合并）后限 6 行
    merged = []
    for cy in row_cys:
        if merged and cy - merged[-1] < icon * 0.8:
            continue
        merged.append(cy)
    std_cells, body_cells = [], []
    for cy in merged[:8]:
        sp = sp_of(cy)
        for i in range(6):
            std_cells.append((center + (i - 2.5) * sp, cy, sp))
        body_cells.append((center - 3.5 * sp, cy, sp))
        body_cells.append((center + 3.5 * sp, cy, sp))
    print(f"格子: 大招 {len(ult_cells)}, 小招 {len(std_cells)}, 身板 {len(body_cells)}")

    # ---- 逐格打分 ----
    ult_sc = [cell_scores(warped, cx, cy, icon, t_ult) for cx, cy in ult_cells]
    std_sc = [cell_scores(warped, cx, cy, int(sp * 0.62), t_std) for cx, cy, sp in std_cells]
    body_sc = [cell_scores(warped, cx, cy, int(sp * 0.62), t_hero) for cx, cy, sp in body_cells]

    # ---- 锚点证据（滑窗命中，位置自由但真实性高）----
    anchor_ev = {}
    for h in hits:
        cx, cy = h["x"] + h["size"] / 2, h["y"] + h["size"] / 2
        if not (ox - 0.6 * zw <= cx <= ox + 1.6 * zw and oy - 0.1 * zh <= cy <= oy + 4.8 * zh):
            continue
        aid = h["a"].id
        anchor_ev[aid] = max(anchor_ev.get(aid, 0), h["score"])

    # ---- 英雄证据汇总：格子证据 ∪ 锚点证据 ----
    by_hero = {}
    for a, _ in templates:
        if a.is_hero_body or not a.owner_hero_id:
            continue
        by_hero.setdefault(a.owner_hero_id, {"ult": [], "std": []})[
            "ult" if a.is_ultimate else "std"].append(a.id)

    # 证据函数：锚点（滑窗 NMS 后 ≥0.72，干净）地板 0.70；
    # 格子（48 格取最大，噪声地板 ~0.62）打半折，防垃圾凑分
    def ability_ev(aid, cell_list):
        a_part = max(0.0, anchor_ev.get(aid, 0) - 0.70)
        c_part = max(0.0, (max((sc.get(aid, 0) for sc in cell_list), default=0) - 0.62) * 0.5)
        return max(a_part, c_part)

    ranked = []
    for hid, ab in by_hero.items():
        u = max((ability_ev(aid, ult_sc) for aid in ab["ult"]), default=0)
        s3 = sorted((ability_ev(aid, std_sc) for aid in ab["std"]), reverse=True)[:3]
        b = max(0.0, (max((sc.get(-hid, 0) for sc in body_sc), default=0) - 0.62) * 0.5)
        total = W_ULT * u + sum(s3) + W_BODY * b
        ranked.append((total, hid, u, sum(s3), b))
    ranked.sort(reverse=True)

    # ---- 大招优先规则：高置信大招格直接定池，剩余名额由融合分补齐 ----
    ULT_LOCK = 0.75
    locked = []
    for sc in ult_sc:
        if not sc:
            continue
        aid, v = max(sc.items(), key=lambda kv: kv[1])
        a = next(a for a, _ in templates if a.id == aid)
        if v >= ULT_LOCK and a.owner_hero_id and a.owner_hero_id not in locked:
            locked.append(a.owner_hero_id)
    pool = list(locked)
    for _, hid, _, _, _ in ranked:
        if len(pool) >= 12:
            break
        if hid not in pool:
            pool.append(hid)
    print(f"\n大招锁定 {len(locked)} 席 + 融合补 {12 - len(locked) if len(locked) < 12 else 0} 席")

    top12 = [snap.hero(h).english_name for h in pool[:12]]
    correct = sum(1 for n in top12 if n in TRUTH)
    print(f"\n结构化指派 top-12: {correct}/12 正确")
    for total, hid, u, s, b in ranked[:16]:
        name = snap.hero(hid).english_name
        mark = "✓" if name in TRUTH else "✗"
        print(f"  {mark} {total:.3f}  (大招{u:.2f} 小招{s:.2f} 身板{b:.2f})  {name}")
    missed = TRUTH - set(top12)
    if missed:
        print("漏掉:", missed)


if __name__ == "__main__":
    main()
