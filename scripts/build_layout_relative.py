"""标定：把 ability-draft-plus 的 1080p 槽位坐标换算成"相对角标区"的比例坐标。

原理：real1 照片经角标矫正后，图内大招的匹配位置是已知的；
ADP 表里这些大招槽位的 1080p 坐标也已知 → 拟合 缩放+平移 (s, tx, ty)，
把 1080p 坐标系对齐到"角标区坐标系"，再把全部 60 槽位表达为角标区的比例。

产出 web/data/layout_relative.json —— JS 端识别的核心配置。
并生成 real1 的槽位叠加验证图。
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from addraft import Snapshot
from scripts.detect_brackets import find_bracket_corners, imread_u, imwrite_u
from scripts.rectify_match import ICON_TO_ZONE, load_templates, pick_quads, rectify, validate_quad

ROOT = Path(__file__).resolve().parent.parent
LAYOUT = json.loads((ROOT / "data" / "layout_coordinates.json").read_text(encoding="utf-8"))
L1080 = LAYOUT["resolutions"]["1920x1080"]


def slot_centers(slots):
    return [(s["x"] + s["width"] / 2, s["y"] + s["height"] / 2) for s in slots]


def main():
    img = imread_u(ROOT / "input" / "real1.jpg")
    snap = Snapshot.load()
    templates = load_templates(snap)

    quads = pick_quads(*(find_bracket_corners(img)[1],), img.shape[1], img.shape[0])
    quad = None
    for q in quads:
        count, _ = validate_quad(img, q, templates)
        if count >= 6:
            quad = q
            break
    assert quad, "real1 角标未定位"
    warped, zone_w, zone_h, (ox, oy) = rectify(img, quad)
    print(f"角标区: 原点({ox:.0f},{oy:.0f}) 尺寸 {zone_w:.0f}x{zone_h:.0f}")

    # 1) 在矫正图上匹配所有大招模板，取高置信命中作为标定锚点
    size = int(zone_w * ICON_TO_ZONE)
    anchors = []
    for a, tpl in templates:
        if not a.is_ultimate:
            continue
        best = None
        for s_px in (int(size * 0.85), size, int(size * 1.15)):
            t = cv2.resize(tpl, (s_px, s_px), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(warped, t, cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(res)
            if best is None or val > best[0]:
                best = (val, loc, s_px)
        val, loc, s_px = best
        cx, cy = loc[0] + s_px / 2, loc[1] + s_px / 2
        # 锚点必须落在角标区内（真大招按定义在框里，区外全是误报）
        if val >= 0.74 and ox - 15 <= cx <= ox + zone_w + 15 and oy - 15 <= cy <= oy + zone_h + 15:
            anchors.append((a.english_name, cx, cy, val))
    print(f"标定锚点（大招命中）: {len(anchors)} 个")
    for n, x, y, v in anchors:
        print(f"  {n:<24} ({x:.0f},{y:.0f}) {v:.2f}")

    # 2) 拟合 s, tx, ty：1080p 坐标 * s + t ≈ 矫正图坐标
    # 关键：s 由"锚点列间距 / 槽位列间距"直接确定（不自由拟合，避免错位分配），
    # 再穷举列偏移做锚点→槽位分配，取残差最小者。
    ult_centers = slot_centers(L1080["ultimate_slots_coords"])
    # 聚类列/行（间距 < 40px 视为同列/行；两行的列坐标因 3D 透视有微小错位）
    def cluster(vals, tol=40):
        out = []
        for v in sorted(vals):
            if out and v - out[-1][-1] < tol:
                out[-1].append(v)
            else:
                out.append([v])
        return [float(np.mean(g)) for g in out]
    slot_cols = cluster([c[0] for c in ult_centers])
    slot_rows = cluster([c[1] for c in ult_centers])
    a_cols = cluster([a[1] for a in anchors])
    a_rows = cluster([a[2] for a in anchors])
    slot_col_gap = float(np.median(np.diff(slot_cols)))
    a_col_gap = float(np.median(np.diff(a_cols)))
    s = a_col_gap / slot_col_gap
    print(f"锚点列 {[f'{c:.0f}' for c in a_cols]} 行 {[f'{r:.0f}' for r in a_rows]}")
    print(f"列间距: 锚点 {a_col_gap:.1f} / 槽位 {slot_col_gap:.1f} → s={s:.4f}")

    # 平移由强先验确定：绿角标对称框住大招网格 → 网格中心 = 角标区中心。
    # （锚点残差在整列平移下不变——网格是周期性的，不能用它定列偏移）
    grid_cx = float(np.mean([c[0] for c in ult_centers]))
    grid_cy = float(np.mean([c[1] for c in ult_centers]))
    tx = (ox + zone_w / 2) - grid_cx * s
    ty = (oy + zone_h / 2) - grid_cy * s
    err = 0
    for _, hx, hy, _ in anchors:
        d = min((hx - (cx * s + tx)) ** 2 + (hy - (cy * s + ty)) ** 2
                for cx, cy in ult_centers)
        err += d ** 0.5
    best_err = err / len(anchors)
    print(f"拟合: s={s:.4f} t=({tx:.1f},{ty:.1f}) 锚点校验残差 {best_err:.1f}px")
    assert best_err < 15, "锚点残差过大，标定失败"

    # 3) 角标区矩形反算回 1080p 坐标系 → 全部槽位转为角标区比例
    zx, zy = (0 - tx) / s + ox / s - ox / s, 0  # 角标区原点在矫正图为 (ox,oy)
    zone_1080 = ((ox - tx) / s, (oy - ty) / s, zone_w / s, zone_h / s)
    print(f"角标区在 1080p 坐标系: x={zone_1080[0]:.0f} y={zone_1080[1]:.0f} "
          f"w={zone_1080[2]:.0f} h={zone_1080[3]:.0f}")

    def to_rel(slots):
        out = []
        for sl in slots:
            out.append({
                "fx": (sl["x"] - zone_1080[0]) / zone_1080[2],
                "fy": (sl["y"] - zone_1080[1]) / zone_1080[3],
                "fw": sl["width"] / zone_1080[2],
                "fh": sl["height"] / zone_1080[3],
                "order": sl.get("hero_order"),
                **({"ability_order": sl["ability_order"]} if "ability_order" in sl else {}),
            })
        return out

    rel = {
        "note": "全部槽位以终极区绿角标矩形为基准的比例坐标；fx/fy 为槽位左上角，fw/fh 为尺寸",
        "calibrated_from": "real1.jpg + ability-draft-plus 1920x1080 preset",
        "residual_px": round(best_err, 1),
        "ultimates": to_rel(L1080["ultimate_slots_coords"]),
        "standards": to_rel(L1080["standard_slots_coords"]),
        "models": to_rel(L1080["models_coords"]),
    }
    out_path = ROOT / "web" / "data" / "layout_relative.json"
    out_path.write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入 {out_path}")

    # 4) 验证图：把比例坐标铺回矫正图
    vis = warped.copy()
    for group, color in (("ultimates", (0, 255, 255)), ("standards", (0, 255, 0)),
                         ("models", (255, 128, 0))):
        for sl in rel[group]:
            x = int(ox + sl["fx"] * zone_w); y = int(oy + sl["fy"] * zone_h)
            w = int(sl["fw"] * zone_w); h = int(sl["fh"] * zone_h)
            cv2.rectangle(vis, (x, y), (x + w, y + h), color, 2)
    imwrite_u(ROOT / "input" / "real1_layout_check.jpg", vis)
    print("验证图: input/real1_layout_check.jpg")


if __name__ == "__main__":
    main()
