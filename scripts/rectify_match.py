"""全自动管线实验：绿角标检测 → 透视矫正 → 模板匹配 → 英雄反推。

用终极技能区自带的 4 个绿色角标（游戏 UI 恒定元素）做定位锚，
无需玩家点角。角标四边形 → 单应变换把全图"摆正" → 匹配分数应回升。
"""

import sys
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from addraft import Snapshot
from scripts.detect_brackets import find_bracket_corners, imread_u, imwrite_u

IMG_DIR = Path(__file__).resolve().parent.parent / "web" / "img"
# 1080p 布局（ability-draft-plus 坐标）：终极区宽 ~619px、图标边长 ~58px
ICON_TO_ZONE = 58 / 619
THRESHOLD = 0.72
NMS_DIST = 40


def pick_quads(cands, img_w, img_h, top_k=5):
    """从绿色连通域里选出候选四边形（按几何+形状得分排序，取前 K 个待验证）。

    真角标是空心 L 形"引号"：填充率(面积/外接框) ~0.2-0.4；
    实心图标/面板 >0.5 —— 这是排除假矩形的关键特征。
    """
    cands = [c for c in cands if 0.4 <= c["w"] / max(c["h"], 1) <= 2.5]
    scored = []
    for combo in combinations(range(len(cands)), 4):
        cs = sorted((cands[i] for i in combo), key=lambda c: c["cy"])
        top = sorted(cs[:2], key=lambda c: c["cx"])
        bot = sorted(cs[2:], key=lambda c: c["cx"])
        (tlx, tly), (trx, try_) = (top[0]["cx"], top[0]["cy"]), (top[1]["cx"], top[1]["cy"])
        (blx, bly), (brx, bry) = (bot[0]["cx"], bot[0]["cy"]), (bot[1]["cx"], bot[1]["cy"])
        w_top, w_bot = trx - tlx, brx - blx
        h_l, h_r = bly - tly, bry - try_
        if w_top < img_w * 0.15 or w_bot < img_w * 0.15:
            continue
        if h_l < img_h * 0.08 or h_r < img_h * 0.08:
            continue
        if abs(tly - try_) > h_l * 0.25 or abs(bly - bry) > h_l * 0.25:
            continue  # 上下边应接近水平
        if abs(w_top - w_bot) > 0.25 * max(w_top, w_bot):
            continue  # 透视允许些许梯形，但不能夸张
        if abs(tlx - blx) > 0.08 * w_top or abs(trx - brx) > 0.08 * w_top:
            continue  # 左右边应近似垂直
        aspect = ((w_top + w_bot) / 2) / ((h_l + h_r) / 2)
        if not 2.0 <= aspect <= 4.5:
            continue  # 终极区是宽扁矩形（标准约 3.0-3.4）
        fill = sum(c["area"] / (c["w"] * c["h"]) for c in top + bot) / 4
        sym = -abs(w_top - w_bot) / w_top - abs(h_l - h_r) / h_l - abs(tly - try_) / h_l
        scored.append((sym - 1.5 * fill,
                       ((tlx, tly), (trx, try_), (blx, bly), (brx, bry))))
    scored.sort(key=lambda t: -t[0])
    return [q for _, q in scored[:top_k]]


def rectify(img, quad, upscale=1.0):
    """upscale>1 时目标坐标系放大（单次插值获得更高匹配分辨率）。"""
    (tl, tr, bl, br) = quad
    w = (tr[0] - tl[0] + br[0] - bl[0]) / 2 * upscale
    h = (bl[1] - tl[1] + br[1] - tr[1]) / 2 * upscale
    src = np.float32([tl, tr, bl, br])
    dst = np.float32([[0, 0], [w, 0], [0, h], [w, h]])
    H = cv2.getPerspectiveTransform(src, dst)
    # 平移画布让全图可见
    corners = np.float32([[0, 0], [img.shape[1], 0], [0, img.shape[0]],
                          [img.shape[1], img.shape[0]]]).reshape(-1, 1, 2)
    warped_corners = cv2.perspectiveTransform(corners, H).reshape(-1, 2)
    minx, miny = warped_corners.min(axis=0)
    maxx, maxy = warped_corners.max(axis=0)
    T = np.array([[1, 0, -minx], [0, 1, -miny], [0, 0, 1]], dtype=np.float64)
    out = cv2.warpPerspective(img, T @ H, (int(maxx - minx), int(maxy - miny)))
    return out, w, h, (-minx, -miny)  # 终极区宽高 + 它在输出图中的原点


