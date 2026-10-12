#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""free-first-gate — 拦【推荐/采用/搭建一个【付费】方案，而本轮从没搜过免费替代】。

⛔ 来历（2026-09-08，Frank：「为何superego没拦你没开火，修到开火为止，不能有遗漏」）：
   诊断"抓不到"，我一头扎进【付费】的 TikHub（还是个余额=0 的号），花了大半轮建包壳、
   接进 worker、算成本 —— **全程没搜过一次免费替代**。而免费的满地都是：
   tikwm（免密钥下 TikTok，实测通）、cobalt/Evil0ctal 可自建、yt-dlp 本就覆盖 1000+ 站。
   Frank 一句「你都白痴的…随便上网都可以找到下载社交媒体的工具的免费的，你没找到哪些网站？」点破。
   查证：`~/.claude/hooks/` 里 **一个免费/付费相关的闸都没有**（只有 budget 测试文件），
   而"免费优先"在 lessons 里出现 13 次 —— 原则天天写、没有一道闸兜底 ⇒ 只能上机器拦。

⛔ 与全局至高铁律的关系：那条第④点「能白嫖就白嫖，免费优先」+ 第⑤点「superego 必须是真 hook，
   不是空拦」。本闸就是把第④点落成第⑤点要求的【真 hook】。

判据（三条同时成立才拦，宁漏勿误杀）：
  ① 本轮交付里【承诺/推荐/采用/搭建一个付费方案】：付费/计费/收费/充值/订阅/credits/余额/
     按次收费/花钱买/paid api… 这类【正在花钱】的措辞。
  ② 本轮全程【没有任何一次免费替代的痕迹】——不管是工具调用(web 搜索/gh/sota-check)
     还是正文里提到免费/开源/自建/yt-dlp/tikwm/cobalt… 只要碰过一次"免费这条路"就放行。
  ③ 不在过去式 / 复盘 / 立规矩 / 认错语境（复盘正是 superego 要的，别惩罚它）。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
try:
    from guard_common import hook_log
except Exception:
    def hook_log(name, msg, ctx=""):  # 兜底桩:必须收 3 参(conformance 判据②)
        pass

# ① 承诺/推荐【付费】方案（正在花钱的措辞）
PAID_COMMIT = re.compile(
    r"(付费|计费|收费|充值|订阅|subscription|付钱|花钱(买|充|下|用)?"
    r"|按(请求|次|条|量|个)[^。;；\n]{0,6}(收费|计费|钱|费)"
    r"|余额(不足|为 ?0|见底|不够|耗尽)|insufficient\s*(balance|credit)"
    r"|paid[-\s]?(api|tier|plan|tool|service)|要充|去充|先充"
    r"|\$\d+\s*(起|/|美元|块|刀)|每(条|次|个)[^。;；\n]{0,4}[\$￥¥]?\d)", re.I)

# ② 免费这条路的痕迹（工具痕迹 or 正文提到；碰过一次就放行）
FREE_TRACE = re.compile(
    r"(免费|白嫖|免密钥|无需(付费|钱)|不花钱|零成本|开源|open[-\s]?source"
    r"|self[-\s]?host|自(建|己搭|部署)|\bfree\b"
    r"|yt[-_]?dlp|tikwm|cobalt|gallery-?dl|you-?get|snap[a-z]*|evil0ctal|douyin\.wtf"
    r"|web\.py|websearch|web_search|firecrawl|easy_anysearch|gh (search|api)"
    r"|sota[-_]?check|六宇宙|last30days|awesome-)", re.I)

# ③ 过去式 / 复盘 / 立规矩 / 认错 —— 不是"我现在就要花钱"
PAST_CTX = re.compile(
    r"(上一轮|之前|昨天|历史上|曾经|原话|引述|复述|教训|lessons|形状 ?20"
    r"|下次(要|再|该|别)|以后(要|再|该|别)|反向指纹|来历|案发|复盘|归因"
    r"|我(今天|这轮|刚才|本轮)的?错|我犯的|我错在|认错|误判|纸老虎|为何没拦|没(开火|拦住)"
    r"|别(再|又)(用|扎进|fixat)|不该(用|扎)|收回|撤回|自我更正)")


def _log(msg, ctx=""):
    hook_log("free-first-gate", msg, ctx)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp or not Path(tp).exists():
        _log("skip(no transcript)")
        return 0

    sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
    try:
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        start = turn_start_index(msgs)
        turn = msgs[start:] if start >= 0 else msgs
    except Exception:
        try:
            msgs = [json.loads(l) for l in open(tp, encoding="utf-8") if l.strip()]
        except Exception:
            return 0
        turn = msgs[-40:]

    free_seen = False
    last_text = ""
    all_text = []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            last_text = content
            all_text.append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                last_text = c.get("text") or ""
                all_text.append(last_text)
            elif c.get("type") == "tool_use":
                blob = json.dumps(c.get("input") or {}, ensure_ascii=False)
                all_text.append(blob)
                if FREE_TRACE.search(blob):
                    free_seen = True

    joined = "\n".join(all_text)
    if FREE_TRACE.search(joined):
        free_seen = True

    tail = last_text[-1800:]
    hit = PAID_COMMIT.search(tail)
    if not hit:
        _log("pass(no paid-commit)")
        return 0
    if free_seen:
        _log("pass(free trace seen)")
        return 0
    if PAST_CTX.search(tail):
        _log("pass(past/postmortem ctx)")
        return 0

    msg = (
        "⛔ 免费优先闸：你这轮【推荐/采用/搭建一个付费方案】(命中: "
        + (hit.group(0) or "")
        + ")，但整轮【一次免费替代都没搜/没提】。\n"
        "⛔ 全局至高铁律第④条：能白嫖就白嫖，免费优先；免费的满地都是，先穷尽再谈付费。\n"
        "⛔ 2026-09-08 实录：我扎进付费 TikHub(还是余额=0的号)大半轮，从没搜免费的 ——\n"
        "   而 tikwm 免密钥就能下 TikTok、cobalt/Evil0ctal 可自建、yt-dlp 本就覆盖 1000+ 站。\n"
        "现在先走【六宇宙·免费】再回来：\n"
        "  · web 搜『免费/开源/self-host <能力>』→ `py -3 ~/.claude/web.py search`\n"
        "  · GitHub 现成开源 → `gh search repos` / `gh api`（话题页）\n"
        "  · 本机已有的免费工具/skill（yt-dlp / xhs_extract / anti-scraping…）\n"
        "  · 免费公共 API（tikwm 等免密钥）/ 可自建的免费服务（cobalt / Evil0ctal）\n"
        "⛔ 证明【免费的都不行】(贴每条的失败证据) 再用付费；或用户明确要付费，才放行。"
    )
    _log("BLOCK", (hit.group(0) or ""))
    print(msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
