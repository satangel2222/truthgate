#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreToolUse hook: 浏览器自动化 / 爬取 / 联网搜索 / 工具选型时,
检查是否有更优工具(Skill/SOTA)可自动 invoke。

触发关键词: browser / scrape / fetch / douyin / crawl / search / yt-dlp
行为: inject 推荐命令到 stdout(不拦),让 Claude 自己决定是否 invoke。

按需触发,不常驻。Frank 明确要求:「需要的时候才去 invoke,
而不是天天每次硬塞上下文,影响我 coding」。

用法:
  py -3 ~/.claude/skills/anti-scraping/fetch.py grab(url)     # 三层回退自动走
  py -3 ~/.claude/skills/sota-check/sota_check.py <topic>     # 按需查 SOTA
  py -3 ~/.claude/skills/agent-cockpit/scripts/skill_index.py --grep <kw>  # 按需查 skill
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

import json, os, re, sys

RAW = sys.stdin.read()
try:
    DATA = json.loads(RAW)
except:
    sys.exit(0)

TOOL = DATA.get("tool_name", "")
CMD = str(DATA.get("tool_input", {}).get("command", "")).lower()

if TOOL not in ("Bash", "PowerShell"):
    sys.exit(0)

# 触发关键词
TRIGGER_PAT = re.compile(
    r"(?:playwright|puppeteer|selenium|camoufox|cloakbrowser|opencli|web-access|"
    r"browser-act|fetch\.grab|grab\(|curl.*douyin|wget.*douyin|yt-dlp|"
    r"douyin.*download|(?<!anti)scrape|crawl|scraping|anti-scraping|"
    r"browser[-_]routing|browser[_-]selection|which.*browser)",
    re.I,
)
# ⛔ 2026-09-10:先把【只被读/列/git 操作】的路径从命令里剥掉再匹配。
#   `git status hooks/anti-scraping-response-detector.py` 里的 anti-scraping 是文件名,不是我要用爬取工具 ——
#   升级闸因此拦了我(它是刚接进账本的,第一枪打在自己身上)。文件名≠意图。
#   但 `py -3 scrape.py` 里的路径是被【执行】的,那正是该提醒的时刻,不剥。判据见 guard_common.path_is_only_read。
_PATHLIKE = re.compile(r"[\w.~:\\/-]*[\\/][\w.-]+|\b[\w.-]+\.(?:py|js|mjs|cjs|ts|ps1|sh|md|json|html|css|txt)\b")
try:
    from guard_common import path_is_only_read as _only_read
    for _p in set(_PATHLIKE.findall(CMD)):
        if _only_read(CMD, _p):
            CMD = CMD.replace(_p, " ")
except Exception:
    pass
if not TRIGGER_PAT.search(CMD):
    sys.exit(0)

inject = """

======== 工具选型提醒 ========

在使用浏览器自动化/爬取工具前,先检查是否有更优方案:

1. 查同类 Skill(本机 724 个,按需搜):
   py -3 ~/.claude/skills/agent-cockpit/scripts/skill_index.py --grep <关键词>

2. 查 SOTA(当前最强工具):
   py -3 ~/.claude/skills/sota-check/sota_check.py <领域> --mine <你手上那个>

3. 本项目的反爬/浏览器路由:
   Read ~/.claude/browser-routing.md

=> 需要时 invoke,不需要就跳过。不自动注入上下文。
================================

"""
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "injectedText": inject,
    }
}, ensure_ascii=False))
