#!/usr/bin/env node
// PreToolUse 守卫：拦截"对登录墙站的裸 launch"(Playwright/Puppeteer/Selenium 新指纹)。
// 登录墙站(X/抖音/小红书/微博/Google/TikTok/IG)用裸 launch 自动化 → 封号(X 永久)。安全做法是
// connectOverCDP 接管真实 Chrome(webdriver=false)。本守卫由 harness 在工具执行前运行,命中即拒绝——
// 不依赖模型"记不记得规矩"。覆盖直接命令 + node/python 脚本里藏的 launch。
//
// ⚠️ 只拦"launch + 命中登录墙域名"。本地测试(localhost)/截图/启动自己项目的 launch 一律放行,不误拦。
// 放行：无真实 launch(纯 CDP 接管/只读)、导航目标非登录墙站(或只到 localhost)、或显式标记 `# antiscraping-ok`。
// 退出码 2 = 阻断（stderr 回灌给模型）；退出码 0 = 放行。
const fs = require('fs');
const path = require('path');

let raw = '';
try { raw = fs.readFileSync(0, 'utf8'); } catch { process.exit(0); }
let data = {};
try { data = JSON.parse(raw); } catch { process.exit(0); }

const tool = data.tool_name || '';
if (tool !== 'Bash' && tool !== 'PowerShell') process.exit(0);
const cmd = ((data.tool_input && data.tool_input.command) || '').toString();
if (!cmd) process.exit(0);

