#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""no-user-data-gate — 拦【断言"我没有/找不到<用户的数据/链接/例子>",而本轮没去翻他的档案/日志/库】。

⛔ 来历（2026-09-09，Frank：「我之前不是自己有很多手动粘贴的旧链接，没被系统记录吗？不会用？
   穷尽gate是废了吗？修到能开火为止」）：
   他问抖音非公开能不能免登抓，我答"我手上没有一条非公开链接，没法测" —— **而他的历史粘贴链接
   就躺在 chat-archive / worker.log / gallery.db / Upstash 去重库里**，我一处都没翻就说"没有"。
   capability-boundary-gate 判的是"只有他能做"，判不了"我没有他的数据" 这个变种 ⇒ 漏了 ⇒ 补这道。

⛔ 与 capability-boundary-gate 的区别：那道管【动作只有他能做】；本道管【数据我声称没有】——
   而"没有"往往是假的，因为用户的历史输入几乎总在某个本地存储里，我只是没去查。

判据（三条同时成立才拦，宁漏勿误杀）：
  ① 本轮交付里断言【(我/手上/这边)没有/找不到/缺/拿不到 <链接/数据/记录/样本/例子/素材/URL/帖/note>】。
  ② 本轮全程【没有任何一次翻他数据仓的痕迹】—— chat-archive(q.js/q-*.js) / worker.log(grep) /
     gallery.db(sqlite) / Upstash/dedup(fwd:) / PROGRESS / 图库 items 之类。
  ③ 不在过去式 / 复盘 / 认错语境。
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

# ① 断言"没有他的数据/链接/例子"
NO_DATA = re.compile(
    r"(我|手上|这边|目前)?[^。;；\n]{0,6}"
    r"(没有(一条|任何)?|找不到|缺(一条|一个)?|拿不到|一条都没有|没有.{0,4}可(测|用|抓))"
    r"[^。;；\n]{0,12}"
    r"(链接|url|数据|记录|样本|例子|素材|帖|note|笔记|片子|视频链接|可测)", re.I)

# ② 翻过他数据仓的痕迹(工具入参或正文里出现即算查过)
STORE_TRACE = re.compile(
    r"(chat-archive|q\.js|q-\w+\.js|q-frank|q-session|q-window|q-full"
    r"|worker\.log|gallery\.db|\.db['\"\s]|sqlite|items|source_url"
    r"|Upstash|dedup|fwd:|lmQueue|/internal/tg-messages"
    r"|grep\s|glob|PROGRESS|brainq|vault_log)", re.I)

# ③ 过去式 / 复盘 / 认错
PAST_CTX = re.compile(
    r"(上一轮|之前|昨天|曾经|原话|复述|教训|lessons|形状 ?20|下次(要|再|该|别)|以后(要|再|该)"
    r"|我(今天|这轮|刚才|本轮)的?错|我犯的|我错在|认错|误判|纸老虎|为何没拦|没(开火|拦住)|收回|撤回)")


def _log(m, ctx=""):
    hook_log("no-user-data-gate", m, ctx)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp or not Path(tp).exists():
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

    store_seen = False
    last_text = ""
    allblob = []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            last_text = content
            allblob.append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                last_text = c.get("text") or ""
                allblob.append(last_text)
            elif c.get("type") == "tool_use":
                blob = json.dumps(c.get("input") or {}, ensure_ascii=False)
                allblob.append(blob)
                if STORE_TRACE.search(blob):
                    store_seen = True
    if STORE_TRACE.search("\n".join(allblob)):
        store_seen = True

    tail = last_text[-1800:]
    hit = NO_DATA.search(tail)
    if not hit:
        _log("pass(no no-data claim)")
        return 0
    if store_seen:
        _log("pass(store queried)")
        return 0
    if PAST_CTX.search(tail):
        _log("pass(past ctx)")
        return 0

    msg = (
        "⛔ 用户数据没查闸：你这轮断言【没有/找不到用户的数据或链接】(命中: "
        + (hit.group(0) or "").strip()
        + ")，但整轮【没翻过他的任何数据仓】。\n"
        "⛔ 2026-09-09 实录：我答『我手上没有非公开抖音链接，没法测』——而他的历史粘贴链接就躺在\n"
        "   chat-archive / worker.log / gallery.db / Upstash 里，我一处没查就说『没有』。Frank：『不会用？』\n"
        "⇒ 说『没有数据』之前，先翻这几处（他的输入几乎总在某个本地库里）：\n"
        "  · 历史对话/粘贴 → `node D:/chat-archive/q.js \"<关键词>\" --project <slug>`\n"
        "  · 本机处理日志 → `grep <关键词> lm-worker/worker.log`\n"
        "  · 已入库的数据 → `gallery.db` 的 items.source_url（sqlite）\n"
        "  · 去重/队列    → Upstash `fwd:` 键 / lmQueue\n"
        "⛔ 真翻过全空，再说『没有』并贴出你查了哪几处、各返回什么。"
    )
    _log("BLOCK", (hit.group(0) or "").strip())
    print(msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
