#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""lessons-write-gate —— PreToolUse 闸:拦【绕过 lessons_add.py 去整份覆写 lessons.md】。

⛔ 为什么要它(2026-09-09 实测):
  本机常有 3~5 个 session 同开,每个记教训都用「读全文 -> 拼接 -> 写全文」。
  · 8 进程并发实测: 旧写法 **1/8 幸存**,lessons_add.py **8/8 全在、编号不撞**
  · 真实发作:编号 `2026-09-09-B` 和 `-D` 各被两个 session 用了一次
    ⇒ 判重脚本报"已记过" ⇒ **整条教训丢了,而我以为自己记过了**
  ⇒ 光把规矩写进 CLAUDE.md 不够(别的 session 会忘/会绕),必须有机器拦一道。

⛔ 别把两件事混了(我建这道闸当天就判错过一次):同一天 lessons.md 里那个
  10,847 字节的 NUL 空洞 **不是并发造成的** —— 是 09-04 18:44 系统崩溃
  (Windows 事件 ID 41)后 NTFS 的零填充,27 个 hook 日志同时中招可证。
  **本闸治的是并发那一半(内容被盖掉 + 撞号),治不了断电。**

判据(全中才拦,宽放窄拦):
  ① 目标是 `lessons.md`(用户级那一份,不是项目里同名文件)
  ② 动作会【整份覆写】: Write 工具 / shell 里的 write_text·writeFileSync·> 重定向·tee·cp·mv
  ③ 不是走 `lessons_add.py` 本身(它自己就要写这个文件)
放行(故意不拦,风险小或属正当路径):
  · **Edit 工具** —— 局部替换,不会把别人刚写的整段吃掉,是改错别字的正当路径
  · 只读: cat/head/tail/grep/wc/Read
  · `--check` / `--selftest` / 备份文件(*.bak / *.corrupt-*)

安全: fail-open(自己出错绝不挡路);拦截时 stderr 给可执行的替代命令,不是空壳。
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from guard_common import hook_log
except Exception:
    def hook_log(name, msg, ctx=""):
        try:
            with open(Path(__file__).with_name(name + ".log"), "a", encoding="utf-8") as f:
                f.write(f"{msg} | {ctx}\n")
        except Exception:
            pass


TARGET = re.compile(r"lessons\.md", re.I)
# 会把 lessons.md 整份写掉、或绕过编号分配去追加的动作(Edit 工具不在内 —— 局部替换风险小得多)
# ⛔ 2026-09-09 异模型外部审查点出:`Add-Content` / `>>` 是【追加】不是覆写,列在名为
#    OVERWRITE 的表里名不副实。**但拦它是有意的** —— 追加虽不会吃掉别人的内容,
#    却照样绕过 next_id 自动分配 ⇒ 撞号,而撞号当天就让一整条教训丢了(判重报"已记过")。
#    ⇒ 保留拦截,把理由写在这里;这张表管的是"绕过正门写它",不只是"覆写它"。
# ⛔ 2026-09-09 建闸当天第二次被自己误伤:`write_text` 原来是【裸匹配】,于是
#    「命令里提到 lessons.md、但实际写的是 scratchpad 里另一个文件」也被拦。
#    ⇒ 写动作必须和 lessons.md 出现在【同一行】才算。
#    已知代价(诚实登记):多行脚本里 `f = Path(...lessons.md)` 换行后再 `f.write_text()` 会漏拦 ——
#    换来的是不再对"只是提到它"开火。噪音会把真提醒训练成背景音,那个代价更大。
# ⛔ 2026-09-27(考卷 c042):重定向 / tee / cp 这几条原来是「写动作后面 120 字内出现 lessons.md」就算,
#   于是 `ls x 2>/dev/null; grep -c "^## " ~/.claude/lessons.md`(只读数条数)被当成覆写。
#   ⇒ 重定向、tee 只认【紧跟着的那个目标】是 lessons.md;cp/mv 这类只在【同一条语句】里找(遇 ; & | 换行就停)。
OVERWRITE = re.compile(
    r"(?:write_text|writeFileSync|writeFile\s*\(|fs\.write)[^\n]{0,120}lessons\.md|"
    r"lessons\.md[^\n]{0,120}(?:write_text|writeFileSync|writeFile\s*\(|fs\.write)|"
    r">\s*[\"']?[^\s\"'|;&<>]*lessons\.md|"
    r"\btee\b(?:\s+-\w+)*\s+[\"']?[^\s\"'|;&<>]*lessons\.md|"
    r"\b(cp|copy|mv|move|Move-Item|Copy-Item|Set-Content|Out-File|Add-Content)\b"
    r"[^|\n;&]{0,160}lessons\.md",
    re.I)
# 走正门 / 动的是备份而非正本 —— 放
# ⛔ 这里【故意不列只读命令名】(cat/grep/head…):2026-09-09 第一版列了,结果
#    `cat new.md > lessons.md` 被 `cat` 命中当成只读放行 —— 真漏拦,回归当场抓到。
#    只读本就由"OVERWRITE 不匹配"隐含表达,再加一层命令名白名单只会开后门。
EXEMPT = re.compile(
    r"lessons_add\.py|--selftest|--check|"
    r"lessons\.md\.(bak|corrupt|tmp|repaired|orig)",
    re.I)

MSG = """⛔ lessons-write-gate:你在【整份覆写】lessons.md,而本机同时开着好几个 session 都在写它。

⛔ 2026-09-09 实测(8 个进程并发写同一文件):
   旧写法(读全文+写全文,无锁) → **只剩 1/8 条幸存**,而且会撞号
   lessons_add.py(锁+原子替换+自动分配编号) → **8/8 全在、编号不撞**
   撞号的直接后果:判重脚本报"已记过",**我那条教训整条丢了,而我以为自己记过了**。

✅ 正确走法(正文里编号写 {ID} 占位,工具会替换成没人占的那个):
   py -3.12 ~/.claude/bin/lessons_add.py --body-file <你的正文.md>
   py -3.12 ~/.claude/bin/lessons_add.py --next 2026-09-09    # 只想知道下一个可用编号
   py -3.12 ~/.claude/bin/lessons_add.py --check              # 体检 NUL/撞号/可解码

ℹ️ 改错别字/改一小段用 **Edit 工具**(局部替换),本闸不拦。
"""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)                       # fail-open

    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}

    if tool == "Write":
        path = str(ti.get("file_path", ""))
        blob = path
    elif tool in ("Bash", "PowerShell"):
        blob = str(ti.get("command", ""))
    else:
        sys.exit(0)                       # Edit / 其它工具不管

    if not TARGET.search(blob):
        sys.exit(0)
    if EXEMPT.search(blob):
        sys.exit(0)
    # 只有用户级那一份要保护;项目里同名文件不管
    if "/.claude/" not in blob.replace("\\", "/") and ".claude" not in blob:
        sys.exit(0)
    if tool != "Write" and not OVERWRITE.search(blob):
        sys.exit(0)                       # shell 里只是提到文件名,没在覆写

    hook_log("lessons-write-gate", "BLOCK", blob[:300])
    sys.stderr.write(MSG)
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                # 闸自己坏了绝不挡路
        hook_log("lessons-write-gate", "FAIL-OPEN", repr(e))
        sys.exit(0)
