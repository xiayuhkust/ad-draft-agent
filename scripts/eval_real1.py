"""用 real1 的 ground truth 做分区正确率评估 + 验证"分区约束匹配"的提升。

用户提供的真实 12 英雄（2026-07-04）：
炸弹人/沉默/马西/蝙蝠/神谕者/电炎绝手/马格纳斯/光法/剑圣/屠夫/术士/军团
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from addraft import Snapshot
from scripts.detect_brackets import find_bracket_corners, imread_u
from scripts.detect_slots import classify_cell, fit_rows, raster_row
from scripts.rectify_match import (ICON_TO_ZONE, load_templates, match, pick_quads,
                                   rectify, validate_quad)

TRUTH = {"Techies", "Silencer", "Marci", "Batrider", "Shadow Shaman", "Snapfire",
         "Magnus", "Keeper of the Light", "Juggernaut", "Pudge", "Warlock",
         "Legion Commander"}


def region_of(cy, cx, oy, zh, oz_x, zw):
    if cy < oy + zh * 1.15:
        return "ult"
    # 标准区 6 列窗口之外的两翼 = 身板列（粗略：x 在角标区横向范围外侧）
    if cx < oz_x - zw * 0.02 or cx > oz_x + zw * 1.02:
        return "model"
    return "std"


def run(img, snap, all_templates, constrained):
    quads = pick_quads(find_bracket_corners(img)[1], img.shape[1], img.shape[0])
    quad = next(q for q in quads if validate_quad(img, q, all_templates)[0] >= 6)
    warped, zw, zh, (ox, oy) = rectify(img, quad)
    icon_px = int(zw * ICON_TO_ZONE)

    t_ult = [(a, t) for a, t in all_templates if a.is_ultimate]
    t_nonult = [(a, t) for a, t in all_templates if not a.is_ultimate and not a.is_hero_body]
    t_hero = [(a, t) for a, t in all_templates if a.is_hero_body]

    scales = (int(icon_px * 0.85), icon_px, int(icon_px * 1.15))
    hits = match(warped, all_templates, scales)
    bx0, bx1 = ox - 0.45 * zw, ox + 1.45 * zw
    by0, by1 = oy - 0.15 * zh, oy + 4.8 * zh
    anchors = [h for h in hits
               if bx0 <= h["x"] + h["size"] / 2 <= bx1 and by0 <= h["y"] + h["size"] / 2 <= by1]

    rows = fit_rows(anchors, icon_px)
    def row_steps(r):
        cs = sorted(h["x"] + h["size"] / 2 for h in r["hits"])
        return [d for d in np.diff(cs) if icon_px * 1.1 < d < icon_px * 2.2]
    ult_rows = [r for r in rows if r["cy"] < oy + zh * 1.15]
    std_rows = [r for r in rows if r["cy"] >= oy + zh * 1.15]
    def sec_sp(rs, dflt):
        st = [d for r in rs for d in row_steps(r)]
        return float(np.median(st)) if st else dflt
    sp_ult, sp_std = sec_sp(ult_rows, icon_px * 1.8), sec_sp(std_rows, icon_px * 1.6)

    results = []
    for r_i, r in enumerate(rows):
        spacing = sp_ult if r["cy"] < oy + zh * 1.15 else sp_std
        own = row_steps(r)
        if len(own) >= 2:
            spacing = float(np.median(own))
        for h in r["hits"]:
            cx = h["x"] + h["size"] / 2
            reg = region_of(r["cy"], cx, oy, zh, ox, zw)
            if constrained:
                # 锚点也按区域重新分类（区域约束的模板子集）
                tset = t_ult if reg == "ult" else (t_hero if reg == "model" else t_nonult)
                cls = classify_cell(warped, cx, r["cy"], icon_px, tset)
                if cls and cls[1] >= 0.55:
                    results.append({"cx": cx, "cy": r["cy"], "a": cls[0], "score": cls[1],
                                    "reg": reg, "src": "锚"})
            else:
                results.append({"cx": cx, "cy": r["cy"], "a": h["a"], "score": h["score"],
                                "reg": reg, "src": "锚"})
        if len(r["hits"]) < 2:
            continue
        for cx in raster_row(r, spacing, bx0, bx1):
            if any(abs(h["x"] + h["size"] / 2 - cx) < spacing * 0.35 for h in r["hits"]):
                continue
            reg = region_of(r["cy"], cx, oy, zh, ox, zw)
            tset = (t_ult if reg == "ult" else (t_hero if reg == "model" else t_nonult)) \
                if constrained else all_templates
            cls = classify_cell(warped, cx, r["cy"], icon_px, tset)
            if cls and cls[1] >= 0.55:
                results.append({"cx": cx, "cy": r["cy"], "a": cls[0], "score": cls[1],
                                "reg": reg, "src": "补"})
    return results


def evaluate(results, snap, label):
    print(f"\n===== {label} =====")
    from collections import defaultdict
    stats = defaultdict(lambda: [0, 0])
    for r in results:
        a = r["a"]
        hid = -a.id if a.is_hero_body else a.owner_hero_id
        hero = snap.hero(hid).english_name if hid else "?"
        ok = hero in TRUTH
        stats[r["reg"]][0 if ok else 1] += 1
    for reg in ("ult", "std", "model"):
        ok, bad = stats[reg]
        total = ok + bad
        pct = ok / total * 100 if total else 0
        print(f"  {reg:>5}: {ok}/{total} 正确 ({pct:.0f}%)")

    # 投票（区域加权可在此调）
    best = {}
    for r in results:
        if r["a"].id not in best or r["score"] > best[r["a"].id]["score"]:
            best[r["a"].id] = r
    votes = defaultdict(float)
    detail = defaultdict(list)
    for r in best.values():
        a = r["a"]
        hid = -a.id if a.is_hero_body else a.owner_hero_id
        if not hid:
            continue
        w = r["score"] - 0.70
        if r["reg"] == "ult":
            w *= 2.0      # 大招区：区域可验证、模板池小 → 高可信
        if r["reg"] == "model":
            w *= 1.5
        votes[hid] += w
        detail[hid].append(f"{a.english_name}({r['reg']}) {r['score']:.2f}")
    ranked = sorted(votes.items(), key=lambda kv: -kv[1])
    top12 = [snap.hero(h).english_name for h, _ in ranked[:12]]
    correct = sum(1 for h in top12 if h in TRUTH)
    print(f"  top-12: {correct}/12 正确")
    for h, w in ranked[:14]:
        name = snap.hero(h).english_name
        mark = "✓" if name in TRUTH else "✗"
        print(f"   {mark} {w:.2f} {name:<20} {detail[h][:3]}")
    missed = TRUTH - set(top12)
    if missed:
        print(f"  漏掉: {missed}")


def main():
    img = imread_u(Path("input/real1.jpg"))
    snap = Snapshot.load()
    templates = load_templates(snap)
    for constrained in (False, True):
        results = run(img, snap, templates, constrained)
        evaluate(results, snap, "分区约束匹配" if constrained else "基线（全模板混匹配）")


if __name__ == "__main__":
    main()
