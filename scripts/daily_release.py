"""发布端每日任务：拉 windrun（仅此一处联网碰官方）→ 打包 → 待同步。

    python scripts/daily_release.py

链路：fetch_snapshot（有变化才继续）→ export_web_bundle → download_icons（增量）→ publish_update

Windows 计划任务注册（发布机上执行一次，每天 09:00 跑）：
    schtasks /Create /TN "ad-draft-daily-release" /SC DAILY /ST 09:00 ^
      /TR "python E:\\闲聊\\ad-draft-agent\\scripts\\daily_release.py"
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(script: str) -> int:
    print(f"\n=== {script} ===")
    return subprocess.call([sys.executable, str(ROOT / "scripts" / script)], cwd=str(ROOT))


def main():
    if run("fetch_snapshot.py") != 0:
        print("快照拉取失败，中止")
        return 1
    for script in ("export_web_bundle.py", "download_icons.py", "publish_update.py"):
        if run(script) != 0:
            print(f"{script} 失败，中止")
            return 1
    print("\n每日发布完成。把 dist/ 同步到托管即完成推送（或在托管机直接跑本脚本）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
