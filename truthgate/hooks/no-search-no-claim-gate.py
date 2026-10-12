#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Stop hook: 我说【某个东西不存在 / 项目里没有 / 只有你能给我】,但这一轮【一次都没搜过】→ 拦。

⛔ 起因(2026-09-06,Frank 甩截图纠正):
   他要 Atria SOFO 的停车自动化,我连说两轮「SOFO 是另一个系统」「那个网址项目里从来没有过记录,
   只有你能给」。他甩来一张截图:`season-parking.com/asg/parkerportalv2`。
   一查:**这个 URL 硬编码在 `scripts/parking_cli.py:49`**,工具 8-28 就端到端实测过;
   而且 `docs/guest-checkin-flow.md` 里白纸黑字写着同一个网址 ——
   **那份文档我在同一轮里刚从头读过一遍、还在里面改过字。**
   Frank:「我记得有给过你的,你确定没给过?」

⛔ 根因(比"我忘了"深一层,lessons 形状 2026-09-06-E):
   我读那份文档时带的问题是「入住流程是什么」,读完存成印象;
   后来问题变成「停车网址有没有」,我**没回去重读**,而是拿那次的印象回答 ——
   **印象是按当时的问题裁剪过的,换个问题它就不够用了。**

⛔ 先查现成(按铁律,2026-09-06 逐个读过 header):
   · `evidence-gate.py` —— 反方向(我说造了文件 → 查文件在不在)
   · `unread-evidence-guard.py` —— 产生了截图却没打开看
   · `already-known-guard.py` —— PreToolUse:这问题 PROGRESS 里查过没(防重复调查)
   · `prior-art-gate.py` / `search-layer-gate.py` / `search-breadth-gate.py` —— 造东西前有没有查开源/换关键词
   **没有一道在验「我说『没有』之前,本轮到底搜没搜过」** ⇒ 自建。

判据(全中才拦,窄触发):
  ① 本轮助手文本里有【不存在类断言】(项目里没有/从来没有过/查不到/不存在/只有你能给…)
  ② 本轮【零次搜索类工具调用】—— Grep/Glob/codegraph,或 Bash 里的 grep/rg/find/ls/dir/where
  ③ 不是在复述历史(「上次查过没有」这类过去式不算本轮新断言)
  = 我在凭印象说"没有" → 拦,逼我先跑一条 grep(零成本)再说。

安全:fail-open 异常放行 / 只拦一次(per-gate 标记) / 只读 transcript / 每次留日志。
放行出口:真跑一次搜索;或者这句"没有"说的是【物理边界】(手机/扫码/密码这类我本来就拿不到的)。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from guard_common import hook_log, turn_start_index, trig, load_transcript_tail, self_blocked_this_turn
except Exception:                      # guard_common 坏了不许连累这道闸(fail-open 铁律)
    def turn_start_index(msgs): return -1
    def hook_log(*a, **k): pass
    def trig(s, n=120): return (s or "")[:n]
    def load_transcript_tail(tp): return []
    def self_blocked_this_turn(*a, **k): return True

import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LOG = "no-search-no-claim-gate"

# ①【不存在类断言】—— 我凭印象宣布某个东西没有。
#   ⛔ 刻意只收【强断言】:含糊的"好像没有""我不确定有没有"不收(那本来就是诚实的不确定)。
NOT_EXIST = re.compile(
    r"项目里(?:从来)?(?:都)?没有|从来没有过|从没有过|压根没有|根本没有(?!人)"
    r"|(?:完全)?没有任何(?:记录|痕迹|东西|文件|脚本|工具|接口)"
    r"|(?:这个|那个|该)?(?:网址|入口|链接|地址|凭据|账号|密码|路径|文件|脚本|工具)[^。\n]{0,12}(?:我这边)?(?:确实)?没有"
    r"|我这边(?:完全)?没有(?:记录|这个|那个|任何)"
    r"|查不到(?:任何)?(?:记录|东西|它)|不存在(?:这个|任何)?"
    # ⛔ 2026-09-06 边界划清:「只有你能做 / 你去注册 / 我够不到」这一族归
    #   `capability-boundary-gate.py`(同日另一 session 为 NVIDIA key 那件事建的)管,这里【不收】,
    #   免得同一句话被两道闸各拦一次。本闸只管一件事:**说某个东西"不存在/没有记录",却没搜过**。
    r"|(?:doesn't|does not|didn't) exist|no such (?:file|record|script|tool)|not (?:in|found in) (?:the )?(?:project|repo)",
    re.I)

# ③ 复述历史 / 明确说的是过去那次 → 不算本轮新断言
HIST = re.compile(r"上(?:次|轮|回)|之前(?:那次|查过)|当时(?:没有|查不到)|历史上|以前那次|已经记过|lessons 里")

# 物理边界:我本来就拿不到的东西(手机/人脸/扫码/别人的密码)—— 说"没有"是实话,不该拦
PHYSICAL = re.compile(
    r"扫码|滑块|验证码|手机(?:在你|上|里)|你的手机|人脸|指纹|插(?:手机|USB)|物理设备|只有你(?:本人)?能(?:点|扫|输|操作)")

