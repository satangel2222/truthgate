#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreToolUse gate:【要拿一份数据覆盖/替换另一份,却没先比对两边的量】⇒ 拦。

⛔⛔ 2026-09-05 差点造成真损失(Frank 截图给我看的,发生在另一个项目的会话里):
   那个会话想恢复 chat-archive,查了 `D:\\chat-archive\\`(**代码目录**)发现没有 brain.db,
   于是断定「chat-archive 断了、D 盘那份只是代码不是数据」,并建议
   **把旧盘 `F:\\Users\\User\\Desktop\\chat-archive` 那份 1.8G 搬到新桌面 + 把抓取脚本重新指过去**。
   实测真相:真数据库在 **`D:\\chat-archive-db\\`**(另一个目录),
   **114,706 条 / 45 项目 / 实时更新**;而它想搬来的那份 **73,184 条 / 35 项目 / 停在 08-25**。
   ⇒ **照做会一次丢 4 万多条对话。**

⛔ 为什么"写进文档"救不了:那份 `host-machine-facts.md` **每轮都自动注入**,
   第 21 行早就写着"真库在 chat-archive-db、代码在 chat-archive"——**它读到了,照样查错地方**。
   因为那句话埋在一个几千字的表格单元格中间。**读到 ≠ 用得上。**
   ⇒ 所以这次不写第 N 条警告,改成**在动手那一刻拦住**。

判据(纯算术,零语义,跨项目通用):
   要做【覆盖型操作】(robocopy /MIR、Copy-Item -Force 到已存在的目标、rm 后重建、
   mv 覆盖、sqlite 替换、把 A 目录指向 B)时,
   **本轮必须出现过"比对两边数量"的动作**(count/统计/du/Measure-Object/select count 等),
   否则 deny 并要求先比对。

