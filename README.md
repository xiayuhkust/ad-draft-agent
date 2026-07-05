# AD 陪练 / AD 盒子

Dota 2 技能征召（Ability Draft）辅助工具集，数据来自 [windrun.io](https://windrun.io) 每日快照。

## 功能

- **草稿陪练**（`web/index.html`）：随机 12 英雄，与 9 个 AI 轮抽练手感；助手开关显示技能胜率与最佳配对
- **AD 盒子**（`plugin/overlay.py`）：游戏内置顶悬浮面板。选人界面按 `Ctrl+Shift+O` 截屏，
  1 秒内自动识别本局英雄池，展示每个英雄的身板/技能胜率与池内最佳配对
- **识别引擎**（`addraft/vision.py`）：绿角标定位 → 透视矫正 → 大招格分类，任意分辨率/宽高比通用

## 玩家使用

**方式一（推荐）：安装包** —— 从 [Releases](https://github.com/xiayuhkust/ad-draft-agent/releases)
下载 `ADBox-Setup-x.x.x.exe`，安装向导里可选快捷键与开机启动（默认关闭）。
安装后数据每日自动热更；程序新版本需下载新安装包（面板会提示）。

**方式二：源码运行**

```
pip install mss pywebview opencv-python-headless
python plugin/overlay.py        # 自动拉起本地服务并打开悬浮面板
```

- 游戏需使用**无边框窗口**模式（独占全屏盖不上悬浮窗）
- 陪练页：浏览器打开 http://localhost:8080

## 自动更新

根目录创建 `update_url.txt`，内容一行：

```
https://cdn.jsdelivr.net/gh/xiayuhkust/ad-draft-agent@main/dist
```

启动时自动增量更新数据（热更）与代码（重启生效）。删除该文件即回到纯本地模式。

## 数据说明

- 统计数据来自 windrun.io（Ability Draft 天梯统计），由发布端每日抓取一次、经本仓库分发，
  玩家端不直接访问 windrun，不给源站造成压力
- 英雄属性来自 OpenDota dotaconstants；图标来自 Valve CDN

## 致谢

- [windrun.io](https://windrun.io)（Noxville）— AD 统计数据
- [ability-draft-plus](https://github.com/Tiarin-Hino/ability-draft-plus)（ISC）— 布局坐标参考
