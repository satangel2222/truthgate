#!/usr/bin/env node
/**
 * 收尾清扫:把我自己写在【仓库外临时目录】里的明文密钥就地打码。
 *
 * 为什么需要它(2026-07-27 实录):
 *   防线原本只有两道 —— .gitignore 和 git pre-commit 钩子 —— 两者【都只管仓库内】。
 *   而我(AI)真正频繁硬编码 key 的地方是 scratchpad:测 API、探配额、改配置时,
 *   为了跑通一次就把 key 写死进临时脚本。那天一轮下来,13 个文件、15 处明文密钥
 *   躺在 %TEMP%\claude\ 里,其中包含一个【当时还活着】的 key。git 永远看不到那里,
 *   所以 pre-commit 内容扫描对它 100% 无效。
 *   r/devsecops 的原话:"agent memory is text files" —— 这就是那个盲区。
 *
 * 只打码,不删文件:脚本本身有复盘价值,丢掉的只是密钥。
 * 静默设计:没有发现就一个字都不输出(Stop hook 每轮都跑,不能刷屏)。
 */
const fs = require('fs');
const path = require('path');
const os = require('os');

// 只扫 Claude 自己的临时区。不碰用户的 Downloads/Documents 等真实工作目录。
const ROOTS = [
  path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'Temp', 'claude'),
  path.join(os.tmpdir(), 'claude'),
];
const EXT = /\.(mjs|cjs|js|ts|py|json|txt|md|sh|ps1|bat|cmd|yaml|yml|env)$/i;
const MAX_AGE_MS = 12 * 3600e3;   // 只看最近 12 小时碰过的,历史文件不重复扫
const MAX_BYTES = 2 * 1024 * 1024; // 跳过大文件(日志/数据集),它们不是我手写的脚本
const MAX_FILES = 4000;            // 硬上限,防止目录爆炸时拖慢收尾

// 词边界很重要:裸 sk- 会匹配 ask-/musk-/desk-/whisk- 这类普通英文
const PATTERNS = [
  [/(^|[^A-Za-z0-9_-])sk-or-v1-[A-Za-z0-9]{20,}/g, '$1sk-or-v1-REDACTED'],
  [/(^|[^A-Za-z0-9_-])sk-[A-Za-z0-9]{32,}/g, '$1sk-REDACTED'],
  [/(^|[^A-Za-z0-9_-])xai-[A-Za-z0-9]{40,}/g, '$1xai-REDACTED'],
  [/(^|[^A-Za-z0-9_-])ghp_[A-Za-z0-9]{30,}/g, '$1ghp_REDACTED'],
  [/(^|[^A-Za-z0-9_-])AIza[A-Za-z0-9_-]{30,}/g, '$1AIza_REDACTED'],
  [/[0-9]{8,12}:AA[A-Za-z0-9_-]{30,40}/g, 'TG_TOKEN_REDACTED'],
];

// ── 第二档:Shannon 熵检测(2026-07-27 last30days 挖到的,来自一段 gitleaks 教程转录)
// 正则只认【我已经知道的】格式。实测:对 RunningHub(纯hex) / FAL(uuid:hex) / Jina(jina_) /
// Groq(gsk_) 这四种 Frank 机器上真实用过的 key,上面那张正则表 0/5 全漏,熵检测 5/5 全中。
// 阈值 3.5 bits/char 是 gitleaks 的经验值。
//
// ⛔ 熵命中【只报告,不打码】。熵有不确定性,而打码会改文件内容 —— 误伤 git hash /
// base64 图片 / minified JS 会直接破坏脚本。确定的(正则)自动处理,疑似的(熵)交给人判断。
const SAFE = /^(?:[0-9a-f]{40}|[0-9a-f]{64}|[0-9A-Fa-f-]{36})$/; // git sha / sha256 / UUID
function shannon(s) {
  const m = Object.create(null);
  for (const c of s) m[c] = (m[c] || 0) + 1;
  let e = 0;
  for (const k in m) { const p = m[k] / s.length; e -= p * Math.log2(p); }
  return e;
}
// 判据是【最长连续无分隔段】,不是整串。真实对照(2026-07-27 实测):
//   043839fbc4244bd8a594a5a8bd30cb6b    -> 最长段 32  = 真 key(RunningHub)
//   gsk_mFXavFygL2WTU9j9RtuiWGdyb3FY... -> 最长段 52  = 真 key(Groq)
//   nemotron-3-super-120b-a12b:free     -> 最长段  8  = 模型名
//   Huihui-Qwen3-VL-8B-Instruct-abli... -> 最长段 11  = 模型名
//   secret-scanning-tools-gitleaks-...  -> 最长段 12  = 文件名
// 先前版本改用「同行必须出现 key/token/secret」做门控,结果真实文件里变量名是
// RUNNINGHUB / FAL / JINA / GROQ(平台名,不含通用词)-> 5 个真 key 全漏,同时把模型名报成疑似。
const SEG_MIN = 20;
function entropySuspects(text) {
  const out = [];
  for (const line of text.split('\n')) {
    if (line.includes('REDACTED')) continue;
    for (const tok of line.match(/[A-Za-z0-9_\-:.]{24,200}/g) || []) {
      if (SAFE.test(tok)) continue;
      if (/^https?:/i.test(tok) || tok.includes('/')) continue;   // URL / 路径不算
      const seg = tok.split(/[-_.:]+/).reduce((a, b) => (b.length > a.length ? b : a), '');
      if (seg.length < SEG_MIN) continue;                          // 分段可读 = 模型名/文件名,不是 key
      if (!/[0-9]/.test(seg) || !/[A-Za-z]/.test(seg)) continue;   // 必须字母数字混合
      if (shannon(seg) >= 3.5) out.push(tok.slice(0, 12));
    }
  }
  return out;
}

