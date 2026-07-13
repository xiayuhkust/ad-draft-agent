"""识别引擎（生产版快车道）。

管线：绿角标检测 → 候选四边形 → 单应矫正 → 大招 2×6 格定点分类 →
ULT_LOCK（top-1 ≥ 0.75 锁席）。全程无分辨率假设，实验 #1-#10 验证。

慢路径（全图滑窗 + 融合投票）留在 scripts/assign_pool.py，按需再接。
"""

from __future__ import annotations

import hashlib
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

from .snapshot import Snapshot

ICON_TO_ZONE = 58 / 619   # 图标边长 / 角标区宽（UI 固定比例，实测跨分辨率成立）
CELL_ACCEPT = 0.72        # 四边形内容验证：格子 top-1 达标线
QUAD_MIN_CELLS = 6        # 至少 6 格达标才认定是草稿界面
ULT_LOCK = 0.75           # 大招锁席线
ULT_WEAK = 0.60           # 大招弱候选线（收录缺口下宁多勿漏，标记低置信进结果）
SLOT_FALLBACK = 0.70      # 大招格二次分类（全技能模板）的接受线
BODY_LOCK = 0.70          # 身板确认线（只提升已有英雄的置信度）
BODY_SOLO = 0.85          # 身板单独引入新英雄的门槛（32px 下杂讯吸铁石在 0.7x，必须高置）
# AD 收录缺口（用户实战发现）：部分英雄大招不进池（如天穹守望者）、部分小招不进池（如小Y）
# → 英雄池 = 大招证据 ∪ 身板证据，实战允许 >12 个候选，宁多勿漏


