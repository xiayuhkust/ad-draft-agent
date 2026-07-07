// 从 web/index.html 抽出草稿引擎段，在 Node 里跑 200 局全 AI 草稿验证规则。
// 用法: node scripts/test_web_engine.js
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf-8");
const bundleJs = fs.readFileSync(path.join(root, "web/data/bundle.js"), "utf-8");

const script = html.split(/<script>|<\/script>/).find(s => s.includes("草稿引擎"));
const engine = script.slice(0, script.indexOf("// ---------- UI ----------"));

const testBody = `
let violations = 0;
for (let game = 0; game < 200; game++) {
  newGame(0);
  while (G.pickNo < 50) {
    const p = G.players[G.order[G.pickNo]];
    const id = aiPick(p);
    if (id === null) { console.log("死锁 @game " + game + " pick " + G.pickNo); process.exit(1); }
    if (!isLegal(p, id)) { console.log("非法选取 @game " + game); process.exit(1); }
    applyPick(p, id);
  }
  for (const p of G.players) {
    if (!(p.body !== null && p.abs.length === 4 && ultCount(p) === 1)) violations++;
  }
  if (G.pool.size !== 10) violations++;
}
console.log("200 局 JS 引擎草稿: 约束违规 = " + violations);

// 手动选池模式：指定 12 英雄开局
const manualIds = new Set(window.AD_BUNDLE.heroes.slice(0, 12).map(h => h.id));
newGame(3, manualIds);
if (G.heroes.length !== 12) { console.log("手动选池英雄数错误: " + G.heroes.length); process.exit(1); }
while (G.pickNo < 50) {
  const p = G.players[G.order[G.pickNo]];
  applyPick(p, aiPick(p));
}
const manualOk = G.players.every(p => p.body !== null && p.abs.length === 4 && ultCount(p) === 1);
console.log("手动选池 12 英雄一局: " + (manualOk ? "通过" : "违规"));

// 极端补位：12 个特殊英雄（无大招/普通技不足3），全靠局外补位也要能满额成局
const specialIds = new Set([5, 10, 34, 40, 42, 49, 60, 74, 76, 82, 84, 113]);
newGame(0, specialIds);
if (G.heroes.length !== 12) { console.log("特殊英雄池英雄数错误: " + G.heroes.length); process.exit(1); }
const ultsInPool = [...G.pool].filter(id => id > 0 && window.AD_BUNDLE.entries.find(e => e.id === id).u).length;
if (ultsInPool !== 12) { console.log("特殊英雄池大招数错误: " + ultsInPool); process.exit(1); }
while (G.pickNo < 50) {
  const p = G.players[G.order[G.pickNo]];
  applyPick(p, aiPick(p));
}
const specialOk = G.players.every(p => p.body !== null && p.abs.length === 4 && ultCount(p) === 1);
console.log("12 特殊英雄补位一局: " + (specialOk ? "通过" : "违规"));

newGame(0);
let with2 = 0, total = 0;
for (const id of G.pool) {
  if (id < 0) continue;
  total++;
  if (bestPairInPool(id)) with2++;
}
console.log("开局池内技能框2覆盖率: " + with2 + "/" + total);
`;

const window = {};
eval(bundleJs + "\n" + engine + "\n" + testBody);