# ② 搜索类工具痕迹
SEARCH_TOOLS = {"Grep", "Glob"}
SEARCH_MCP = re.compile(r"codegraph", re.I)
# Bash/PowerShell 里算"真的搜过"的命令(要有查找语义,不是随便跑个 node)
SEARCH_CMD = re.compile(
    r"(?:^|[\s;|&(])(?:grep|rg|ripgrep|ack|ag|find|fd|ls|dir|where|locate|Select-String|Get-ChildItem)\b"
    r"|codegraph|--selftest\s*$",   # 注:--selftest 不算搜索,这里刻意不放行,见下方 _has_search
    re.I)
# 上面那条最后一项是历史遗留写法,真正判据在 _has_search 里(只认查找类命令)
_REAL_SEARCH_CMD = re.compile(
    r"(?:^|[\s;|&(])(?:grep|rg|ripgrep|ack|ag|find|fd|ls|dir|where|locate|Select-String|Get-ChildItem)\b"
    r"|codegraph", re.I)


def _has_search(turn):
    """本轮有没有【真的搜过】。Grep/Glob 工具、codegraph、或 shell 里的查找命令都算。"""
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            nm = str(c.get("name", ""))
            if nm in SEARCH_TOOLS or SEARCH_MCP.search(nm):
                return True
            if nm in ("Bash", "PowerShell"):
                if _REAL_SEARCH_CMD.search(str((c.get("input") or {}).get("command", ""))):
                    return True
    return False


def _text_of(turn):
    out = []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            out.append(content)
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                out.append(c.get("text", ""))
    return "\n".join(out)


def main():
    data = json.loads(sys.stdin.read())
    if not data.get("stop_hook_active"):
        self_blocked_this_turn(LOG, turn_start=True)
    elif self_blocked_this_turn(LOG):
        hook_log(LOG, "skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
    if not tp:
        hook_log(LOG, "skip(no transcript_path)")
        return
    msgs = load_transcript_tail(tp)
    if not msgs:
        try:
            msgs = [json.loads(l) for l in open(tp, encoding="utf-8", errors="replace") if l.strip()]
        except Exception:
            hook_log(LOG, "skip(transcript unreadable)")
            return
    i = turn_start_index(msgs)
    turn = msgs[i + 1:] if i >= 0 else msgs

    text = _text_of(turn)
    tail = text[-1500:]                       # 断言通常在收尾段
    m = NOT_EXIST.search(tail)
    _semhit = ""
    if not m and not _semhit:
        try:
            from guard_common import claim_kinds as _ck
            if "absence" in _ck(tail[-1500:], kinds=("absence",)):
                _semhit = "语义判定:词表没命中,但这话语义上就是该类断言"
        except Exception:
            pass
    if not m:
        hook_log(LOG, "allow(no not-exist claim)")
        return
    if HIST.search(tail):
        hook_log(LOG, "allow(复述历史,不是本轮新断言)")
        return
    if PHYSICAL.search(tail):
        hook_log(LOG, "allow(物理边界:手机/扫码/密码这类我本来就拿不到)")
        return
    if _has_search(turn):
        hook_log(LOG, "allow(本轮真的搜过了)")
        return

    # ⛔ 防死循环:拦之前先给【自己】打标记 —— 下一次 Stop 走上面的 elif 直接跳过。
    #   漏这一句 = 我拦完它又拦、无限循环(这条是本闸自己的回归测试当场抓到的,别删)。
    self_blocked_this_turn(LOG, mark=True)
    hook_log(LOG, "BLOCK(claimed-not-exist without any search) trig=" + trig(tail, 160))
    print(json.dumps({"decision": "block", "reason":
        "⛔ 没搜就说没有闸:你这轮断言【某个东西不存在/项目里没有/只有 Frank 能给】"
        f"(命中:「{(m.group(0) if m else _semhit)[:24]}」),但整轮【一次搜索都没做过】——"
        "没跑过 Grep/Glob、没跑过 grep/rg/find/ls、也没查 codegraph。\n"
        "⛔ 2026-09-06 实录:我两轮说「那个停车网址项目里从来没有过记录,只有你能给」,"
        "而它**硬编码在 `scripts/parking_cli.py:49`**,工具 8-28 就实测过;"
        "同一个网址还写在 `docs/guest-checkin-flow.md` 里——**那份文档我同一轮刚从头读过、还改过字**。"
        "根因:我读文档时带的是【上一个问题】,换了问题却拿旧印象回答。\n"
        "⇒ 现在跑一条搜索再说(零成本,一秒钟):\n"
        "   `grep -rn \"<那个东西的名字/网址/关键词>\" .`  或 Grep/Glob 工具 或 codegraph_explore\n"
        "⇒ 搜完再下结论:找到了就用它;真没有,再说『没有』——这时候你手上有证据。\n"
        "(若这句『没有』说的是【手机/扫码/密码】这类你本来就拿不到的物理边界,把措辞收窄到那件事即可放行。)"},
        ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                    # fail-open:这道闸自己坏了,绝不挡住工作
        try:
            hook_log(LOG, "error(fail-open): %s" % str(e)[:160])
        except Exception:
            pass
