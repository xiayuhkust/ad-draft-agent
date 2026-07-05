"""身板定位 v2：由大招区几何 + 棋盘透视模型反推 12 个身板格。

棋盘在游戏内是 3D 渲染：行越靠下，列距越大、图标越大（近大远小）。
做法：
  1. 标准区锚点行 → 每行栅格得到 (行深 cy, 列距 sp, 行中心 cx)
  2. 线性拟合 sp(cy) 与 center(cy) —— 棋盘透视模型
  3. 身板格 = 每行 中心 ± 3.5 × sp(cy)（技能 6 列外侧各一格）
  4. 只用英雄头像模板分类，输出 top-3 候选（供结构化指派用）
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from addraft import Snapshot
from scripts.detect_brackets import find_bracket_corners, imread_u, imwrite_u
from scripts.detect_slots import fit_rows, raster_row
from scripts.rectify_match import (ICON_TO_ZONE, load_templates, match, pick_quads,
                                   rectify, validate_quad)

TRUTH = {"Techies", "Silencer", "Marci", "Batrider", "Shadow Shaman", "Snapfire",
         "Magnus", "Keeper of the Light", "Juggernaut", "Pudge", "Warlock",
         "Legion Commander"}


def classify_top(warped, cx, cy, cell_px, templates, k=3):
    m = int(cell_px * 0.5)
    x0, y0 = int(cx - cell_px / 2 - m), int(cy - cell_px / 2 - m)
    x1, y1 = int(cx + cell_px / 2 + m), int(cy + cell_px / 2 + m)
    if x0 < 0 or y0 < 0 or x1 > warped.shape[1] or y1 > warped.shape[0]:
        return []
    crop = warped[y0:y1, x0:x1]
    scored = []
    for a, tpl in templates:
        t = cv2.resize(tpl, (cell_px, cell_px), interpolation=cv2.INTER_AREA)
        _, val, _, _ = cv2.minMaxLoc(cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED))
        scored.append((val, a))
    scored.sort(key=lambda t: -t[0])
    return scored[:k]


def main():
    img = imread_u(Path("input/real1.jpg"))
    snap = Snapshot.load()
    templates = load_templates(snap)
    t_hero = [(a, t) for a, t in templates if a.is_hero_body]

    quads = pick_quads(find_bracket_corners(img)[1], img.shape[1], img.shape[0])
    quad = next(q for q in quads if validate_quad(img, q, templates)[0] >= 6)
    warped, zw, zh, (ox, oy) = rectify(img, quad)
    icon = int(zw * ICON_TO_ZONE)

    scales = (int(icon * 0.85), icon, int(icon * 1.15))
    hits = match(warped, templates, scales)
    bx0, bx1 = ox - 0.45 * zw, ox + 1.45 * zw
    anchors = [h for h in hits
               if bx0 <= h["x"] + h["size"] / 2 <= bx1
               and oy + zh * 1.15 <= h["y"] + h["size"] / 2 <= oy + zh * 4.8]
    rows = fit_rows(anchors, icon)

    # 每行栅格 → (cy, 列距, 中心)；行内 ≥2 锚点才可信
    samples = []
    for r in rows:
        if len(r["hits"]) < 2:
            continue
        cs = sorted(h["x"] + h["size"] / 2 for h in r["hits"])
        steps = [d for d in np.diff(cs) if icon * 1.1 < d < icon * 2.2]
        if not steps:
            continue
        sp = float(np.median(steps))
        cols = raster_row(r, sp, bx0, bx1)
        if len(cols) < 6:
            continue
        samples.append((r["cy"], sp, float(np.mean(cols))))
    print("行样本 (cy, 列距, 中心):")
    for cy, sp, cx in samples:
        print(f"  cy={cy:.0f}  sp={sp:.1f}  center={cx:.0f}")

    cys = np.array([s[0] for s in samples])
    sp_fit = np.polyfit(cys, [s[1] for s in samples], 1)
    cx_fit = np.polyfit(cys, [s[2] for s in samples], 1)
    print(f"透视模型: sp(cy) = {sp_fit[0]:.4f}·cy + {sp_fit[1]:.1f}   "
          f"center(cy) = {cx_fit[0]:.4f}·cy + {cx_fit[1]:.1f}")

    # 标准区 6 行的行深：用锚点行 cy 聚合（应有 6 行）
    row_cys = sorted(s[0] for s in samples)
    print(f"可用行: {len(row_cys)}")

    vis = warped.copy()
    found = []
    for cy in row_cys:
        sp = np.polyval(sp_fit, cy)
        center = np.polyval(cx_fit, cy)
        cell = int(sp * 0.62)  # 身板格边长 ≈ 0.62 × 列距（与技能同比例）
        for side, cx in (("左", center - 3.5 * sp), ("右", center + 3.5 * sp)):
            top = classify_top(warped, cx, cy, cell, t_hero)
            if not top:
                continue
            best_v, best_a = top[0]
            name = best_a.english_name.replace("Hero: ", "")
            mark = "✓" if name in TRUTH else "✗"
            in_top3 = any(a.english_name.replace("Hero: ", "") in TRUTH for v, a in top)
            found.append((mark, in_top3))
            cands = ", ".join(f"{a.english_name.replace('Hero: ','')} {v:.2f}" for v, a in top)
            print(f"  {side} ({cx:.0f},{cy:.0f}) 格{cell}px  {mark} [{cands}]")
            color = (0, 255, 128) if mark == "✓" else (0, 128, 255)
            cv2.rectangle(vis, (int(cx - cell / 2), int(cy - cell / 2)),
                          (int(cx + cell / 2), int(cy + cell / 2)), color, 2)
            cv2.putText(vis, f"{name} {best_v:.2f}", (int(cx - cell / 2), int(cy - cell / 2) - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

    ok = sum(1 for m, _ in found if m == "✓")
    ok3 = sum(1 for _, t in found if t)
    print(f"\ntop-1 正确: {ok}/{len(found)}   真英雄在 top-3 内: {ok3}/{len(found)}")
    imwrite_u(Path("input/real1_bodies.jpg"), vis)
    print("可视化: input/real1_bodies.jpg")


if __name__ == "__main__":
    main()
