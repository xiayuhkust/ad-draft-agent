# Dota 2 对局数据来源研究

> 2026-07-14 整理。回答三个问题：本项目每一份数据从哪来；哪些属于 Dota 官方、哪些来自 windrun；生态里还有哪些可用的数据源。

## 1. 我们的数据流水线

```
windrun.io API ──┐
Valve 官方 CDN ──┼─→ data/snapshot/ + web/img/ ─→ export_web_bundle.py ─→ web/data/bundle.js
OpenDota 常量 ───┘         （每日快照）                                        │
                                                                             ├─→ 网页版（CloudBase /ad）
                                                                             └─→ 盒子（识别模板 + 面板数据）
```

- `scripts/fetch_snapshot.py`：每日定时拉 windrun 六个端点，内容有变化才发布新快照
- `scripts/download_icons.py`：从 Valve CDN 下载英雄/技能图标（出新英雄才有增量）
- `scripts/export_web_bundle.py`：瘦身合并为前端数据包，并从 OpenDota 常量补英雄主属性

## 2. 当前数据分类明细

### 来自 windrun.io（第三方，非官方）—— 全部对局统计

| 快照文件 | windrun 端点 | 内容 | 项目中的用途 |
|---|---|---|---|
| `abilities.json` | `/api/v2/abilities` | 每个技能/身板的胜率、场次、平均被抢手数(avgPickPosition)、估值 | 格子胜率、池内顺位、AI 选取 |
| `ability_pairs.json` | `/api/v2/ability-pairs` | 头部约 7500 个技能两两组合的胜率/场次 | 配对推荐（★/○ 三行） |
| `ability_high_skill.json` | `/api/v2/ability-high-skill` | 高分段子集的技能胜率 | 详情页"高分段"数字 |
| `heroes.json` | `/api/v2/heroes` | 英雄身板整体战绩 | 身板格胜率 |
| `static_abilities.json` | `/api/v2/static/abilities` | 技能表：id、名称、是否大招、归属英雄、tooltip | 池构建、识别结果映射 |
| `static_heroes.json` | `/api/v2/static/heroes` | 英雄表：id、英文名、shortName | 全部英雄索引 |

说明：
- 两个 static 表描述的其实是 Valve 游戏本体数据（技能归属、大招标记），但我们是**经 windrun 转手**拿到的，windrun 对 AD 特有的改动（如卡尔的 AD 版小招、不可征召技能的剔除）已经处理好，这正是选它的原因。
- windrun 自称覆盖 **2500 万+ AD 对局**，是 AD 领域事实上的权威统计站；其上游数据来源未公开文档化（FAQ 页有 Cloudflare 防护），业界通行做法是基于 Valve 公开对局数据（Steam Web API / 录像解析）自建管线，windrun 应属此类。
- 它没有官方公开 API，我们用的 `api.windrun.io/api/v2` 是其网页自用接口——所以抓取器刻意做了最小化（每端点每天 1 次、1.5s 间隔、带浏览器 UA、内容不变不发布），客户端永远读我们的快照而不直连 windrun。
- 约束：配对表只有头部 7500 对（缺失 ≠ 不强）；小样本组合需要 `num_picks ≥ 200` 门槛过滤（MIN_N）。

### 来自 Valve 官方

| 数据 | 来源 | 项目中的用途 |
|---|---|---|
| 全部英雄/技能图标 PNG | `cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/`（Dota 2 官方素材 CDN） | 网页/盒子界面显示；**识别引擎的模板库**（636 张模板全部来自官方图标） |

即：我们的截图识别之所以能工作，是因为拿官方原图做模板匹配，游戏内渲染的就是同一批素材。

### 来自 OpenDota（第三方开源项目，数据派生自 Valve 游戏文件）

| 数据 | 来源 | 项目中的用途 |
|---|---|---|
| 英雄主属性 (str/agi/int/all) | `raw.githubusercontent.com/odota/dotaconstants`（OpenDota 从 Valve 游戏文件编译的常量库） | 手动选池界面按主属性分组（`data/hero_attrs.json` 本地缓存，只拉一次） |

### 不联网的"数据"

| 数据 | 来源 | 项目中的用途 |
|---|---|---|
| AD 规则（12 英雄池、补位规则、最多 1 个无大招英雄、蛇形选取） | Liquipedia / Fandom wiki 的规则描述 + 实战验证，硬编码在 `addraft/draft.py` 与网页引擎里 | 模拟开局与合法性判定 |
| 本项目的 house rules（1 身板 + 4 技能、恰好 1 大招） | 用户自定（2026-07-04） | 草稿引擎约束 |

## 3. Dota 对局数据生态全景

### Valve 官方渠道

