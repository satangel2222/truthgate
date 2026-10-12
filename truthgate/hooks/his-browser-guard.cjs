#!/usr/bin/env node
// PreToolUse 守卫：护住【Frank 已登录的浏览器】,禁止我征用或杀掉。
//
// 由来(2026-08-20 Frank 亲口):「全局铁律不得动我9226的浏览器,我那个是专为 openclaw obsidian
// 跨项目抓知识库的。修正你可以给我登入画面我去登入」
// 前科(lessons 2790-2813):2026-08-12 我把一台【只是慢了 17 秒、还活着】的 9226 当孤儿
// `taskkill /F` 掉,害他掉登录;而且我当时拿 `curl /json/version` 的 200 当"健康"证据一路报绿。
//
// 先查现成(2026-08-20):本机 anti-playwright-guard.cjs 目的相反(它反而推荐 connectOverCDP
// 接管真实 Chrome);GitHub karanb192/claude-code-hooks ★481 六个 safety hook 全是
// 文件/git/secrets 向,不覆盖进程终止与 CDP 端口 ⇒ 只能自建。
//
// 拦两类动作(都是【写/生命周期】操作):
//   ① 征用:connectOverCDP / connect_over_cdp / 抢占 --remote-debugging-port=9226|9555
//   ② 杀:taskkill/Stop-Process/kill/pkill 指向 9226|9555,或【无差别】杀 chrome.exe
//      (无差别杀会连他所有已登录浏览器一起带走——这正是我上次伤到 9226 的方式)
// 放行:纯只读观察(netstat / curl /json/version / Get-CimInstance / Get-Process)——
//      我仍然需要能诊断,只是不能动手。也放行显式标记 `# his-browser-ok`。
//
// 退出码 2 = 阻断(stderr 回灌给模型);退出码 0 = 放行。
const fs = require('fs');

let raw = '';
try { raw = fs.readFileSync(0, 'utf8'); } catch { process.exit(0); }
let data = {};
try { data = JSON.parse(raw); } catch { process.exit(0); }

const tool = data.tool_name || '';
if (tool !== 'Bash' && tool !== 'PowerShell') process.exit(0);
const cmd = ((data.tool_input && data.tool_input.command) || '').toString();
if (!cmd) process.exit(0);

// 显式放行（他当面授权过这一次，或确属误判）
if (/#\s*his-browser-ok/i.test(cmd)) process.exit(0);

// 本机 CDP 端口归属（2026-08-20 实测 + dev-diary/SKILL.md 佐证）：
//   9226 = openclaw/obsidian 知识库跨项目抓取  → ⛔ 绝对禁止(Frank 亲口)
//   9555 = bananaflow(AI 生图 TG Bot)          → ⛔ 拦；跑 bananaflow skill 本身才算正当，加标记
//   9333 = dev-diary 发小红书专用              → ✅ 不拦：它就是【为自动化建的】，程序连它是本职
//   9334 = dev-diary deepseek 专用             → ✅ 不拦：同上
// ⚠️ 别把 9333/9334 一起拦了——它们跟 9226/9555 只是"看起来同类"，性质相反：
//    前两个是【别的系统正在用】，后两个是【专门开给我连的】。拦了会废掉他的 dev-diary。
const HIS_PORTS = /\b(?:9226|9555)\b/;

// ① 征用他的浏览器
const HIJACK = /connectOverCDP|connect_over_cdp|--remote-debugging-port\s*=?\s*(?:9226|9555)/i;
// ② 杀进程类动作
const KILL = /\btaskkill\b|\bStop-Process\b|\bpkill\b|\bkillall\b|\bkill\s+-?\d|\.kill\(/i;
// ③ 无差别杀 chrome（不带 PID，直接按镜像名/进程名扫射）
const CHROME_WIPE =
  /taskkill[^\n]*\/IM\s+["']?chrome(?:\.exe)?|Stop-Process[^\n]*-Name\s+["']?chrome|pkill[^\n]*\bchrome\b|killall[^\n]*\bchrome\b/i;

let hit = null;
if (HIS_PORTS.test(cmd) && HIJACK.test(cmd)) hit = '征用 9226/9555（他已登录的浏览器）';
else if (HIS_PORTS.test(cmd) && KILL.test(cmd)) hit = '杀 9226/9555 上的浏览器';
else if (CHROME_WIPE.test(cmd)) hit = '无差别杀 chrome.exe（会连他已登录的浏览器一起带走）';

if (hit) {
  const reason =
    '🚫 护他浏览器闸拦截 [' + hit + ']\n' +
    '⛔ 9226 = openclaw/obsidian 知识库跨项目抓取专用；9555(bananaflow)同理。opencli 不在此列，可正常用。\n' +
    '   这些是【他的资产】，不是可征用的工具。前科：2026-08-12 我 taskkill 了一台只是慢了 17 秒、\n' +
    '   还活着的 9226，害他掉登录。判定「孤儿/僵尸/没响应」也不动它——只报告。\n' +
    '\n' +
    '✅ 需要登录态时的正确做法（他的原话：「你可以给我登入画面我去登入」）：\n' +
    '   0. 先用 opencli 复用他已登录的浏览器（开自己的 session，不动别人的标签）；不行才：\n' +
    '   1. 自己起一个实例：独立 user-data-dir + 避开 9226/9555 的端口，绝不复用他的 profile；\n' +
    '   2. 打开登录页 → 截图 → 自己 Read 确认画面 → 打开给他看（Start-Process，别只贴路径）；\n' +
    '   3. 他登完我在同一个实例里继续干；登录态留我自己 profile，下次复用。\n' +
    '   只读诊断（netstat / curl /json/version / Get-CimInstance）不受本闸限制。\n' +
    '   详见 ~/.claude/browser-routing.md 顶部红线。\n' +
    '   （他当面授权了这一次，才可在命令里加 `# his-browser-ok`。）';
  try {
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: reason,
      },
    }));
  } catch (_e) {}
  process.stderr.write(reason + '\n');
  process.exit(2);
}
process.exit(0);
