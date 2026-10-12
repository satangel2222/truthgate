#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""search-breadth-gate — 拦【只查了一两个宇宙，就下领域级断言】（Claude 收尾）。

⛔ 来历(2026-08-14,Frank:「上次让你找工具,你就只找到 30%,还漏了那么多」):
   我只跑了 `gh search` 一族关键词、每组只取前 20 条、从不翻页,就出具了《全链路选型定案》,
   并写下「gh 是世界大免费工具库——但这三环 GitHub 给不了强货」。补上翻页 + 话题页 + 网页搜索后,
   同一个领域从 308 个变成 7446 个;而他本机早就装着 9 个同类 skill。

⛔ 2026-10-02 从「数工具」改成「数宇宙」(Frank:「全都要」,六宇宙分三层接进 TruthGate 的第 3 层):
   旧判据数的是工具种类,gh search + 话题页 + gh api 能凑成 3 种过关 —— 其实都是 GitHub 一个宇宙。
   现在要 ≥3 个宇宙且含①本机(REQUIREMENTS 第 2 条 3 档:先内部记录,再外部调研);检索数最近 3 轮。
   判据(断言词表、工具→宇宙、豁免、空管道 / 时效 / 中英)全部搬进 ~/.truthgate/six_universes.py,
   AG 桥接调的是同一份;本文件只负责读本轮会话记录、量每条检索回来多大。
   词表同日按 9/16~10/01 的 31 次真实记账收窄(23 次命中里 15 次是「测试都失败了」这类普通句子),
   考题 c083~c102。改前的历史注释在 git 里(748e82a 及更早)。

⛔ 与 prior-art-gate 的分工:那道只判【查没查过】,本道判【查了几个互相看不见的宇宙】。

⛔ 2026-10-04 加一条不看措辞的(Frank「授权这里修复」):本轮翻过别人软件的安装目录,而最近 3 轮查过的外部宇宙不到 2 个 ⇒ 拦。
   来历:排查 Antigravity 开窗口看不见,我拆了它的程序、下了根因结论、写了修复工具,全程没上网;结论里没有
   「没有现成 / 最强是」这类词,本道闸记的是 pass。判据在 six_universes.probe_verdict;这一条每轮只拦一次
   (他只是让我找某个配置文件在哪的时候,不该被逼着搜三遍)。
   同日外审后再加一条兜底:工具目录里这一轮多了新脚本(看文件创建时间,不管是写的、复制的、robocopy 还是脚本生成的),
   而最近 3 轮没查过本机以外 ⇒ 拦(six_universes.new_tool_files / new_tool_verdict)。调用前的两道闸
   (prior-art-gate 管 Write、shell-writes-code-gate 管 cp/mv)量不全所有走法,这里按结果量。
   这两条用【严格通道】(strict_channels_of):本机 grep 里出现 reddit.com、echo 一个域名都不算联网。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/.truthgate"))
from six_universes import (channels_of, judge, probe_of, probe_verdict, strict_channels_of,  # noqa: E402
                           new_tool_files, new_tool_verdict, actions_text)


def _turn_epoch(msgs):
    """本轮从什么时候开始(第一条带时间的消息)。不知道 ⇒ 无穷大 = 不认任何新文件。"""
    from datetime import datetime
    for m in msgs:
        ts = m.get("timestamp")
        if ts:
            try:
                return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
            except Exception:
                break
    return float("inf")

LOG = Path.home() / ".claude" / "hooks" / "search-breadth-gate.log"


def _log(m):
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(m + "\n")
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp or not Path(tp).exists():
        _log("skip(no transcript)")
        return 0
    try:
        from guard_common import load_transcript_tail, is_real_user_msg
        msgs = load_transcript_tail(tp)
        # 检索数【最近 3 轮】(本轮 + 前两轮),不是只数本轮:2026-10-02 留出集里「5 个最 SOTA 的 OCR 部署完成」
        # 在调研之后的 4 轮总结里反复出现,只数本轮就轮轮误拦。窗口再大就会把别的话题的检索也算进来。
        users = [i for i, m in enumerate(msgs) if is_real_user_msg(m)]
        turn = msgs[users[-3]:] if len(users) >= 3 else msgs
        this_turn = len(turn) - (len(msgs) - users[-1]) if users else 0   # 本轮在 turn 里从第几条开始
    except Exception:
        try:
            msgs = [json.loads(l) for l in open(tp, encoding="utf-8") if l.strip()]
        except Exception:
            return 0
        turn = msgs[-40:]
        this_turn = 0

    channels, search_ids, sizes, last_text, probes = set(), set(), [], "", []
    strict = set()
    for idx, m in enumerate(turn):
        content = (m.get("message") or {}).get("content") or []
        if m.get("type") != "assistant":
            # 工具结果挂在非 assistant 消息里,按 tool_use_id 对回去量大小(2026-09-08:通道够 ≠ 通道有回话)
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in search_ids:
                    sizes.append(len(json.dumps(c.get("content") or "", ensure_ascii=False)))
            continue
        if isinstance(content, str):
            last_text = content
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                last_text = c.get("text") or ""
            elif c.get("type") == "tool_use":
                blob = json.dumps(c.get("input") or {}, ensure_ascii=False)
                got = channels_of(c.get("name") or "", blob)
                if got and c.get("id"):
                    search_ids.add(c["id"])
                channels |= got
                strict |= strict_channels_of(c.get("name") or "", blob)
                if idx >= this_turn:          # 拆没拆只数本轮(检索数最近 3 轮):不然一次翻目录会连拦三轮
                    p = probe_of(c.get("name") or "", blob)
                    if p:
                        probes.append(p)

    # 只看事实的两条(拆别人的软件 / 工具目录里多了新脚本)。每轮只拦一次:
    #   新一轮的第一次收尾(stop_hook_active=False)先清标记(不管这次有没有判决 —— 外审:原来只在有判决时清,
    #   上一轮的旧标记会让这一轮直接跳过),拦过就落标记。这一段出任何错都只丢它自己。
    fact = None
    try:
        from guard_common import self_blocked_this_turn as _sb
        if not data.get("stop_hook_active"):
            _sb("search-breadth-fact", turn_start=True)
        if _sb("search-breadth-fact"):
            _log("skip(fact checks: already blocked this turn)")
        else:
            fact = probe_verdict(strict, probes)
            if not fact:
                now_turn = turn[this_turn:]
                end = _turn_epoch(reversed(now_turn))          # 这一轮最后一条消息的时间(实时跑 ≈ 现在)
                fact = new_tool_verdict(
                    new_tool_files(_turn_epoch(now_turn), actions_text(now_turn),
                                   until=None if end == float("inf") else end + 120),
                    strict, actions_text(turn))
            if fact:
                _sb("search-breadth-fact", mark=True)
    except Exception as e:
        _log("fact-check error %r" % (e,))
        fact = None
    verdict = fact or judge(last_text[-1500:], channels, sizes)
    if not verdict:
        _log("pass channels=%s probes=%d" % (",".join(sorted(channels)), len(probes)))
        return 0
    tag, reason = verdict
    _log(tag)
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
