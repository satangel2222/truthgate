# -*- coding: utf-8 -*-
"""PreToolUse gate: 拦住「用 Windows PowerShell 5.1 的 -Encoding utf8 写配置/代码文件」。

⛔ 为什么存在(2026-09-04 实录,lessons 形状 2026-09-04-D):
   我用 `Set-Content -Path settings.json -Encoding utf8` 改 ~/.claude/settings.json。
   看起来完全正确 —— 但 **Windows PowerShell 5.1 的 utf8 = UTF-8 WITH BOM**,
   文件头多了 EF BB BF 三个字节 => python json.load 抛 "Unexpected UTF-8 BOM",
   Claude Code 也读不了。**我把自己的配置写坏了,而命令报的是成功。**

   本机实测对照(同一条命令):
       PowerShell 5.1  -> 前三字节 239,187,191   (BOM)
       PowerShell 7.6.5-> 前三字节 104,101,108   (干净, 直接是 h,e,l)
   而 Claude Code 的 PowerShell 工具执行的是
   C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe = **5.1**,
   装了 PS7 也不会自动切 => 这个坑对我一直存在。

判据(全客观,不需要理解语义):
   命令里同时出现 ①写文件的 cmdlet ②-Encoding utf8(且不是 utf8NoBOM) ③目标是会被别的程序解析的扩展名
   => 拦。

放行口径:
   · 用了 UTF8Encoding / WriteAllText / utf8NoBOM      -> 本来就对
   · 目标是 .txt/.log/.csv 这类没人解析结构的           -> 不拦
   · 命令里带 BOM-OK 标记                              -> 明确要 BOM(极少见)
   · 读操作(Get-Content -Encoding utf8)                -> 不拦
"""
import json
import re
import sys

# 会被别的程序【解析结构】的扩展名 —— BOM 会让它们炸
RISKY_EXT = r"\.(?:json|jsonl|py|md|ya?ml|toml|js|mjs|cjs|ts|ini|cfg|xml|csproj|ps1|psm1|sh)\b"

WRITE_CMDLET = re.compile(r"\b(?:Set-Content|Out-File|Add-Content)\b", re.IGNORECASE)
# -Encoding utf8 但不是 utf8NoBOM / utf8BOM 显式写法
ENC_UTF8 = re.compile(r"-Encoding\s+(?:'|\")?utf8(?!NoBOM)(?:'|\")?\b", re.IGNORECASE)
SAFE_HINT = re.compile(r"UTF8Encoding|WriteAllText|WriteAllBytes|utf8NoBOM|BOM-OK", re.IGNORECASE)
RISKY_TARGET = re.compile(RISKY_EXT, re.IGNORECASE)


def check(cmd: str, tool: str) -> str:
    if not cmd:
        return ""
    if SAFE_HINT.search(cmd):
        return ""
    if not WRITE_CMDLET.search(cmd):
        return ""
    if not ENC_UTF8.search(cmd):
        return ""
    if not RISKY_TARGET.search(cmd):
        return ""

    return (
        "[X] BOM 闸: 这条命令用 Windows PowerShell 5.1 的 `-Encoding utf8` 写一个"
        "【会被别的程序解析的文件】——\n"
        "    PS 5.1 的 utf8 是 **UTF-8 WITH BOM**(文件头 EF BB BF),写出来的文件:\n"
        "      · python json.load -> Unexpected UTF-8 BOM\n"
        "      · Claude Code 读 settings.json -> 直接读不了\n"
        "      · 而 Set-Content 自己【报成功】,损坏是静默的\n"
        "\n"
        "    实录 2026-09-04: 我就是这么把 ~/.claude/settings.json 写坏的"
        "(lessons 形状 2026-09-04-D)。\n"
        "    本机实测: PS5.1 前三字节 239,187,191 / PS7.6.5 前三字节 104,101,108。\n"
        "    ⛔ 而 Claude Code 的 PowerShell 工具跑的就是 5.1,装了 PS7 也不会自动切。\n"
        "\n"
        "  改成下面任一条(按推荐排序):\n"
        "    (1) 要写文件就用 Write / Edit 工具 —— 零编码层,首选\n"
        "    (2) 用 Python 写: open(p,'w',encoding='utf-8') —— 默认无 BOM\n"
        "    (3) 必须留在 PowerShell:\n"
        "        [System.IO.File]::WriteAllText($p, $text, "
        "(New-Object System.Text.UTF8Encoding($false)))\n"
        "\n"
        "  (确实需要 BOM 的极少数情况,命令里加注释 BOM-OK 放行。)"
    )


def self_test() -> int:
    ok = [True]

    def t(name, cmd, should_block, tool="PowerShell"):
        got = bool(check(cmd, tool))
        good = got == should_block
        ok[0] &= good
        print("  %s %-46s 期望%s 实得%s"
              % ("OK " if good else "FAIL", name,
                 "拦" if should_block else "放", "拦" if got else "放"))

    print("== 该拦的 ==")
    t("Set-Content 写 json", "Set-Content -Path 'a\\settings.json' -Value $t -Encoding utf8", True)
    t("Out-File 写 py", "$x | Out-File -FilePath script.py -Encoding utf8", True)
    t("Add-Content 写 md", "Add-Content -Path notes.md -Value 'x' -Encoding utf8", True)
    t("引号包着的 utf8", "Set-Content -Path b.yaml -Encoding 'utf8'", True)
    t("Bash 里调 powershell 也算", "Set-Content -Path c.toml -Encoding utf8", True, "Bash")

    print("== 不该拦的 ==")
    t("已用 UTF8Encoding", "[System.IO.File]::WriteAllText($p,$t,(New-Object System.Text.UTF8Encoding($false)))", False)
    t("PS7 的 utf8NoBOM", "Set-Content -Path a.json -Encoding utf8NoBOM", False)
    t("写 txt(没人解析)", "Set-Content -Path a.txt -Encoding utf8", False)
    t("只是读", "Get-Content -Path a.json -Encoding utf8", False)
    t("没指定编码", "Set-Content -Path a.json -Value $t", False)
    t("明确要 BOM", "Set-Content -Path a.json -Encoding utf8  # BOM-OK", False)
    t("空命令", "", False)

    print(chr(10) + ("全绿" if ok[0] else "有 FAIL"))
    return 0 if ok[0] else 1


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)                      # fail-open:闸自己坏了绝不挡住一切
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
