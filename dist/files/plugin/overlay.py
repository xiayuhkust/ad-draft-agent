"""AD 盒子：置顶可拖动的悬浮识别面板（PC 端一体化入口）。

    python plugin/overlay.py

- 自动确保本地识别服务在跑（没有就拉起 server.py）
- 悬浮窗：无边框、置顶、宽 480，顶栏可拖动（布局同手机版面板）
- 识别触发：全局热键 Ctrl+Shift+O 或面板上的 📷 按钮
- 游戏建议使用"无边框窗口"模式（独占全屏可能截到黑屏/挡住悬浮窗）
"""

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hotkey_capture import capture_primary, send

ROOT = Path(__file__).resolve().parent.parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
BASE = f"http://localhost:{PORT}"

MOD_CONTROL, MOD_SHIFT = 0x0002, 0x0004
VK_O = 0x4F
WM_HOTKEY = 0x0312

FULL_H, FOLD_H = 820, 42
window = None


def server_alive() -> bool:
    try:
        urllib.request.urlopen(f"{BASE}/api/state", timeout=2)
        return True
    except Exception:
        return False


def ensure_server():
    if server_alive():
        return
    print("识别服务未运行，自动拉起 server.py ...")
    subprocess.Popen([sys.executable, str(ROOT / "server.py"), str(PORT)],
                     cwd=str(ROOT),
                     creationflags=subprocess.CREATE_NEW_CONSOLE)
    for _ in range(60):
        if server_alive():
            print("识别服务就绪")
            return
        time.sleep(1)
    raise RuntimeError("识别服务启动失败")


def do_capture():
    try:
        png = capture_primary()
        r = send(png, BASE)
        tag = f"锁定 {r.get('lockedCount')} 席" if r.get("ok") else r.get("reason")
        print(f"识别: {tag}")
    except Exception as e:
        print(f"识别出错: {e}")


class Api:
    def capture(self):
        threading.Thread(target=do_capture, daemon=True).start()

    def fold(self, folded):
        if window:
            window.resize(480, FOLD_H if folded else FULL_H)

    def close(self):
        if window:
            window.destroy()


def topmost_keeper():
    """周期性重申置顶：部分游戏窗口获得焦点时会抢层级。
    注意：独占全屏无解（绕过合成器），游戏需用无边框窗口模式。"""
    user32 = ctypes.windll.user32
    HWND_TOPMOST = -1
    FLAGS = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
    while True:
        hwnd = user32.FindWindowW(None, "AD 盒子")
        if hwnd:
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, FLAGS)
        time.sleep(2)


def hotkey_loop():
    user32 = ctypes.windll.user32
    if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_SHIFT, VK_O):
        print("热键 Ctrl+Shift+O 注册失败（可能被占用），仍可用面板按钮触发")
        return
    print("热键就绪: Ctrl+Shift+O")
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == WM_HOTKEY and msg.wParam == 1:
            do_capture()


def main():
    global window
    ensure_server()
    threading.Thread(target=hotkey_loop, daemon=True).start()
    threading.Thread(target=topmost_keeper, daemon=True).start()
    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
    window = webview.create_window(
        "AD 盒子", f"{BASE}/overlay.html",
        width=480, height=FULL_H,
        x=screen_w - 500, y=60,
        frameless=True, on_top=True, easy_drag=False,
        js_api=Api(),
    )
    webview.start()


if __name__ == "__main__":
    main()