def load_templates(snap):
    out = []
    for a in snap.draftable():
        folder = "heroes" if a.is_hero_body else "abilities"
        img = imread_u(IMG_DIR / folder / f"{a.short_name}.png")
        if img is None:
            continue
        hh, ww = img.shape[:2]
        if ww != hh:
            s = min(hh, ww)
            img = img[(hh - s) // 2:(hh + s) // 2, (ww - s) // 2:(ww + s) // 2]
        out.append((a, img))
    return out


def match(scene, templates, scales):
    hits = []
    for a, tpl in templates:
        best = None
        for size in scales:
            t = cv2.resize(tpl, (size, size), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(scene, t, cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(res)
            if best is None or val > best[0]:
                best = (val, loc, size)
        val, loc, size = best
        if val >= THRESHOLD:
            hits.append({"a": a, "score": val, "x": loc[0], "y": loc[1], "size": size})
    hits.sort(key=lambda h: -h["score"])
    kept = []
    for h in hits:
        cx, cy = h["x"] + h["size"] / 2, h["y"] + h["size"] / 2
        if not any(abs(cx - (k["x"] + k["size"] / 2)) < NMS_DIST
                   and abs(cy - (k["y"] + k["size"] / 2)) < NMS_DIST for k in kept):
            kept.append(h)
    return kept


def vote(hits, snap):
    from collections import defaultdict
    best_by_ability = {}
    for h in hits:
        aid = h["a"].id
        if aid not in best_by_ability or h["score"] > best_by_ability[aid]["score"]:
            best_by_ability[aid] = h
    votes = defaultdict(list)
    for h in best_by_ability.values():
        a = h["a"]
        hid = -a.id if a.is_hero_body else a.owner_hero_id
        if hid:
            votes[hid].append((a.english_name, h["score"]))
    return sorted(((hid, vs, sum(s - 0.70 for _, s in vs)) for hid, vs in votes.items()),
                  key=lambda t: -t[2])


def validate_quad(img, quad, templates):
    """矫正后终极区里必须真的能匹配出技能图标——按预测尺度在区内快速匹配计数。"""
    warped, w, h, (ox, oy) = rectify(img, quad)
    pad = int(w * ICON_TO_ZONE)
    x0, y0 = max(0, int(ox) - pad), max(0, int(oy) - pad)
    zone = warped[y0:int(oy + h) + pad, x0:int(ox + w) + pad]
    size = max(24, int(w * ICON_TO_ZONE))
    count = 0
    for a, tpl in templates:
        if not a.is_ultimate:
            continue  # 终极区只匹配大招模板，更快更判别
        t = cv2.resize(tpl, (size, size), interpolation=cv2.INTER_AREA)
        if zone.shape[0] <= size or zone.shape[1] <= size:
            return 0, None
        _, val, _, _ = cv2.minMaxLoc(cv2.matchTemplate(zone, t, cv2.TM_CCOEFF_NORMED))
        if val >= 0.72:
            count += 1
    return count, (warped, w)


def main():
    img_path = Path(sys.argv[1])
    img = imread_u(img_path)
    print(f"图像: {img_path.name} {img.shape[1]}x{img.shape[0]}")

    snap = Snapshot.load()
    templates = load_templates(snap)

    _, cands = find_bracket_corners(img)
    quads = pick_quads(cands, img.shape[1], img.shape[0])
    if not quads:
        print("未找到角标四边形")
        return
    best = None
    for i, q in enumerate(quads):
        count, res = validate_quad(img, q, templates)
        print(f"候选四边形 #{i+1} TL{tuple(map(round, q[0]))} TR{tuple(map(round, q[1]))} "
              f"→ 终极区大招命中 {count} 个")
        if best is None or count > best[0]:
            best = (count, q, res)
        if count >= 6:
            break
    count, quad, _ = best
    if count < 2:
        print("所有候选四边形都未通过内容验证")
        return
    print(f"选定: TL{tuple(map(round, quad[0]))} TR{tuple(map(round, quad[1]))} "
          f"BL{tuple(map(round, quad[2]))} BR{tuple(map(round, quad[3]))}")

    warped, zone_w, _, _ = rectify(img, quad)
    out_path = img_path.with_name(img_path.stem + "_rectified.jpg")
    imwrite_u(out_path, warped)
    icon = zone_w * ICON_TO_ZONE
    scales = tuple(int(icon * f) for f in (0.85, 1.0, 1.15))
    print(f"矫正后: {warped.shape[1]}x{warped.shape[0]}, 终极区宽 {zone_w:.0f}, "
          f"预测图标 {icon:.0f}px, 尺度 {scales}  → {out_path.name}")

    hits = match(warped, templates, scales)
    scores = sorted((h["score"] for h in hits), reverse=True)
    print(f"\n命中 {len(hits)} 个 | 分数 top10: {[f'{s:.2f}' for s in scores[:10]]}")
    print(f"≥0.80 的命中: {sum(1 for s in scores if s >= 0.80)} 个")

    ranked = vote(hits, snap)
    print("\n英雄加权投票:")
    for hid, vs, w in ranked[:15]:
        names = [f"{n} {s:.2f}" for n, s in sorted(vs, key=lambda x: -x[1])][:4]
        print(f"  权重 {w:.2f}  ({len(vs)}技能)  {snap.hero(hid).english_name:<18} {names}")
    print("\n推断 12 英雄池 =", [snap.hero(h).english_name for h, _, _ in ranked[:12]])


if __name__ == "__main__":
    main()
