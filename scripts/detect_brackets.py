"""实验：检测终极技能区的 4 个绿色角标（游戏 UI 自带的"引号"）。

思路：饱和亮绿在暗色 UI 里非常突出 → HSV 阈值 → 连通域 →
按几何关系（2 上 2 下、构成凸四边形）选出 4 个角标。
输出调试图：_mask（绿色掩码）、_corners（角标定位结果）。
"""

import sys
from pathlib import Path

import cv2
import numpy as np


def imread_u(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def imwrite_u(path, img):
    ok, buf = cv2.imencode(Path(path).suffix, img)
    if ok:
        buf.tofile(str(path))


def green_mask(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 亮绿：H 40-85（OpenCV 0-180 制），高饱和、中高亮度
    mask = cv2.inRange(hsv, (40, 80, 90), (85, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return mask


def find_bracket_corners(img, debug_prefix=None):
    mask = green_mask(img)
    if debug_prefix:
        imwrite_u(f"{debug_prefix}_mask.jpg", mask)

    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    h_img, w_img = mask.shape
    img_area = h_img * w_img
    # 面积过滤用相对量（角标在 real1/shot1 实测约占全图 1.6e-5 ~ 7.6e-5），分辨率无关
    area_min, area_max = img_area * 8e-6, img_area * 6e-4
    cands = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < area_min or area > area_max:
            continue
        if w > w_img * 0.1 or h > h_img * 0.1:  # 排除大片绿色（面板等）
            continue
        cands.append({"cx": centroids[i][0], "cy": centroids[i][1],
                      "x": x, "y": y, "w": w, "h": h, "area": area})
    return mask, cands


def main():
    for name in sys.argv[1:]:
        p = Path(name)
        img = imread_u(p)
        prefix = str(p.with_name(p.stem))
        mask, cands = find_bracket_corners(img, prefix)
        print(f"\n{p.name}  {img.shape[1]}x{img.shape[0]}  绿色小连通域 {len(cands)} 个:")
        for c in sorted(cands, key=lambda c: (c["cy"], c["cx"]))[:30]:
            print(f"  ({c['cx']:.0f},{c['cy']:.0f}) 尺寸 {c['w']}x{c['h']} 面积 {c['area']}")
        vis = img.copy()
        for c in cands:
            cv2.rectangle(vis, (c["x"] - 4, c["y"] - 4),
                          (c["x"] + c["w"] + 4, c["y"] + c["h"] + 4), (0, 0, 255), 3)
        imwrite_u(prefix + "_corners.jpg", vis)
        print(f"  调试图: {prefix}_mask.jpg / {prefix}_corners.jpg")


if __name__ == "__main__":
    main()
