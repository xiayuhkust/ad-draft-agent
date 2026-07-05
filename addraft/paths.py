"""路径中枢：源码运行与 PyInstaller 冻结运行的统一出口。

- ROOT：资源根（web/、data/ 所在）。冻结时 = _internal（sys._MEIPASS）
- EXE_DIR：可执行文件旁（config.json、update_url.txt 放这，安装器好写入）
- IS_FROZEN：是否打包运行（更新器据此跳过代码文件——exe 里的 .py 改了也没用）
"""

import sys
from pathlib import Path

IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    ROOT = Path(sys._MEIPASS)          # noqa: SLF001 —— PyInstaller 运行时目录
    EXE_DIR = Path(sys.executable).parent
else:
    ROOT = Path(__file__).resolve().parent.parent
    EXE_DIR = ROOT
