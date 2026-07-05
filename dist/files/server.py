"""AD 陪练本地服务器：静态页 + 识别接口 + 手机推送状态。

用法：
    python server.py            # 默认 8080（与 Cloudflare 隧道对接的端口）
    python server.py 8090

接口：
    GET  /...               静态文件（web/ 目录）
    POST /api/recognize     body = 图片二进制（截图）→ 识别 → JSON；结果同时存为最新状态
    GET  /api/state         → {"seq": n, "result": {...}}  手机轮询，seq 变化即有新推送
"""

import json
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

from addraft.vision import Recognizer, imdecode_bytes
from addraft import updater

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def auto_update():
    """启动时后台检查更新：数据热更、代码提示重启。失败不影响本地运行。"""
    try:
        r = updater.check_and_update()
        if not r.get("enabled"):
            print("自动更新未启用（根目录放 update_url.txt 可开启）")
            return
        if r["updated"]:
            kind = "含代码，重启后生效" if r["codeChanged"] else "数据已热更生效"
            print(f"更新完成: {len(r['updated'])} 个文件（{kind}）"
                  f" → app {r['appVersion']} / data {r['dataVersion']}")
        else:
            print(f"已是最新: app {r['appVersion']} / data {r['dataVersion']}")
    except Exception as e:
        print(f"更新检查失败（继续本地运行）: {e}")

state_lock = threading.Lock()
state = {"seq": 0, "result": None, "at": None}

print("加载识别引擎（模板入内存）...")
recognizer = Recognizer()
print(f"就绪：{len(recognizer.t_ult)} 个大招模板")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):
        msg = args[0] if args else ""
        if "/api/" in msg and "/api/state" not in msg:  # 轮询不刷屏
            super().log_message(fmt, *args)

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            with state_lock:
                return self._json({"seq": state["seq"], "at": state["at"],
                                   "result": state["result"]})
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/recognize"):
            return self._json({"ok": False, "reason": "unknown endpoint"}, 404)
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 50 * 1024 * 1024:
            return self._json({"ok": False, "reason": "empty or oversized body"}, 400)
        data = self.rfile.read(length)
        img = imdecode_bytes(data)
        if img is None:
            return self._json({"ok": False, "reason": "无法解码图片"}, 400)
        t0 = time.time()
        result = recognizer.recognize(img)
        result["elapsedMs"] = int((time.time() - t0) * 1000)
        if result.get("ok"):
            with state_lock:
                state["seq"] += 1
                state["result"] = result
                state["at"] = time.strftime("%H:%M:%S")
            print(f"识别成功：锁定 {result['lockedCount']} 席 "
                  f"({result['elapsedMs']}ms) → {result['heroes']}")
        else:
            print(f"识别失败：{result.get('reason')}")
        return self._json(result)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    threading.Thread(target=auto_update, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"服务器启动: http://localhost:{port}  (静态目录: {WEB})")
    server.serve_forever()


if __name__ == "__main__":
    main()
