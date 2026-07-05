"""PC 热键插件：Ctrl+Shift+O 全屏截图 → 本地识别服务 → 手机页自动切入。

用法（先启动 server.py）：
    python plugin/hotkey_capture.py            # 默认发到 http://localhost:8080
    python plugin/hotkey_capture.py 8090       # 自定义端口

依赖：pip install mss（截屏）；热键用 Win32 RegisterHotKey（纯 ctypes，无需额外库）。
注意：游戏用无边框窗口模式截屏最稳；独占全屏在部分机器截到黑屏。
"""

import ctypes
import ctypes.wintypes as wt
import io
import json
import sys
import urllib.request

import mss
import mss.tools

MOD_CONTROL, MOD_SHIFT = 0x0002, 0x0004
VK_O = 0x4F
WM_HOTKEY = 0x0312
HOTKEY_ID = 1


def capture_primary() -> bytes:
    with mss.mss() as sct:
        mon = sct.monitors[1]  # 主显示器
        shot = sct.grab(mon)
        return mss.tools.to_png(shot.rgb, shot.size)


def send(png: bytes, base: str) -> dict:
    req = urllib.request.Request(
        f"{base}/api/recognize", data=png,
        headers={"Content-Type": "image/png"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8080"
    base = f"http://localhost:{port}"
    user32 = ctypes.windll.user32
    if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT, VK_O):
        print("热键注册失败（Ctrl+Shift+O 可能被其他程序占用）")
        return
    print(f"就绪：游戏中按 Ctrl+Shift+O 截屏识别 → {base}")
    print("（手机页面开着\"待命\"即可自动收到结果；Ctrl+C 退出）")

    msg = wt.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                print("截屏中...", flush=True)
                try:
                    png = capture_primary()
                    r = send(png, base)
                    if r.get("ok"):
                        print(f"  ✓ 锁定 {r['lockedCount']} 席 "
                              f"({r.get('elapsedMs')}ms): {', '.join(r['heroes'])}")
                    else:
                        print(f"  ✗ {r.get('reason')}")
                except Exception as e:
                    print(f"  ✗ 出错: {e}")
    finally:
        user32.UnregisterHotKey(None, HOTKEY_ID)


if __name__ == "__main__":
    main()