// 显式放行（人/我已确认走 CDP 或确属安全）
if (/#\s*antiscraping-ok|anti-scraping-ok/i.test(cmd)) process.exit(0);

// 只匹配"真正的 launch 调用",不匹配裸库名(puppeteer/playwright/selenium 作为 grep 搜索词/
// 注释/npm 包名/路径都不该拦——那些零封号风险)。launch 才是新指纹开真浏览器的危险动作。
const LAUNCH = /(?:chromium|firefox|webkit|puppeteer)\s*\.\s*launch\b|\.\s*launchPersistentContext\b|webdriver\s*\.\s*(?:Chrome|Firefox|Edge)\s*\(|new\s+Builder\s*\(/i;
// 封号只发生在"裸 launch 去登录墙站"。本地测试(localhost)/截图/启动自己项目的 launch 零封号风险,
// 一律放行——只有 launch + 登录墙域名【作为真实导航目标】时才拦(误拦本地开发是之前的核心 bug)。
// 收尾 \b 防短域名前缀误匹配：没有它 `t\.co` 会命中本地的 t.config/t.count、`x\.com` 会命中 x.compile。
const DANGER = /\b(?:x\.com|twitter\.com|t\.co|douyin\.com|iesdouyin|xiaohongshu\.com|xhslink|xhscdn|weibo\.(?:com|cn)|accounts\.google|myaccount\.google|tiktok\.com|instagram\.com|facebook\.com|linkedin\.com)\b/i;
const LOCALHOST = /\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|host\.docker\.internal)\b/i;
// 导航/连接调用的触发词(goto/navigate/get/url/href/window.open/connectOverCDP)。定位后由 navBlocks
// 按【括号深度】手动切出【单条调用】的实参——不用定长正则窗(旧 `[^;{}]{0,160}`)一把抓。定长窗跨行
// 会把下一条语句的串误吞进同一块:localhost 的 goto 吞掉下一行的登录墙域名 → 误拦本地测试(Python/无分号);
// 或把两条 goto 并进一块 → 判错首要目标。按【语句/括号】切分才对齐"真实导航目标"。
const NAV_TRIG = /\.\s*goto|\.\s*navigate|\.\s*to\b|\.\s*get\b|\.\s*url\b|location\s*\.\s*href|window\s*\.\s*open|connectOverCDP|connect_over_cdp/gi;
// 强导航触发词(真会开新页):变量藏毒(dvars)只在这些块里查引用,别跑到弱触发词 .to/.get/.url 上——
// 它们撞 chai 断言 .to.include(VAR)/page.url().to.contain(VAR),把只用于断言的外链变量误判成导航目标(安全侧过拦)。
// 字面量危险域名仍由下面 targets 的 'danger' 检查在【全部】触发块上覆盖,不漏拦。
// 含 .get(Selenium driver.get(url) 是真导航,变量藏毒经它不能漏拦=X封号不可逆);只排除 .to/.url(纯 chai 断言撞词)。
const STRONG_NAV = /^\s*(?:\.\s*goto|\.\s*navigate|\.\s*get\b|window\s*\.\s*open|location\s*\.\s*href|connectOverCDP|connect_over_cdp)/i;
// 从每个触发词起,读到该调用的语句边界:遇 `{`/`}` 立停;`(`/`[` 记深度;括号【外】的 `;`/换行 = 语句结束。
// 这样多行单 goto 的实参(goto(\n 'x.com'\n))整块留住,而 goto('localhost')\n<别的语句> 不再被并吞。
const navBlocks = (t) => {
  const out = [];
  for (let m; (m = NAV_TRIG.exec(t)); ) {
    let i = m.index + m[0].length, depth = 0, buf = m[0];
    for (let n = 0; i < t.length && n < 200; i++, n++) {
      const ch = t[i];
      if (ch === '{' || ch === '}') break;
      if (ch === '(' || ch === '[') depth++;
      else if (ch === ')' || ch === ']') depth = Math.max(0, depth - 1);
      else if ((ch === ';' || ch === '\n') && depth <= 0) break;
      buf += ch;
    }
    out.push(buf);
  }
  return out;
};
// 把 launch/域名关联到【同一次导航调用】,而非对整块内容子串匹配——堵审计确认的洞:
//  ① 漏报(旧 !SAFE 整块豁免):CDP 字样出现在死代码/注释里,不再豁免真正的裸 launch。
//     纯 CDP 接管脚本没有 .launch( → LAUNCH 不命中,本就放行,故无需整块 SAFE 白名单。
//  ② 误报:只导航 localhost 的本地脚本,即便无关地出现登录墙域名(fixture/注释/分享链接)也不再被拦。
//  ③ 漏报(变量藏毒):const LOGIN='https://x.com'; goto(LOGIN) —— 危险域名经变量/拼接喂给导航,仍要拦。
// ponytail: 关键字+括号切分的启发式;完全动态构造的目标(goto(fn()))仍可能漏——旧实现也漏,有 `# antiscraping-ok` 兜底。
const isFlagged = (t) => {
  if (!LAUNCH.test(t) || !DANGER.test(t)) return false;
  const nav = navBlocks(t);
  // 每块的"首要目标"= 触发词后【最先出现】的 URL:危险域名先出现=登录墙导航;localhost 先出现=本地。
  // 即便捕获窗仍并入了尾随串,也按【谁先】判真实目标(goto('localhost')…'fb'→本地;goto('x.com')…'localhost'→危险)。
  const target = (c) => {
    const d = c.search(DANGER), l = c.search(LOCALHOST);
    if (d >= 0 && (l < 0 || d < l)) return 'danger';
    if (l >= 0) return 'local';
    return 'other';
  };
  const targets = nav.map(target);
  if (targets.includes('danger')) return true;     // 有导航块以登录墙域名为首要目标 → 必拦(死 CDP/注释救不了)
  // 危险域名藏在变量里再被导航到(const LOGIN='https://x.com'; goto(LOGIN) / BASE='...'; goto(BASE+'/login'))。
  // 找出被赋危险域名字面量的变量名,若它落在某个【非 localhost】导航块内 → 危险域名是真实导航目标 → 拦。
  // 纯数据里的危险域名(expected='...fb...',从不喂给导航)变量名不落在导航块 → 不拦,不误伤本地 e2e。
  const dvars = [];
  const AS = /([A-Za-z_$][\w$]*)\s*[:=]\s*[`'"][^`'"\n]*/g;
  for (let m; (m = AS.exec(t)); ) if (DANGER.test(m[0])) dvars.push(m[1]);
  if (dvars.length && nav.some((c, i) => targets[i] !== 'local' && STRONG_NAV.test(c) &&
        dvars.some((v) => new RegExp('(?:^|[^\\w$])' + v.replace(/\$/g, '\\$') + '(?![\\w$])').test(c))))
    return true;
  if (targets.includes('local')) return false;     // 导航去 localhost、无危险目标 → 放行(本地测试)
  return true;                                      // 有 launch+危险域名但无本地导航证据 → 保守拦(漏报方向危险)
};

// git-bash 路径 /e/x -> e:/x，供 Windows node 解析
const winPath = (p) => {
  if (!p) return p;
  const m = String(p).match(/^\/([a-zA-Z])\/(.*)$/);
  return m ? m[1] + ':/' + m[2] : String(p);
};

let hit = null;
// 命令里直接内联 launch（如 node -e '...chromium.launch()...'）
if (isFlagged(cmd)) hit = 'command';

if (!hit) {
  // 解析 cwd：优先 cd 前缀，其次 harness 给的 cwd，都做 win 归一化
  let cwd = winPath(data.cwd) || process.cwd();
  // ⛔ 2026-09-18 外审实测漏拦:原来只认 `cd X &&|;` ⇒ PowerShell `Set-Location X; node clean.js`
  //   在错的目录里找不到脚本 ⇒ 读不到内容 ⇒ 放行裸 launch→x.com(X 账号永久冻结)。
  //   段首切目录一律认:cd / chdir / Set-Location / Push-Location / pushd / sl,可带 -Path / -LiteralPath。
  const cdm = cmd.match(/(?:^|&&|\|\||;|\n)\s*(?:cd|chdir|Set-Location|Push-Location|pushd|sl)(?:\s+\/d)?\s+(?:-(?:Literal)?Path(?::|\s+)\s*)?["']?([^"'&|;\n]+?)["']?\s*(?:&&|\|\||;|\n)/i);
  if (cdm) cwd = winPath(cdm[1].trim());
  // 只扫"被解释器执行"的脚本(node/python X.js)，绝不扫仅被 grep/cat/read/git 读取的文件——
  // 读一个含 launch 的文件零封号风险，误拦它是这次要修的核心 bug。
  const scripts = [...cmd.matchAll(
    /\b(?:node|nodejs|python3?|deno(?:\s+run)?|bun|tsx|ts-node)\s+(?:(?:--?[\w-]+(?:=\S+)?|-\w+)\s+)*["']?([\w.\/\\:@-]+\.(?:mjs|cjs|js|ts|py))\b/gi
  )].map(m => m[1]);
  for (const s of scripts) {
    const sw = winPath(s);
    const cands = [sw, path.resolve(cwd, sw)];
    for (const c of cands) {
      try {
        if (fs.existsSync(c) && fs.statSync(c).isFile()) {
          const content = fs.readFileSync(c, 'utf8');
          if (isFlagged(content)) { hit = 'script:' + c; break; }
        }
      } catch (_e) {}
    }
    if (hit) break;
  }
}

if (hit) {
  const reason =
    '🚫 anti-scraping 守卫拦截 [' + hit + ']：检测到对登录墙站(X/抖音/小红书/微博/Google/TikTok/IG…)的裸 launch。\n' +
    '这些站用 Playwright/Puppeteer/Selenium 裸 launch 自动化会被封（X 永久冻结）。\n' +
    '安全做法：用 launch_persistent_context + 【我自己的】独立 user-data-dir(webdriver=false、指纹与真人一致)；\n' +
    '需要登录就打开登录页截图请他登，登录态存我自己 profile 里复用。或先 invoke anti-scraping skill 确认方案。\n' +
    '⛔ 别用 connectOverCDP 去接管【他已登录的】浏览器(9226=openclaw知识库/9555/opencli profile)——\n' +
    '   那是他的资产，2026-08-20 已定为全局铁律，另有 his-browser-guard.cjs 硬拦。\n' +
    '(本地测试/启动自己项目的 launch 不会被拦；若确属误判，在命令里加 `# antiscraping-ok`。)';
  // 官方 PreToolUse 首选：JSON permissionDecision deny（新版读它，reason 更干净丰富）
  try {
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: reason,
      },
    }));
  } catch (_e) {}
  // exit 2 = fail-closed 兜底：任何版本/即便 JSON 不被识别也硬拦，stderr 回灌模型
  process.stderr.write(reason + '\n');
  process.exit(2);
}
process.exit(0);
