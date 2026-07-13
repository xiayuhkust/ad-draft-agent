"""AD 盒子：置顶可拖动的悬浮识别面板（PC 端一体化入口）。

    python plugin/overlay.py          # 源码运行
    ADBox.exe                         # 打包运行（安装版）

- 识别服务在本进程内以线程运行（已有外部服务在跑则直接复用）
- 快捷键可配置：exe 旁 config.json 的 "hotkey"（如 "ctrl+shift+o"、"f9"），
  安装器的快捷键选择页写的就是这个文件
- 游戏建议"无边框窗口"模式（独占全屏挡悬浮窗/截黑屏）
"""

import ctypes
import ctypes.wintypes as wt
import json
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# windowed exe 没有控制台：stdout/stderr 为 None，print 会崩 → 重定向到日志文件
if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
    _log = open(Path(sys.executable).parent / "adbox.log", "a",
                encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

import webview

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))          # hotkey_capture
sys.path.insert(0, str(_HERE.parent))   # addraft / server（源码运行时）

from addraft.paths import EXE_DIR
from hotkey_capture import capture_primary, send

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
BASE = f"http://localhost:{PORT}"
CONFIG_PATH = EXE_DIR / "config.json"

WM_HOTKEY = 0x0312
MODS = {"ctrl": 0x0002, "shift": 0x0004, "alt": 0x0001, "win": 0x0008}
FULL_W, FULL_H, FOLD_W, FOLD_H = 480, 820, 56, 42
window = None


def load_hotkey():
    """config.json 的 hotkey 字符串 → (修饰键位掩码, 虚拟键码, 显示名)。"""
    spec = "ctrl+shift+o"
    try:
        spec = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("hotkey", spec)
    except Exception:
        pass
    mods, vk = 0, None
    for part in spec.lower().replace(" ", "").split("+"):
        if part in MODS:
            mods |= MODS[part]
        elif len(part) == 1 and (part.isalpha() or part.isdigit()):
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 12:
            vk = 0x70 + int(part[1:]) - 1
    if vk is None:
        mods, vk, spec = MODS["ctrl"] | MODS["shift"], ord("O"), "ctrl+shift+o"
    return mods, vk, spec


def server_alive() -> bool:
    try:
        urllib.request.urlopen(f"{BASE}/api/state", timeout=2)
        return True
    except Exception:
        return False


def ensure_server():
    if server_alive():
        print("检测到已有识别服务，直接复用")
        return
    import server  # 首次导入即加载识别引擎（模板入内存）
    threading.Thread(target=server.serve, args=(PORT,), daemon=True).start()
    for _ in range(60):
        if server_alive():
            print("识别服务就绪（进程内线程）")
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

    def check_update(self):
        """手动检查更新（pywebview 每次调用独立线程，阻塞网络请求无妨）。"""
        from addraft import updater
        try:
            r = updater.check_and_update()
            r["ok"] = True
            return r
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    def open_url(self, url):
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)

    def fold(self, folded, w=None, h=None):
        # 尺寸由页面传入（随 web 热更可调）；老页面不传参则用内置默认
        if window:
            window.resize(w or (FOLD_W if folded else FULL_W),
                          h or (FOLD_H if folded else FULL_H))

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
    mods, vk, spec = load_hotkey()
    user32 = ctypes.windll.user32
    if not user32.RegisterHotKey(None, 1, mods, vk):
        print(f"热键 {spec} 注册失败（可能被占用），仍可用面板 📷 按钮触发")
        return
    print(f"热键就绪: {spec}")
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == WM_HOTKEY and msg.wParam == 1:
            do_capture()


# 启动过渡页：窗口先见人，加载进度/失败原因都在页内显示（慢机器上不再"没反应"）
BOOT_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>
body{background:#0d1117;color:#dce3ee;font:13px/1.6 system-ui,"Microsoft YaHei",sans-serif;
  margin:0;user-select:none;overflow:hidden}
#bar{display:flex;align-items:center;padding:8px 10px;background:#161d29;
  border-bottom:1px solid #2a3548;cursor:move}
#bar b{color:#e8b64a;flex:1}
#bar button{background:#1d2636;color:#dce3ee;border:1px solid #2a3548;border-radius:6px;
  padding:4px 9px;font:inherit;cursor:pointer}
#msg{padding:28px 18px;text-align:center;color:#8b98ac;line-height:2}
</style></head><body>
<div id="bar" class="pywebview-drag-region"><b>AD 盒子</b><button onclick="pywebview.api.close()">✕</button></div>
<div id="msg">正在加载识别引擎…<br>首次启动或更新后会慢一些，请稍候</div>
</body></html>"""


def boot():
    """GUI 起来后再做耗时初始化；任何失败都写回过渡页，窗口始终可见可关。"""
    threading.Thread(target=topmost_keeper, daemon=True).start()
    try:
        ensure_server()
    except Exception as e:
        msg = json.dumps(f"启动失败：{e}。请检查网络/端口占用后关闭重试")
        window.evaluate_js(f'document.getElementById("msg").textContent = {msg}')
        return
    threading.Thread(target=hotkey_loop, daemon=True).start()
    window.load_url(f"{BASE}/overlay.html")


def main():
    global window
    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
    window = webview.create_window(
        "AD 盒子", html=BOOT_HTML,
        width=FULL_W, height=FULL_H,
        x=screen_w - 500, y=60,
        frameless=True, on_top=True, easy_drag=False,
        js_api=Api(),
    )
    webview.start(boot)


if __name__ == "__main__":
    main()
