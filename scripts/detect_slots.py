"""槽位网格拟合 + 补格分类（JS 版识别的最终算法原型 v2）。

掩码分割在照片上不可靠（托盘反光/弹幕会把图标粘成一片）。
改用两段式：
  1. 粗匹配（滑窗）得到锚点 —— 每个命中都自带精确位置
  2. 锚点聚类成行 → 每行拟合"等距 6 格"栅格 → 空缺格子低阈值补分类
定位已知时分类阈值可放宽到 0.55，把粗匹配漏掉的暗淡/遮挡图标捞回来。
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from addraft import Snapshot
from scripts.detect_brackets import find_bracket_corners, imread_u, imwrite_u
from scripts.rectify_match import (ICON_TO_ZONE, load_templates, match, pick_quads,
                                   rectify, validate_quad, vote)

MIN_CLS_SCORE = 0.55
GRID_COLS = 6


def fit_rows(anchors, icon_px):
    """锚点按 y 聚成行。"""
    rows = []
    for h in sorted(anchors, key=lambda h: h["y"]):
        cy = h["y"] + h["size"] / 2
        if rows and cy - rows[-1]["cy"] < icon_px * 0.55:
            rows[-1]["hits"].append(h)
            rows[-1]["cy"] = float(np.mean([x["y"] + x["size"] / 2 for x in rows[-1]["hits"]]))
        else:
            rows.append({"cy": cy, "hits": [h]})
    return rows


def raster_row(row, spacing, x_min, x_max):
    """由行内锚点相位生成等距 6 格的列中心。"""
    centers = sorted(h["x"] + h["size"] / 2 for h in row["hits"])
    # 相位：所有锚点对 spacing 取模的圆均值
    phases = [c % spacing for c in centers]
    phase = float(np.median(phases))
    cols = []
    c = x_min + ((phase - x_min) % spacing)
    while c <= x_max:
        cols.append(c)
        c += spacing
    # 只保留 6 格窗口：选覆盖锚点最多且居中的连续 6 格
    if len(cols) <= GRID_COLS:
        return cols
    best, best_score = cols[:GRID_COLS], -1
    for i in range(len(cols) - GRID_COLS + 1):
        win = cols[i:i + GRID_COLS]
        covered = sum(1 for c0 in centers if any(abs(c0 - w) < spacing * 0.35 for w in win))
        mid_penalty = abs((win[0] + win[-1]) / 2 - (x_min + x_max) / 2) / (x_max - x_min)
        score = covered - mid_penalty
        if score > best_score:
            best_score, best = score, win
    return best


def classify_cell(warped, cx, cy, icon_px, templates):
    m = int(icon_px * 0.45)
    x0, y0 = int(cx - icon_px / 2 - m), int(cy - icon_px / 2 - m)
    x1, y1 = int(cx + icon_px / 2 + m), int(cy + icon_px / 2 + m)
    if x0 < 0 or y0 < 0 or x1 > warped.shape[1] or y1 > warped.shape[0]:
        return None
    crop = warped[y0:y1, x0:x1]
    best = None
    for a, tpl in templates:
        t = cv2.resize(tpl, (icon_px, icon_px), interpolation=cv2.INTER_AREA)
        _, val, _, _ = cv2.minMaxLoc(cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED))
        if best is None or val > best[1]:
            best = (a, val)
    return best


def main():
    img_path = Path(sys.argv[1])
    img = imread_u(img_path)
    snap = Snapshot.load()
    templates = load_templates(snap)

    quads = pick_quads(find_bracket_corners(img)[1], img.shape[1], img.shape[0])
    quad = None
    for q in quads:
        count, _ = validate_quad(img, q, templates)
        if count >= 6:
            quad = q
            break
    assert quad, "角标未定位"
    warped, zw, zh, (ox, oy) = rectify(img, quad)
    icon_px = int(zw * ICON_TO_ZONE)
    print(f"{img_path.name}: 角标区 ({ox:.0f},{oy:.0f}) {zw:.0f}x{zh:.0f}, 图标 ~{icon_px}px")

    # 1) 粗匹配锚点（板区内）
    scales = (int(icon_px * 0.85), icon_px, int(icon_px * 1.15))
    hits = match(warped, templates, scales)
    bx0, bx1 = ox - 0.45 * zw, ox + 1.45 * zw
    by0, by1 = oy - 0.15 * zh, oy + 4.8 * zh
    anchors = [h for h in hits
               if bx0 <= h["x"] + h["size"] / 2 <= bx1 and by0 <= h["y"] + h["size"] / 2 <= by1]
    print(f"粗匹配锚点(板区内): {len(anchors)} / 总命中 {len(hits)}")

    # 2) 行聚类 + 栅格化 + 补格分类
    rows = fit_rows(anchors, icon_px)

    def row_steps(r):
        cs = sorted(h["x"] + h["size"] / 2 for h in r["hits"])
        return [d for d in np.diff(cs) if icon_px * 1.1 < d < icon_px * 2.2]

    # 列距分区估计：大招区（角标框内）和标准区间距不同
    ult_rows = [r for r in rows if r["cy"] < oy + zh * 1.15]
    std_rows = [r for r in rows if r["cy"] >= oy + zh * 1.15]
    def section_spacing(rs, default):
        steps = [d for r in rs for d in row_steps(r)]
        return float(np.median(steps)) if steps else default
    sp_ult = section_spacing(ult_rows, icon_px * 1.8)
    sp_std = section_spacing(std_rows, icon_px * 1.6)
    print(f"行数 {len(rows)}（大招 {len(ult_rows)} / 标准 {len(std_rows)}），"
          f"列距: 大招 {sp_ult:.1f} / 标准 {sp_std:.1f}")

    results = []
    for r_i, r in enumerate(rows):
        spacing = sp_ult if r["cy"] < oy + zh * 1.15 else sp_std
        own = row_steps(r)
        if len(own) >= 2:
            spacing = float(np.median(own))
        # 锚点无条件保留
        for h in r["hits"]:
            results.append({"row": r_i, "cx": h["x"] + h["size"] / 2, "cy": r["cy"],
                            "a": h["a"], "score": h["score"], "src": "锚"})
        # 栅格只用来补空缺格；单锚点的行不可信（误报会自成一行生出垃圾补格）
        if len(r["hits"]) < 2:
            continue
        for cx in raster_row(r, spacing, bx0, bx1):
            if any(abs(h["x"] + h["size"] / 2 - cx) < spacing * 0.35 for h in r["hits"]):
                continue
            cls = classify_cell(warped, cx, r["cy"], icon_px, templates)
            if cls and cls[1] >= MIN_CLS_SCORE:
                results.append({"row": r_i, "cx": cx, "cy": r["cy"],
                                "a": cls[0], "score": cls[1], "src": "补"})

    n_anchor = sum(1 for r in results if r["src"] == "锚")
    n_fill = sum(1 for r in results if r["src"] == "补")
    print(f"最终槽位识别: {len(results)} 个（锚点 {n_anchor} + 补格 {n_fill}）")

    hits_v = [{"a": r["a"], "score": r["score"]} for r in results]
    ranked = vote(hits_v, snap)
    print("\n英雄加权投票:")
    for hid, vs, w in ranked[:14]:
        names = [f"{n} {s:.2f}" for n, s in sorted(vs, key=lambda x: -x[1])][:4]
        print(f"  权重 {w:.2f}  ({len(vs)}技能)  {snap.hero(hid).english_name:<18} {names}")
    print("\n推断 12 英雄池 =", [snap.hero(h).english_name for h, _, _ in ranked[:12]])

    vis = warped.copy()
    for r in results:
        color = (0, 255, 128) if r["src"] == "锚" else (0, 128, 255)
        x, y = int(r["cx"] - icon_px / 2), int(r["cy"] - icon_px / 2)
        cv2.rectangle(vis, (x, y), (x + icon_px, y + icon_px), color, 2)
        cv2.putText(vis, f"{r['a'].short_name[:14]} {r['score']:.2f}", (x, y - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)
    out = img_path.with_name(img_path.stem + "_slots.jpg")
    imwrite_u(out, vis)
    print(f"可视化: {out}")


if __name__ == "__main__":
    main()
