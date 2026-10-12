#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backslash-eater-gate — Bash 工具会吃掉一层反斜杠，用它写代码/写文件必崩时拦下。

来历（2026-08-20，Frank：「heredoc 完整深入审查彻底修复，找出根因不是头痛医头」）

【根因 · 已实测 + 上游已确认，不是我写错也不是 git bash】

  Claude Code 的 Bash 工具在把 command 送进 shell 之前，会跑一遍 quoting/preprocessing
  管线（shell-quote），这一步**吃掉一层反斜杠**。上游多个未修 issue：
    · anthropics/claude-code#14361  Bash tool 在单引号内错误转义特殊字符（违反 POSIX）
    · anthropics/claude-code#1195   Backslash Handling Issues in CLI Commands
    · anthropics/claude-code#48317  反复在 heredoc/字符串转义上失败，导致多次重试
    · anthropics/claude-code#11225  复杂 bash 语法被 preprocessing 搞坏
    · anthropics/claude-code#23740  把 ! 转义成 \\!，打断 jq
    上游原文：「There appears to be a regression of the v1.0.77 fix for heredoc and
    multiline string escaping.」

  本机三组对照实测（同一分钟，同一台机器）：
      写的      Bash 工具实得     PowerShell 工具实得
      \\n         \\n   OK            \\n     OK
      \\\\n        \\n   吃了一层       \\\\n    OK
      \\\\\\n       \\\\n  吃了一层       \\\\\\n   OK
      \\\\         \\    吃了一层       —
  · 带引号的 heredoc（<<'EOF'，POSIX 规定完全字面）照吃
  · printf '%s' 'x:\\\\n'（单引号，bash 绝不处理反斜杠）也照吃
    => 排除 shell、排除引号、排除 heredoc，锁定【工具层】
  · $HOME 不展开、反引号不执行 => 引号本身是生效的，唯独反斜杠被吃一层

【为什么会静默崩 —— 两层转义叠加】

    我写 "\\\\n"  ->[工具吃一层]->  python 收到 "\\n"  ->[python 解释转义]->  落地成【真换行】
    我写 "C:\\\\Users" -> python 收到 "C:\\Users" -> \\U 是 Unicode 转义 => SyntaxError

  历史发作（lessons 形状 J）：sed -i 把一整行代码换成字母 X（**没报错**，静默损坏）；
  2026-08-20 一天内又两次：写 hook 测试时 \\n 落成真换行 -> SyntaxError。

【根治，不是补救】
  ① 写/改文件 -> 用 Write / Edit 工具（不经这条 quoting 管线，零转义层）—— 首选
  ② 必须在 shell 里跑 Python 且要换行 -> chr(10) / os.linesep / r'''...''' 原始字符串
  ③ 实在要在 shell 里传字面反斜杠 -> 改用 PowerShell 工具（实测不吃）

【先查现成（2026-08-20）-> 判定 自建】
  · 上游 6 个 issue 全是**故障报告**，没有可用的解法或补丁
  · 本机 shell-writes-code-gate.py 判据是「heredoc 重定向到代码文件 / sed -i 改代码文件」，
    而它**明确豁免「把脚本喂给 stdin 执行」**（python - <<EOF）——今天崩的正是这个口子：
    喂进去的脚本自己在写文件，双反斜杠照样被吃。本闸补的就是这条缝，不重复它。
  · gh search「shell escaping guard agent」0 命中；topic:claude-code+hooks 前 20 无同类

【判据（客观、纯文本）】
  命令含【连续 >=2 个反斜杠】 且 这条命令在【写文件 / 传代码】
  （heredoc、> 重定向、tee、sed -i、python -c/-、node -e、perl -e）=> 拦。
  单个反斜杠不拦（printf '%s\\n'、grep 转义都安全）。PowerShell 工具不拦（实测不吃）。

自测：python backslash-eater-gate.py --self-test
"""
import json
import os
import re
import sys

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import guard_common  # noqa: F401  记账用
except Exception:
    pass

# 连续 >=2 个反斜杠 = "我本意要字面反斜杠"的信号，而它必被吃掉一层
DOUBLE = re.compile(r"\\{2,}")

# 只在"写文件 / 传代码"场景拦；纯查询里的双反斜杠无害
WRITES = re.compile(
    r"<<-?\s*['\"]?\w+"                                # heredoc
    r"|>\s*['\"]?[\w./\\:-]+"                          # 重定向写文件
    r"|\btee\b"
    r"|\bsed\s+-i\b"
    r"|\bpython[0-9.]*\s+-c\b|\bpython[0-9.]*\s+-\s"   # 传 python 代码
    r"|\bnode\s+-e\b|\bperl\s+-e\b",
    re.I)

MSG = """[X] 反斜杠吞噬闸:这条命令里有【连续反斜杠】,而 Bash 工具会【吃掉一层】——
写出来的东西和你想的不一样,而且往往【静默】不一样(不报错,文件坏了你不知道)。