| 渠道 | 内容 | 对 AD 的适用性 |
|---|---|---|
| **Steam Web API**（`api.steampowered.com`，免费申请 key） | 每场公开对局的基础数据：玩家、英雄、KDA、技能加点(ability_upgrades) | 有 AD 模式对局记录，但**不直接给出"谁征召了哪些技能"**，需从加点序列反推，且不含选人过程 |
| **对局录像 .dem 文件**（Valve 回放服务器） | 最完整的原始数据，包含 AD 选人全过程 | 用 clarity/manta 等解析器可还原每一手征召；成本高（每场几十 MB + CPU 解析），windrun/OpenDota 的深度数据都源于此 |
| **Game Coordinator**（模拟客户端协议，如 node-dota2） | 实时对局、个人资料 | 可查进行中对局，但接口非正式、易变 |
| **GSI（Game State Integration）** | 本地客户端实时推送游戏状态（金钱、技能、物品……） | 观战/赛事模式才有完整草稿信息；**普通玩家自己打 AD 时选人界面数据不暴露**——这就是盒子必须走截图识别的原因 |
| **游戏文件（vpk）** | 技能/英雄的全部静态定义 | dotaconstants 等常量库的上游；自己解包可拿到最原始的技能表 |
| **官方素材 CDN** | 英雄/技能图标、录像小地图素材 | 我们已在用（图标+识别模板） |

### 第三方数据平台

| 平台 | 数据来源 | API | 对 AD 的适用性 |
|---|---|---|---|
| **windrun.io** | 自建管线（基于 Valve 公开对局数据） | 无官方 API（网页自用接口） | **AD 专门站，唯一提供技能胜率/配对/顺位统计的来源**，我们的核心依赖；同类工具 Ability Draft Plus 也抓它 |
| **OpenDota** | Steam Web API + 自动录像解析，开源 | 免费 REST API（有速率限制），付费可提额 | 通用对局查询好用；AD 只是普通模式之一，无技能征召专项统计；可查个人 AD 战绩 |
| **STRATZ** | Steam Web API + Clarity 录像解析 | 免费 GraphQL API（需 key） | 数据维度最全的通用平台，有草稿/技能/出装分析；AD 模式对局可查询，但同样没有 windrun 式的征召组合统计 |
| **Dotabuff** | 自建（同源 Valve 数据） | 无公开 API | 网页查询为主，对我们没有可编程价值 |
| **datdota** | 职业比赛录像 | 无 | 只覆盖职业赛，AD 无关（其域名下的 abilitydraft 子站实为 windrun 的排行榜镜像） |
| **dota2protracker** | 高分/职业路人 | 无公开 API | 天梯 meta 站，无 AD |
| **Ability Draft Plus / HGV 等工具** | 抓 windrun / 官方素材 | — | 同类竞品，验证了"windrun + 官方图标模板识别"这条路线是业界共识 |

## 4. 结论与机会

1. **现状健康**：统计数据只有 windrun 一家可用（也是全生态唯一的 AD 专项统计源），我们已用快照层把它隔离——windrun 挂了/改版了，玩家端不受影响，只是数据不再更新。
2. **单点依赖风险**：windrun 无 SLA、接口随时可能改。缓解手段：快照有版本历史（git），接口变了改 `fetch_snapshot.py` 一处即可；极端情况下可退路到"自建录像解析管线"（STRATZ/OpenDota 证明技术可行，但成本远超当前收益）。
3. **可以补充的来源**（按性价比）：
   - **STRATZ/OpenDota 个人战绩**：输入 Steam ID 拉自己的 AD 历史战绩，做"我的 AD 生涯"面板——免费 API 就够。
   - **自录对局数据库**（配合腾讯云）：盒子识别结果 + 赛后手动标胜负，攒小组自己的组合胜率，弥补 windrun 配对表 7500 对之外的缺口。
   - **录像解析**：想要"每一手谁抢了什么"的精确复盘时的终极手段，建议等小组数据库证明有需求后再投入。
4. **GSI 无法替代截图识别**（普通局不暴露选人数据），当前的模板匹配方案仍是正确路线。

## 参考链接

- windrun.io：https://windrun.io/
- OpenDota core（数据来源说明）：https://github.com/odota/core
- OpenDota dotaconstants：https://github.com/odota/dotaconstants
- STRATZ API：https://stratz.com/api
- Ability Draft Plus（同类工具，windrun 数据）：https://github.com/Tiarin-Hino/ability-draft-plus/
- Valve Steam Web API：https://dev.dota2.com/ / https://api.steampowered.com
- Liquipedia Ability Draft 规则：https://liquipedia.net/dota2game/Ability_Draft
