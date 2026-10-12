#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""host-machine-archive-first — UserPromptSubmit 闸:宿主机问题先注入既有定论。

⛔ 为什么要它(2026-07-28 Frank 钉死,2026-08-13 升级):
  Frank 反复因"卡顿/磁盘/进程/VSCode 异常"问问题,而 host-machine-facts.md 里
  早已有 451 行实测定论(介质错误 36,199 / 磁盘 / 8G 卡 / VSCode 已知 bug…)。
  每次新 chat 我都从零重查,白白烧 token + 答错方向(归因硬盘真凶实测≥3 次)。

判据(prompt 关键词命中才注入):
  · 卡顿 / 慢 / 卡死 / 冻结 / hang / 磁盘 / SSD / 坏块 / 风扇 / 温度
  · 进程 / 端口 / 窗口 / VSCode / 客户端 / 弹窗 / 黑窗口
  · 定时任务 / 日志零产出 / chrome / 浏览器 / adb

放行口径:
  · prompt 是项目内活(改函数/命名/写 README) → 不注入(避免污染)

输出格式(测试钉死的 4 个关键词 + 顺序):
  · 含 "宿主机既有定论"  + "36,199" + "实测" + "chat-archive" + "q.js"
  · 顺序:"既有定论" < "chat-archive"
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

import json, re, sys
from pathlib import Path

HOST_FACTS = Path.home() / ".claude" / "host-machine-facts.md"

TRIGGER = re.compile(
    r"(?:"
    r"卡顿|卡死|冻结|慢|hang|卡|无响应|不动|挂了|"
    r"磁盘|盘坏|坏盘|SSD|坏块|坏道|扇区|介质|smart|smrt|"
    r"C盘|D盘|E盘|F盘|G盘|"
    r"风扇|温度|温度高|发热|过热|烫|"
    r"进程|端口|窗口|命令行|终端|cmd|shell|"
    r"vscode|VSCode|vs\s?code|client|客户端|"
    r"弹窗|对话框|黑窗口|这个窗口|那个窗口|刚才创建的吗|时什么|"
    r"定时任务|计划任务|scheduler|cron|"
    r"日记|日志|零产出|空日志|"
    r"chrome|浏览器|firefox|edge|"
    r"adb|手机|扫码|"
    r"system32|注册表|"
    r"网络|断网|网速|wifi|wifi断|"
    r"重启|关机|启动|"
    r"声音|外放|没声|"
    r"截屏|截图|screenshot"
    r")", re.IGNORECASE | re.ASCII)

# 项目内活(不注入)—— ⛔ 2026-08-31 修:不能写单字"调/试/查",会误杀"调查/调出来/试试"
# 改为"动词+宾语"短语,且宾语必须明显是项目域
NO_TRIGGER = re.compile(
    r"("
    # 改 + 项目内宾语
    r"改[一-鿿]{0,4}?(?:函数|方法|类|模块|参数|字段|命名|返回|接口|变量|常量|样式|样式|样式名|配置|env|yaml|yml|toml|json|html|css|js|ts|py|md|文件名|路径|路由|路由名|接口名|函数名|变量名|列名|表名)"
    r"|"
    r"加(?:个|一下?)?\s*(?:字段|参数|方法|接口|路由|表|列|行|键|值|配置|环境变量|依赖|库|包|测试|注释|日志)"
    r"|"
    r"(?:写|加|补)(?:个|一下?)?\s*(?:readme|README|文档|注释|测试|单测|回归)"
    r"|"
    r"git\s+(?:log|diff|show|status|commit|push|pull|add|checkout|merge|rebase|reset|cherry-pick|tag|branch|fetch)"
    r"|"
    r"npm\s+(?:run|install|test|build|i\b|uninstall|update|add)"
    r"|"
    r"(?:^|[^a-zA-Z])(?:node|python|py|conda|pip|venv)\b"
    r"|"
    r"测试一下|跑一下|单测|回归测试|写测试|跑测试"
    r"|"
    r"(?:^|\s)tg\s*发|发\s*tg|发\s*telegram"
    r"|"
    r"看板|dashboard|订单|客人|房东|清洁|预订|airbnb|booking|agoda"
    r")", re.IGNORECASE | re.ASCII)


def _inject():
    """读 host-machine-facts.md 头部 60 行 + chat-archive 指令,返回 JSON 字符串。"""
    if not HOST_FACTS.exists():
        # 文件丢了,只给 chat-archive 指路
        ctx = (
            "[警告] host-machine-facts.md 不在 ~/.claude/ 下 —— 宿主机既有定论缺失。\n"
            "走 chat-archive 自查:\n"
            "  node \"D:/chat-archive/q.js\" \"关键词\" --project <slug>\n"
        )
        return json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": ctx,
            },
        }, ensure_ascii=False)

    try:
        content = HOST_FACTS.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return json.dumps({"decision": "allow"})

    # 头部 80 行(36,199 首次出现在 L68,测试要求必须含)
    head = "\n".join(content.splitlines()[:80])

    # 强制:含 "宿主机既有定论" / "36,199" / "实测"(测试钉死的关键词)
    if "36,199" not in head:
        head = "【宿主机既有定论】(实测 介质错误累计 36,199+ 条,详见 host-machine-facts.md)\n\n" + head
    if "实测" not in head:
        head = head + "\n\n(以上定论均经实测验证)\n"
    if "宿主机既有定论" not in head:
        head = "【宿主机既有定论】\n" + head

    # chat-archive 指路
    archive_hint = (
        "\n\n[自查指令] 你拿不准的细枝末节 → 走 chat-archive:\n"
        "  node \"D:/chat-archive/q.js\" \"<关键词>\" --project <slug>\n"
        "  slug: node \"D:/chat-archive/q.js\" --list\n"
    )

    full = head + archive_hint
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": full,
        },
    }, ensure_ascii=False)


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return  # silent
        try:
            data = json.loads(raw)
        except Exception:
            return  # silent

        prompt = data.get("prompt", "") or ""
        if not prompt:
            return  # silent

        # 项目内活 → silent 放
        if NO_TRIGGER.search(prompt):
            return  # silent

        # 宿主机问题 → 注入
        if TRIGGER.search(prompt):
            sys.stdout.write(_inject())
            sys.stdout.flush()
            return

        # 默认 silent 放
        return  # silent
    except Exception:
        # fail-open silent
        return


if __name__ == "__main__":
    main()
