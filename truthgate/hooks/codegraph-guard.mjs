#!/usr/bin/env node
// PreToolUse hook (matcher: Grep) — 全局，跨所有项目。
// 当前项目含 .codegraph/ 索引时，拦截内置 Grep 工具并提示模型改用 codegraph_explore。
// 没有索引 → 静默放行。需要字面量/非代码搜索时，模型改走 Bash 的 rg（不匹配 Grep，故不被本 hook 拦）。
import { existsSync, statSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';

// ⛔ 2026-07-25 修两类误伤(审计 + 本轮实测各撞 3 次):
//  ①【作用域】原判据只看「当前项目有没有 .codegraph/」,完全不看 Grep 要搜的 path ——
//    于是在一个有索引的项目里搜【项目之外】的文件(如 ~/.claude/hooks/ 这种全局配置)也被拒,
//    而那些文件根本不在索引里,codegraph_explore 查不到 = 把人推向一个查不到东西的工具。
//  ②【新鲜度】只检查索引目录【存在】,不看它是不是几周前冻住的;陈旧索引照样拦 = 逼人用过期数据。
const STALE_DAYS = 14;

function outsideIndexedRoot(toolPath, cwd) {
  if (!toolPath) return false;                 // 没指定 path = 搜当前项目 → 归索引管
  try {
    // ⛔ Windows 盘符大小写不敏感:`d:\x` 与 `D:\x` 是同一个地方,用大小写敏感比较会把
    //   项目内路径误判成"项目外"→ 放行(外部 critic 抓到)。统一转小写再比。
    const abs = resolve(cwd, toolPath).toLowerCase(), root = resolve(cwd).toLowerCase();
    return abs !== root && !abs.startsWith(root + sep);
  } catch { return false; }
}

function indexStale(cwd) {
  // ⛔ 原来取 .codegraph【目录】的 mtime —— 目录时间会被里面任何一次日志写入带动,
  //   而真正的索引数据库是【原地重写】的、不推进目录时间(外部 critic 实测:目录 18:25、库 16:10)。
  //   结果:一个没有增删文件的活索引可能被判"陈旧"而让这道闸自我关闭。→ 直接看索引库本身的时间。
  // ⛔ 外部 critic 实测:上一版把【目录自己】也放进 Math.max —— 而目录时间会被里面任何一次
  //   日志写入带动(真实项目就是这形状:库 16:10、目录 18:25、daemon.log 一直在写)→ 目录永远新鲜
  //   → 陈旧分支等于死代码 = 修了等于没修。**有数据库就只看数据库**,一个都没有才回落到目录。
  const dir = join(cwd, '.codegraph');
  let newest = 0;
  for (const f of ['codegraph.db', 'index.db', 'graph.db']) {
    try { newest = Math.max(newest, statSync(join(dir, f)).mtimeMs); } catch { /* 没这个库 */ }
  }
  if (newest === 0) {
    try { newest = statSync(dir).mtimeMs; } catch { return false; }
  }
  return Date.now() - newest > STALE_DAYS * 864e5;
}

let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { buf += c; });
process.stdin.on('end', () => {
  let cwd = process.cwd();
  try {
    const data = JSON.parse(buf || '{}');
    if (typeof data.cwd === 'string' && data.cwd) cwd = data.cwd;
  } catch { /* ignore — fall back to process.cwd() */ }

  // 无索引：什么都不输出，默认放行。
  if (!existsSync(join(cwd, '.codegraph'))) process.exit(0);

  let toolPath;
  try { toolPath = JSON.parse(buf || '{}')?.tool_input?.path; } catch { /* ignore */ }
  // 搜的是【被索引项目之外】的文件 → 索引里根本没有，拦了等于把人推向查不到的工具 → 放行
  if (outsideIndexedRoot(toolPath, cwd)) process.exit(0);
  // 索引已陈旧 → 逼人用过期数据不如让他直接搜 → 放行
  if (indexStale(cwd)) process.exit(0);

  const reason =
    '本项目有 .codegraph/ 索引。请优先用 codegraph_explore（MCP 工具）查代码——一次返回 verbatim 源码 + 调用链 + 影响面，比 Grep 更快更准。' +
    '例外：若你在搜字面量字符串 / 日志 / 配置值 / 非代码文本 / 未被索引的文件，改用 Bash 的 `rg`（不会被本 hook 拦截）。';

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: reason,
    },
  }));
  process.exit(0);
});