def imdecode_bytes(data: bytes):
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def _green_candidates(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (40, 80, 90), (85, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    h_img, w_img = mask.shape
    area_min, area_max = h_img * w_img * 8e-6, h_img * w_img * 6e-4
    cands = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (area_min <= area <= area_max):
            continue
        if w > w_img * 0.1 or h > h_img * 0.1:
            continue
        if not 0.4 <= w / max(h, 1) <= 2.5:
            continue
        cands.append({"cx": centroids[i][0], "cy": centroids[i][1],
                      "w": w, "h": h, "area": area})
    return cands


def _pick_quads(cands, img_w, img_h, top_k=5):
    scored = []
    for combo in combinations(range(len(cands)), 4):
        cs = sorted((cands[i] for i in combo), key=lambda c: c["cy"])
        top = sorted(cs[:2], key=lambda c: c["cx"])
        bot = sorted(cs[2:], key=lambda c: c["cx"])
        (tlx, tly), (trx, try_) = (top[0]["cx"], top[0]["cy"]), (top[1]["cx"], top[1]["cy"])
        (blx, bly), (brx, bry) = (bot[0]["cx"], bot[0]["cy"]), (bot[1]["cx"], bot[1]["cy"])
        w_top, w_bot = trx - tlx, brx - blx
        h_l, h_r = bly - tly, bry - try_
        if w_top < img_w * 0.12 or w_bot < img_w * 0.12:
            continue
        if h_l < img_h * 0.06 or h_r < img_h * 0.06:
            continue
        if abs(tly - try_) > h_l * 0.25 or abs(bly - bry) > h_l * 0.25:
            continue
        if abs(w_top - w_bot) > 0.25 * max(w_top, w_bot):
            continue
        if abs(tlx - blx) > 0.08 * w_top or abs(trx - brx) > 0.08 * w_top:
            continue
        aspect = ((w_top + w_bot) / 2) / ((h_l + h_r) / 2)
        if not 2.0 <= aspect <= 4.5:
            continue
        fill = sum(c["area"] / (c["w"] * c["h"]) for c in top + bot) / 4
        sym = -abs(w_top - w_bot) / w_top - abs(h_l - h_r) / h_l - abs(tly - try_) / h_l
        scored.append((sym - 1.5 * fill,
                       ((tlx, tly), (trx, try_), (blx, bly), (brx, bry))))
    scored.sort(key=lambda t: -t[0])
    return [q for _, q in scored[:top_k]]


def _rectify(img, quad):
    tl, tr, bl, br = quad
    w = (tr[0] - tl[0] + br[0] - bl[0]) / 2
    h = (bl[1] - tl[1] + br[1] - tr[1]) / 2
    H = cv2.getPerspectiveTransform(
        np.float32([tl, tr, bl, br]),
        np.float32([[0, 0], [w, 0], [0, h], [w, h]]))
    corners = np.float32([[0, 0], [img.shape[1], 0], [0, img.shape[0]],
                          [img.shape[1], img.shape[0]]]).reshape(-1, 1, 2)
    wc = cv2.perspectiveTransform(corners, H).reshape(-1, 2)
    minx, miny = wc.min(axis=0)
    maxx, maxy = wc.max(axis=0)
    T = np.array([[1, 0, -minx], [0, 1, -miny], [0, 0, 1]], dtype=np.float64)
    out = cv2.warpPerspective(img, T @ H, (int(maxx - minx), int(maxy - miny)))
    return out, w, h, (-minx, -miny)


class Recognizer:
    """常驻内存的识别器：模板一次加载，多次请求复用。"""

    def __init__(self, snapshot: Snapshot | None = None, img_dir: Path | None = None):
        from .paths import EXE_DIR, ROOT
        self.snap = snapshot or Snapshot.load()
        img_dir = img_dir or ROOT / "web" / "img"
        tpls = self._load_templates(img_dir, EXE_DIR / "tpl_cache.npz")
        self.t_ult = tpls["ult"]
        # 全技能模板（大招格二次分类用：大招未收录的英雄，其格子里放的是小招）
        self.t_std = tpls["std"]
        self.t_hero = []
        for a, tpl in tpls["hero"]:
            h, w = tpl.shape[:2]  # 横版头像居中裁方
            s = min(h, w)
            self.t_hero.append((a, tpl[(h - s) // 2:(h + s) // 2, (w - s) // 2:(w + s) // 2]))

    def _load_templates(self, img_dir: Path, cache_path: Path) -> dict:
        """全部所需图标一次解码，结果缓存为单个 npz 供下次启动整块读入。

        636 个小 PNG 逐个读盘+解码在慢机器（机械盘/杀软实时扫描）上要几十秒，
        单文件顺序读快一个数量级。任一图标的名字/大小/mtime 变化即整体重建。
        """
        needed = []
        for a in self.snap.draftable():
            if a.is_hero_body:
                kind, p = "hero", img_dir / "heroes" / f"{a.short_name}.png"
            else:
                kind = "ult" if a.is_ultimate else "std"
                p = img_dir / "abilities" / f"{a.short_name}.png"
            if p.exists():
                needed.append((kind, a, p))
        key = hashlib.sha256("|".join(
            f"{k}:{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}"
            for k, _, p in needed).encode()).hexdigest()

        try:
            z = np.load(cache_path, allow_pickle=False)
            if str(z["__key__"]) == key:
                out = {"ult": [], "hero": [], "std": []}
                for kind, a, _ in needed:
                    out[kind].append((a, z[f"{kind[0]}_{a.short_name}"]))
                return out
        except Exception:
            pass  # 无缓存/损坏/图标已变 → 走慢路径重建

        out = {"ult": [], "hero": [], "std": []}
        save = {"__key__": np.array(key)}
        for kind, a, p in needed:
            # 不用 cv2.imread：它不支持含中文的路径
            tpl = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
            if tpl is None:
                continue
            save[f"{kind[0]}_{a.short_name}"] = tpl
            out[kind].append((a, tpl))
        try:
            tmp = cache_path.parent / (cache_path.name + ".new")
            with open(tmp, "wb") as f:
                np.savez(f, **save)
            tmp.replace(cache_path)
        except Exception:
            pass  # 缓存写不进（只读目录等）不影响运行
        return out

    def _classify_cell(self, warped, cx, cy, icon, templates=None):
        m = int(icon * 0.5)
        x0, y0 = int(cx - icon / 2 - m), int(cy - icon / 2 - m)
        x1, y1 = int(cx + icon / 2 + m), int(cy + icon / 2 + m)
        if x0 < 0 or y0 < 0 or x1 > warped.shape[1] or y1 > warped.shape[0]:
            return None
        crop = warped[y0:y1, x0:x1]
        if crop.shape[0] <= icon or crop.shape[1] <= icon:
            return None
        best = None
        for a, tpl in (templates if templates is not None else self.t_ult):
            t = cv2.resize(tpl, (icon, icon), interpolation=cv2.INTER_AREA)
            _, v, _, _ = cv2.minMaxLoc(cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED))
            if best is None or v > best[1]:
                best = (a, v)
        return best

    @staticmethod
    def _ult_cells(zw, zh, ox, oy):
        center = ox + zw / 2
        sp = zw * 0.172
        return [(center + (i - 2.5) * sp, cy)
                for cy in (oy + 0.26 * zh, oy + 0.76 * zh) for i in range(6)]

    def _validate_quad(self, img, quad):
        """降采样快速验证：格子统一缩到 ~32px 匹配 + 无望即弃，垃圾四边形秒拒。"""
        warped, zw, zh, (ox, oy) = _rectify(img, quad)
        icon = int(zw * ICON_TO_ZONE)
        if icon < 16:
            return 0
        scale = min(1.0, 32 / icon)
        if scale < 1.0:
            warped = cv2.resize(warped, None, fx=scale, fy=scale,
                                interpolation=cv2.INTER_AREA)
            zw, zh, ox, oy, icon = (zw * scale, zh * scale, ox * scale, oy * scale,
                                    max(16, int(icon * scale)))
        cells = self._ult_cells(zw, zh, ox, oy)
        ok = 0
        for idx, (cx, cy) in enumerate(cells):
            cls = self._classify_cell(warped, cx, cy, icon)
            if cls and cls[1] >= CELL_ACCEPT:
                ok += 1
            if ok + (len(cells) - idx - 1) < QUAD_MIN_CELLS:
                break  # 剩余格子全中也凑不够，提前放弃
        return ok

    def _scan_bodies(self, warped, zw, zh, ox, oy, icon):
        """扫描左右身板竖条（标准区两翼），返回 {heroId: score}。

        条带降采样到 ~32px 图标后滑窗匹配 127 个英雄头像，
        命中按 y 聚类（同格取最高分英雄），宁多勿漏。
        """
        found = {}
        y0 = max(0, int(oy + 0.95 * zh))
        y1 = min(warped.shape[0], int(oy + 3.8 * zh))
        for x0, x1 in ((int(ox - 0.34 * zw), int(ox + 0.08 * zw)),
                       (int(ox + zw - 0.08 * zw), int(ox + zw + 0.34 * zw))):
            x0 = max(0, x0)
            x1 = min(warped.shape[1], x1)
            strip = warped[y0:y1, x0:x1]
            if strip.shape[0] < icon or strip.shape[1] < icon:
                continue
            scale = min(1.0, 32 / icon)
            s_icon = max(16, int(icon * scale))
            s = cv2.resize(strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            hits = []
            for a, tpl in self.t_hero:
                t = cv2.resize(tpl, (s_icon, s_icon), interpolation=cv2.INTER_AREA)
                if s.shape[0] <= s_icon or s.shape[1] <= s_icon:
                    continue
                _, v, _, loc = cv2.minMaxLoc(cv2.matchTemplate(s, t, cv2.TM_CCOEFF_NORMED))
                if v >= BODY_LOCK:
                    hits.append((v, -a.id, loc[1]))
            # 同一格（y 邻近）只留最高分英雄
            hits.sort(reverse=True)
            taken_ys = []
            for v, hid, y in hits:
                if any(abs(y - ty) < s_icon * 0.7 for ty in taken_ys):
                    continue
                taken_ys.append(y)
                found[hid] = max(found.get(hid, 0), v)
        return found

    def _classify_quad(self, img, quad):
        """全精度分类（只对通过验证的四边形执行一次）。"""
        warped, zw, zh, (ox, oy) = _rectify(img, quad)
        icon = int(zw * ICON_TO_ZONE)
        cells, slot_extras = [], []
        for cx, cy in self._ult_cells(zw, zh, ox, oy):
            cls = self._classify_cell(warped, cx, cy, icon)
            # 大招模板匹配不上的格子 → 全技能模板二次分类
            # （大招未收录的英雄，该格放的是它的小招——用户实战发现的收录缺口）
            if cls is None or cls[1] < ULT_WEAK:
                alt = self._classify_cell(warped, cx, cy, icon, self.t_std)
                if alt and alt[1] >= SLOT_FALLBACK:
                    slot_extras.append(alt)
            cells.append(cls)
        bodies = self._scan_bodies(warped, zw, zh, ox, oy, icon)
        return cells, slot_extras, bodies

    def recognize(self, img) -> dict:
        """输入 BGR 图像，输出识别结果 dict（可直接 JSON 化）。"""
        cands = _green_candidates(img)
        quads = _pick_quads(cands, img.shape[1], img.shape[0])
        chosen = None
        for quad in quads:
            if self._validate_quad(img, quad) >= QUAD_MIN_CELLS:
                chosen = quad
                break
        if chosen is None:
            return {"ok": False, "reason": "未检测到草稿界面（绿角标/大招区验证失败）"}

        results, slot_extras, bodies = self._classify_quad(img, chosen)
        heroes, sources, cells = {}, {}, []
        for cls in results:
            if cls is None:
                cells.append(None)
                continue
            a, v = cls
            hid = a.owner_hero_id
            hero = self.snap.hero(hid) if hid else None
            cells.append({"ability": a.english_name, "score": round(v, 3),
                          "hero": hero.english_name if hero else None,
                          "heroId": hid, "locked": v >= ULT_LOCK})
            if hid and v >= ULT_WEAK and (hid not in heroes or v > heroes[hid]):
                heroes[hid] = v
                sources.setdefault(hid, set()).add("ult" if v >= ULT_LOCK else "ult?")
        ult_count = sum(1 for s in sources.values() if "ult" in s)
        # 大招格二次分类（小招占位）：其主人加入
        for a, v in slot_extras:
            hid = a.owner_hero_id
            if hid:
                sources.setdefault(hid, set()).add("slot")
                heroes[hid] = max(heroes.get(hid, 0), v)
        # 身板证据：确认已有英雄用 0.70；单独引入新英雄需 0.85（防杂讯吸铁石）
        for hid, v in bodies.items():
            if hid in heroes:
                sources[hid].add("body")
                heroes[hid] = max(heroes[hid], v)
            elif v >= BODY_SOLO:
                sources.setdefault(hid, set()).add("body")
                heroes[hid] = v
        ranked = sorted(heroes.items(), key=lambda kv: -kv[1])
        return {
            "ok": True,
            "heroIds": [h for h, _ in ranked],
            "heroes": [self.snap.hero(h).english_name for h, _ in ranked],
            "lockedCount": ult_count,
            "bodyCount": len(bodies),
            "sources": {str(h): sorted(sources.get(h, [])) for h, _ in ranked},
            "cells": cells,
        }