const now = Date.now();
let scanned = 0;
const hits = [];
const suspects = [];

function walk(dir, depth) {
  if (depth > 6 || scanned > MAX_FILES) return;
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
  for (const e of entries) {
    if (scanned > MAX_FILES) return;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === 'node_modules' || e.name === '.git') continue;
      walk(p, depth + 1);
      continue;
    }
    if (!EXT.test(e.name)) continue;
    let st;
    try { st = fs.statSync(p); } catch { continue; }
    if (st.size > MAX_BYTES || now - st.mtimeMs > MAX_AGE_MS) continue;
    scanned++;
    let src;
    try { src = fs.readFileSync(p, 'utf8'); } catch { continue; }
    let out = src, n = 0;
    for (const [re, rep] of PATTERNS) {
      const m = src.match(re);
      if (m) { n += m.length; out = out.replace(re, rep); }
    }
    if (n > 0) {
      // 改文件之前先留一份原件。这个 hook 每轮自动跑,如果某个【正在被使用】的临时脚本
      // 含 key,打码后它就跑不通了 —— 必须可逆。.keybak 与原文件同目录,自身不会被再次扫描
      // (扩展名不在 EXT 白名单内),要恢复直接把它改回原名即可。
      try {
        const bak = p + '.keybak';
        if (!fs.existsSync(bak)) fs.writeFileSync(bak, src, 'utf8');
        fs.writeFileSync(p, out, 'utf8');
        hits.push(`${e.name} (${n})`);
      } catch { }
    }
    // 对打码后的内容再跑熵检测,捞正则表不认识的格式(只报告,不改文件)
    const sus = entropySuspects(out);
    if (sus.length) suspects.push({ file: e.name, tokens: sus.slice(0, 3) });
  }
}

// 去重:Windows 上 os.tmpdir() 解析出来就是 %LOCALAPPDATA%\Temp,两个 ROOT 指向同一处,
// 不去重会把每个文件扫两遍、每条命中报两次(2026-07-27 实测输出里 t.mjs 出现两次)。
const seenRoot = new Set();
for (const r of ROOTS) {
  try {
    if (!fs.existsSync(r)) continue;
    const real = fs.realpathSync(r).toLowerCase();
    if (seenRoot.has(real)) continue;
    seenRoot.add(real);
    walk(r, 0);
  } catch { }
}

const out = [];
if (hits.length) {
  const shown = hits.slice(0, 6).join(', ');
  out.push(`🔐 收尾清扫:已打码明文密钥 —— ${shown}${hits.length > 6 ? ` 等 ${hits.length} 个文件` : ''}。`);
}
if (suspects.length) {
  const shown = suspects.slice(0, 4).map(s => `${s.file}[${s.tokens.join(',')}…]`).join('  ');
  out.push(`⚠️ 高熵疑似密钥(正则表不认识的格式,未自动改动,请人工确认) —— ${shown}`
    + `${suspects.length > 4 ? ` 等 ${suspects.length} 个文件` : ''}`);
}
if (out.length) {
  console.log(out.join('\n') + `\n   这些位置 git 看不到、pre-commit 拦不住。别在临时脚本里硬编码 key,从环境变量或 gitignore 的配置读。`);
}
process.exit(0);