安全:fail-open —— 解析失败/拿不到 transcript 一律放行(rc=0)。
"""
# ⛔ 2026-09-10 接进账本(Frank:「为何 superego 没拦你还是没开火?」):本闸此前从没 import guard_common,
#   于是它每次开火 hook-stats.jsonl 里都是 0 条 ⇒ 记分板看不见它、nudge-escalation-gate 也数不到它
#   (同日扫出 10 道同病,ui-edit-guard 一天响 8 次账本 0 条)。guard_common 一 import 就自动观测 stdout、
#   退出时按内容判 nudge/block/allow,本闸逻辑一字不改。自包含写法:不依赖本文件已有的 import。
try:
    import os as _gc_os, sys as _gc_sys
    _gc_sys.path.insert(0, _gc_os.path.dirname(_gc_os.path.abspath(__file__)))
    import guard_common  # noqa: F401  接线即记账;失败不影响本闸(fail-open)
except Exception:
    pass

import json
import os
import re
import sys


def ok():
    sys.exit(0)


try:
    DATA = json.loads(sys.stdin.read() or "{}")
except Exception:
    ok()

TOOL = DATA.get("tool_name", "")
if TOOL not in ("Bash", "PowerShell"):
    ok()

CMD = str((DATA.get("tool_input") or {}).get("command", ""))
if not CMD:
    ok()

LOW = CMD.lower()

# ── ① 这是不是【覆盖型】操作 ──────────────────────────────
# ⛔ 判据【绝不能依赖参数顺序】—— 第一版写成 `copy-item…-force…-recurse`,
#   而真实命令是 `-Recurse -Force`(顺序相反)⇒ **最关键那条真实危险样本直接漏过**,
#   是回归测试当场抓到的。PowerShell/CLI 的参数顺序本来就是任意的。
#   ⇒ 改成:先认出命令动词,再【分别】检查各个开关在不在,不管它们谁前谁后。
def _has(*flags):
    return all(re.search(r"(?<![\w-])" + f, LOW) for f in flags)


# ⛔⛔ 2026-09-07 第二次改这里:上面那个 `_has` 是**在整条命令里找开关**,不管它属于谁 ——
#   `Copy-Item a b; Remove-Item c -Force` 会被算成「Copy-Item 强制覆盖」(开关是别人的)。
#   同理 `git commit -m "copy-item -force"` 里引号中的字也会命中。
#   这是查外部现成实现时暴露的:`cc-safety-net`(★1.5k)的卖点就是「**解析这条命令在干什么**」,
#   而我这边全是整串正则。⇒ 抽出 `cmd_parse`,判据改成
#   **「有没有一次 <动词> 调用,而且【那一次自己】带齐了这些开关」**。
#   动词互相包含(remove-item ⊃ move-item)也随之天然解决,不再靠事后补 \b。
try:
    from cmd_parse import has_invocation as _inv
except Exception:
    _inv = None


def _cmd_has(verb, *flags):
    if _inv:
        return _inv(CMD, verb, *flags)
    # 退路:解析器不可用时回到老写法(方向保守 —— 宁可像以前一样,也不静默放行一切)
    return bool(re.search(r"(?<![\w-])" + re.escape(verb), LOW)) and _has(
        *[re.escape(f) for f in flags])


IS_OVERWRITE = (
    _cmd_has("robocopy", "/mir")
    # ⛔⛔ 2026-09-07:命令动词必须带 `\b`。原来是裸的 `move-item` ——
    #   而 **`remove-item` 字面上就包含 `move-item`**(re + move-item)
    #   ⇒ 任何 `Remove-Item xxx -Force`(不带 -Recurse 的单文件删除)都被当成
    #     「Move-Item 强制覆盖」拦下 = **真实误伤,而且是天天会遇到的操作**。
    #   照出它的是新写的故障注入用例(「只有 -Force 没有 -Recurse ⇒ 放行」)——它当场变红,
    #   我先以为是靶子写错,逐条打印分支才看到命中的是 move-item 那条。
    #   同形状今天第三次:`CODE_EXT` 少 `\b` 把 settings.json 当成 .js;
    #   `drama` 命中 `dramalink`,让那道专为它建的闸放行了它本人。
    #   ⇒ **拿子串匹配命令动词,迟早撞上另一个包含它的动词。**
    or _cmd_has("copy-item", "-force")                               # 强制覆盖
    or _cmd_has("move-item", "-force")
    or _cmd_has("remove-item", "-recurse", "-force")
    or _cmd_has("cp", "-r") or _cmd_has("cp", "-f")
    or _cmd_has("rsync", "--delete")
    or re.search(r"\bmv\s+[^\n]*\s+/", LOW)
)
if not IS_OVERWRITE:
    ok()

# ── ② 目标是不是【已存在且像数据】的东西 ──────────────────
#    只管数据(db/档案/备份/项目目录),不管构建产物与临时目录
DATA_HINT = re.search(
    r"\.db\b|\.sqlite|brain|archive|backup|备份|档案|projects|\.jsonl|dataset|库",
    LOW)
if not DATA_HINT:
    ok()

SAFE_PATH = re.search(r"\\temp\\|/tmp/|node_modules|\\build\\|/build/|scratchpad|__pycache__", LOW)
if SAFE_PATH:
    ok()

# ⛔ 明确标注已核对过 ⇒ 放行(提示里承诺了这个出口,必须真的实现 ——
#   否则就成了"提示说有出口、代码里没有"的假承诺,那比没提示更糟)。
if re.search(r"#\s*OVERWRITE-VERIFIED", CMD, re.I):
    ok()

# ── ③ 本轮有没有【比对过两边的量】──────────────────────────
COMPARE = re.compile(
    r"count\s*\(|select\s+count|measure-object|\bwc\s+-l\b|getlength|"
    r"len\(|\.count\b|du\s+-|get-childitem[^\n]*measure|统计|比对|逐条|条数|多少条",
    re.I)

tp = DATA.get("transcript_path") or ""
compared = False
if tp and os.path.exists(tp):
    try:
        with open(tp, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-140:]
        for ln in reversed(lines):
            try:
                o = json.loads(ln)
            except Exception:
                continue
            if o.get("type") != "assistant":
                continue
            for c in (o.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    if COMPARE.search(str(c.get("input") or {})):
                        compared = True
                        break
            if compared:
                break
    except Exception:
        ok()          # 读不了 transcript 就别挡路

if compared:
    ok()

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "⛔ 覆盖前必须先比两边的量:你要做一个【会覆盖/替换已有数据】的操作,"
            "但本轮**没有任何一次比对过两边各有多少条/多少文件**。\n\n"
            "⛔ 2026-09-05 实录(差点丢 4 万条对话):另一个项目的会话查 chat-archive 时,"
            "只看了 `D:\\chat-archive\\`(**那是代码目录**)、发现没有 brain.db,"
            "就断定「档案库断了」,并建议把旧盘那份 1.8G 搬来覆盖 + 重新指向。\n"
            "   真相:真库在 **`D:\\chat-archive-db\\`**,114,706 条 / 45 项目 / 实时更新;"
            "它想搬来的那份只有 73,184 条 / 35 项目 / 停在 08-25。**文件更大只因含历史碎片。**\n\n"
            "⇒ 先跑一次两边对比再来(任选其一):\n"
            "   · 数据库: `select count(*), max(ts) from <表>` 两边各跑一次\n"
            "   · 目录  : `Get-ChildItem <路径> -Recurse -File | Measure-Object` 两边各跑一次\n"
            "⇒ **哪边新、哪边多,数字说了算** —— 文件体积大 ≠ 内容多。\n"
            "⇒ 确认过了、或这次覆盖的就是临时产物 ⇒ 命令里加注释 `# OVERWRITE-VERIFIED` 即放行。"
        ),
    }
}, ensure_ascii=False))
sys.exit(0)