根因已实测 + 上游确认(anthropics/claude-code #14361 / #1195 / #48317 / #11225 / #23740):
Bash 工具送进 shell 前跑的 quoting 管线会吃一层反斜杠。上游原话:
「There appears to be a regression of the v1.0.77 fix for heredoc and multiline string escaping」

本机对照实测:
    你写 \\\\n   -> shell 实得 \\n      (PowerShell 工具实得 \\\\n,不吃)
    你写 \\\\\\\\n  -> shell 实得 \\\\n
  · 带引号的 heredoc(<<'EOF',POSIX 规定完全字面)照吃
  · printf '%s' 'x:\\\\n'(单引号,bash 绝不处理反斜杠)也照吃
  => 不是 heredoc、不是引号、不是 bash,是【工具层】。

于是两层叠加:
    你写 "\\\\n"      -> python 收到 "\\n"      -> 落地成【真换行】
    你写 "C:\\\\Users" -> python 收到 "C:\\Users" -> \\U 是 Unicode 转义 => SyntaxError

改成下面任一条(按推荐排序):
  (1) 要写/改文件就用 Write / Edit 工具 —— 不经这条管线,零转义层。首选。
  (2) 必须在 shell 里跑 Python 且要换行 -> chr(10) / os.linesep / r'''...''' 原始字符串
  (3) 实在要在 shell 里传字面反斜杠 -> 改用 PowerShell 工具(实测不吃)

(lessons 形状 J:同一个转义坑一天崩 3 次,每次只补救不修根因。这次修的是根因。)"""


def check(cmd, tool="Bash"):
    if tool != "Bash" or not cmd:
        return None            # PowerShell 工具实测不吃反斜杠，不拦
    if not DOUBLE.search(cmd):
        return None
    if not WRITES.search(cmd):
        return None
    return MSG


def self_test():
    ok = [True]
    bs = chr(92)               # 用 chr 造反斜杠：本文件自身也要能被 shell 安全跑

    def t(name, cmd, want_block, tool="Bash"):
        got = check(cmd, tool) is not None
        if got != want_block:
            ok[0] = False
        print("  [%s] %-28s -> %s" % ("PASS" if got == want_block else "FAIL",
                                      name, "block" if got else "allow"))

    # (1) 今天真实崩掉的那两条
    t("heredoc 里写双斜杠n",
      "python - <<'EOF'" + chr(10) + "s=s.replace('a','b" + bs * 2 + "nc')" + chr(10) + "EOF", True)
    t("heredoc 写 Windows 路径",
      "python - <<'EOF'" + chr(10) + "p='C:" + bs * 2 + "Users'" + chr(10) + "EOF", True)

    # (2) 对照组：单反斜杠安全，不该拦
    t("printf 单反斜杠", "printf '%s" + bs + "n' hello > x.txt", False)
    t("grep 转义括号", "grep 'interface" + bs + "{" + bs + "}' src/", False)
    t("普通查询", "ls -la && git status", False)

    # (3) 有双反斜杠但不写文件 -> 不拦（无害）
    t("查询里带双斜杠", "grep 'a" + bs * 2 + "b' file.txt", False)

    # (4) PowerShell 工具不拦（实测不吃）
    t("PowerShell 同内容", 'python -c "p=' + "'C:" + bs * 2 + "Users'" + '"', False,
      tool="PowerShell")

    # (5) 其它写文件通道
    t("sed -i 带双斜杠", "sed -i 's/a/b" + bs * 2 + "nc/' x.py", True)
    t("重定向写文件", "echo 'a" + bs * 2 + "b' > out.txt", True)
    t("node -e", 'node -e "console.log(' + "'a" + bs * 2 + "b'" + ')"', True)

    print(chr(10) + ("全绿" if ok[0] else "有 FAIL"))
    return 0 if ok[0] else 1


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = data.get("tool_name")
    if tool not in ("Bash", "PowerShell"):
        sys.exit(0)
    msg = check((data.get("tool_input") or {}).get("command") or "", tool)
    if msg:
        sys.stderr.write(msg + chr(10))
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
