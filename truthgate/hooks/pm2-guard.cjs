#!/usr/bin/env node
// PreToolUse 守卫：硬拦会触发 lm-worker 死循环的 pm2 持久化命令(save/startup/dump/resurrect)。
// 事故(记忆 feedback_pm2_lmworker)：pm2 save/startup 把所有 app(含 lm-worker)拖进开机自启；
// lm-worker 崩溃 → pm2 无封顶重启 → 立即重拉同一失败任务 → 再崩 → 无限死循环吃爆资源。
// 由 harness 在工具执行前运行,命中即拒绝——不依赖模型"记不记得规矩"。
//
// ⚠️ 只拦危险的持久化子命令。安全的 pm2 restart/start/stop/delete/list/logs/jlist... 一律放行(不误拦)。
// 放行：命令里显式标记 `# pm2-ok`(确认非 pm2 不可且已避开死循环,如图库那种带封顶独立 config)。
// 退出码 2 = 阻断(stderr 回灌给模型)；退出码 0 = 放行。
const fs = require('fs');

let raw = '';
try { raw = fs.readFileSync(0, 'utf8'); } catch { process.exit(0); }
let data = {};
try { data = JSON.parse(raw); } catch { process.exit(0); }

const tool = data.tool_name || '';
if (tool !== 'Bash' && tool !== 'PowerShell') process.exit(0);
const cmd = ((data.tool_input && data.tool_input.command) || '').toString();
if (!cmd) process.exit(0);

// 显式放行(已确认非 pm2 不可、且避开死循环)
if (/#\s*pm2-ok/i.test(cmd)) process.exit(0);

// 危险子命令 + 可选【sudo / 包装器 / 路径前缀】,不含前置边界(两趟匹配共用,避免子命令表漂移):
//   save(持久化)、startup(生成开机自启)、dump(=save 别名)、resurrect(复活已存列表)。
//   注意 startup≠start：`pm2 start x` 因 "startup\b" 需要完整词、不会命中 → pm2 start 永不被拦。
const PM2_DANGER = '(?:sudo\\s+)?(?:npx\\s+|yarn\\s+|pnpm\\s+exec\\s+|[.\\w\\/\\\\-]*[\\/\\\\])?pm2(?:\\.cmd)?\\s+(save|startup|dump|resurrect)\\b';

// 先剥掉【尾部注释】(引号感知:引号内的 # 不算注释)——否则 `pm2 restart all # then pm2 save` 会因
//   \s 边界把注释里的 pm2 save 当成真调用误拦(FP)。`# pm2-ok` 已在上面先行放行,不受影响。
function stripComment(s) {
  let q = null;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (q) { if (c === q) q = null; }
    else if (c === '"' || c === "'") q = c;
    else if (c === '#' && (i === 0 || /\s/.test(s[i - 1]))) return s.slice(0, i);
  }
  return s;
}
const cmdNC = stripComment(cmd);

// 第1趟(骨架):剥掉引号包裹的内容(把字符串里"提到"的 pm2 save 抹成空格)→ 引号内的 | ( ) ` 元字符不再被
//   当成命令分隔符,grep "err\|pm2 save" / echo "(pm2 save)" 等零执行字符串不再误拦(FP)。
//   边界容许【空格】+可选包装器/路径前缀 → npx pm2 save、./node_modules/.bin/pm2 save 不再漏放(FN)。
// ponytail: 剥引号不处理转义/嵌套引号(罕见),仍远好于旧的裸整串匹配。
const DANGER = new RegExp('(?:^|[\\s;&|(){}`])\\s*' + PM2_DANGER, 'i');
const skel = cmdNC.replace(/"[^"]*"|'[^']*'/g, ' ');

// 第2趟(原文):补回第1趟剥引号会漏掉的两条【引号内被真正执行】的通路——
//   (a) 命令替换 `...pm2 save...` / $(...):即便在双引号里也会被 shell 执行;
//   (b) exec 包装器(sh/bash/zsh/dash/ash -c、eval、ssh "<代码>"):引号载荷本身是代码不是数据。
// 仅当出现 exec 包装器时,才把引号内的 ; && || 视为会执行的分隔符;否则只认命令替换 `/$(——
//   这样 echo "note; pm2 save"、git commit -m "x; pm2 save" 这类纯字符串不会被误拦(不制造新 FP)。
const hasExecWrapper = /(?:^|[\s;&|(`{}])(?:sudo\s+)?(?:bash|sh|zsh|dash|ash|eval|ssh)\b/i.test(cmdNC);
const sep = hasExecWrapper ? '(?:;|&&|\\|\\||`|\\$\\()' : '(?:`|\\$\\()';
const PASS2 = new RegExp(sep + '\\s*' + PM2_DANGER, 'i');

const m = skel.match(DANGER) || cmdNC.match(PASS2);
if (m) {
  const sub = m[1].toLowerCase();
  const reason =
    '🚫 pm2 守卫拦截：`pm2 ' + sub + '` 会触发 lm-worker 死循环事故。\n' +
    '根因(记忆 feedback_pm2_lmworker)：pm2 save/startup 把所有 app(含 lm-worker)拖进开机自启；\n' +
    'lm-worker 崩溃 → pm2 无封顶重启 → 立即重拉同一失败任务 → 再崩 → 无限死循环吃爆资源。\n\n' +
    '⛑ 先问自己：这个真的必须 pm2 吗？没有就别用 pm2 持久化：\n' +
    '  • 要"开机自启" → Startup 快捷方式 / 登录计划任务(只 pm2 start 那一个 app)，绝不 pm2 save\n' +
    '  • 要"崩溃自愈" → 独立看门狗计划任务(查端口没了就拉起)，或图库那种带封顶独立 config\n' +
    '                   (max_restarts=15 + exp_backoff_restart_delay + min_uptime，物理上无法无限循环)\n' +
    '  • 能不用 pm2 就不用，pm2 放最后。\n' +
    '确属安全非它不可(且已避开死循环)要放行：命令里加 `# pm2-ok` 并说明为何。';
  // 官方 PreToolUse 首选：JSON permissionDecision deny
  try {
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: reason,
      },
    }));
  } catch (_e) {}
  // exit 2 = fail-closed 兜底
  process.stderr.write(reason + '\n');
  process.exit(2);
}
process.exit(0);
