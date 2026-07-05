"""识别实验 v1：对一张草稿界面截图做全库多尺度模板匹配。

不依赖坐标——用滑窗模板匹配直接在整图上找技能/英雄图标，
测"零先验识别"的精度下限。输出：
- 控制台：识别列表（名称、置信度、位置）
- input/<原图名>_annotated.jpg：标注框可视化，人工核对用
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from addraft import Snapshot

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "web" / "img"

SCALES = (48, 62, 76, 90, 104, 118)  # 模板缩放边长候选（截屏图标~50-80px，手机照~90-110px）
THRESHOLD = 0.72               # 归一化相关系数阈值
NMS_DIST = 40                  # 同位置去重半径（像素）


def imread_u(path):
    """cv2.imread 不支持 Windows 中文路径，用 fromfile+imdecode 代替。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_u(path, img):
    ok, buf = cv2.imencode(Path(path).suffix, img)
    if ok:
        buf.tofile(str(path))
    return ok


def load_templates(snap):
    out = []
    for a in snap.draftable():
        folder = "heroes" if a.is_hero_body else "abilities"
        p = IMG_DIR / folder / f"{a.short_name}.png"
        img = imread_u(p)
        if img is None:
            continue
        # 英雄头像是横版 256x144，居中裁方形再用
        h, w = img.shape[:2]
        if w != h:
            s = min(h, w)
            img = img[(h - s) // 2:(h + s) // 2, (w - s) // 2:(w + s) // 2]
        out.append((a, img))
    return out


def match_all(scene, templates):
    hits = []
    for a, tpl in templates:
        best = None
        for size in SCALES:
            t = cv2.resize(tpl, (size, size), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(scene, t, cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(res)
            if best is None or val > best[0]:
                best = (val, loc, size)
        val, loc, size = best
        if val >= THRESHOLD:
            hits.append({"a": a, "score": val, "x": loc[0], "y": loc[1], "size": size})
    return hits


def nms(hits):
    """同一位置可能被多个模板命中，只留分数最高的。"""
    hits = sorted(hits, key=lambda h: -h["score"])
    kept = []
    for h in hits:
        cx, cy = h["x"] + h["size"] / 2, h["y"] + h["size"] / 2
        clash = any(
            abs(cx - (k["x"] + k["size"] / 2)) < NMS_DIST
            and abs(cy - (k["y"] + k["size"] / 2)) < NMS_DIST
            for k in kept
        )
        if not clash:
            kept.append(h)
    return kept


def main():
    img_path = Path(sys.argv[1]) if len(sys.argv) > 1 else next((ROOT / "input").glob("*.jpg"))
    scene = imread_u(img_path)
    print(f"图像: {img_path.name}  {scene.shape[1]}x{scene.shape[0]}")

    snap = Snapshot.load()
    templates = load_templates(snap)
    print(f"模板库: {len(templates)} 个（技能+英雄头像）")

    hits = nms(match_all(scene, templates))
    hits.sort(key=lambda h: (h["y"] // 60, h["x"]))
    print(f"\n识别到 {len(hits)} 个图标（阈值 {THRESHOLD}）:")
    for h in hits:
        kind = "英雄" if h["a"].is_hero_body else ("大招" if h["a"].is_ultimate else "技能")
        print(f"  [{h['score']:.2f}] ({h['x']:>4},{h['y']:>4}) {kind} {h['a'].english_name}")

    # 英雄投票：全命中加权（w = score - 0.70），同技能只计最高分一次。
    # 弱信号(0.72-0.79)单独不可信，但同英雄多个弱信号叠加就是强证据。
    from collections import defaultdict
    best_by_ability = {}
    for h in hits:
        aid = h["a"].id
        if aid not in best_by_ability or h["score"] > best_by_ability[aid]["score"]:
            best_by_ability[aid] = h
    votes = defaultdict(list)
    for h in best_by_ability.values():
        a = h["a"]
        hero_id = -a.id if a.is_hero_body else a.owner_hero_id
        if hero_id:
            votes[hero_id].append((a.english_name, h["score"]))
    ranked = sorted(
        ((hid, vs, sum(s - 0.70 for _, s in vs)) for hid, vs in votes.items()),
        key=lambda t: -t[2],
    )
    print(f"\n英雄加权投票（{len(best_by_ability)} 个去重命中）:")
    for hid, vs, w in ranked:
        hero = snap.hero(hid)
        names = [f"{n} {s:.2f}" for n, s in sorted(vs, key=lambda x: -x[1])][:4]
        print(f"  权重 {w:.2f}  ({len(vs)}技能)  {hero.english_name:<18} {names}")
    print("\n推断 12 英雄池 =", [snap.hero(h).english_name for h, _, _ in ranked[:12]])

    for h in hits:
        x, y, s = h["x"], h["y"], h["size"]
        cv2.rectangle(scene, (x, y), (x + s, y + s), (0, 255, 128), 2)
        cv2.putText(scene, f"{h['a'].short_name[:18]} {h['score']:.2f}", (x, y - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 128), 1)
    out = img_path.with_name(img_path.stem + "_annotated.jpg")
    imwrite_u(out, scene)
    print(f"\n标注图已存: {out}")


if __name__ == "__main__":
    main()
