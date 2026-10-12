#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""archive-recall-gate — 拦【对"他以前做过的事"说找不到/记不得,却没查 chat-archive】。

判据(全部成立才拦,宁漏勿误杀):
  ① 本轮说了否定性断言(找不到/没有/不存在/失效了/记不得…)
  ② 该断言指向过去(之前/以前/上次/曾经/你说的那个/做过…)
  ③ 本轮没有调用过 chat-archive 的任何查询脚本
  ④ 本轮确实在检索(有搜索类工具调用),排除纯聊天
"""
import json, re, sys
from pathlib import Path

LOG = Path.home() / ".claude" / "hooks" / "archive-recall-gate.log"

DENIAL = re.compile(
    "(找不到|没找到|查不到|搜不到|不存在|没有这个|没有那个|已失效|失效了"
    "|记不得|想不起|我记错|没有记录|没有印象|NOT_EXISTS"
    "|镜像里没有|本地没有|零成果|零收获|命中 0)")

PAST = re.compile(
    "之前(跑通过|做过|跑过|试过|配过)"
    "|以前(跑通过|做过|跑过|试过|配过)"
    "|上次(做过|配过)|曾经(做过|配过)|原来做过|当初配过"
    "|你说的那个(?:工作|项目|工具)|你提过那个"
    "|我记得(?:你|他)说过|历史(?:上|里)做过|过去经验里|那时(?:配置|做过)")

NEG_PAST = re.compile("没有之前|没有以前|没之前|没以前")

ARCHIVE = re.compile(
    r"(chat-archive|chat_archive|q-sessions\.js|q-session\.js"
    r"|q-window\.js|q-full\.js|q-frank\.js|q\.js)", re.I)

SEARCHY = re.compile(
    r"(grep|rg\s|find\s|search|glob|--info|--list|rh_search|WebSearch"
    r"|gh\s+search|curl.*api|_index\.json|huggingface)", re.I)


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(m + "\n")
    except Exception:
        pass


def collect(turn):
    said, tools = [], []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        for c in ((m.get("message") or {}).get("content") or []):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                said.append(c.get("text") or "")
            elif c.get("type") == "tool_use":
                name = c.get("name") or ""
                inp = json.dumps(c.get("input") or {}, ensure_ascii=False)
                tools.append(name + " " + inp)
    return said, tools


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
        st = turn_start_index(msgs)
        turn = msgs[st:] if st >= 0 else msgs
    except Exception:
        return 0

    said, tools = collect(turn)
    blob = "\n".join(tools)
    tail = "\n".join(said)[-2500:]

    if ARCHIVE.search(blob):
        _log("pass(查过 chat-archive)")
        return 0
    if not SEARCHY.search(blob):
        _log("pass(本轮没有检索行为)")
        return 0
    d = DENIAL.search(tail)
    _semhit = ""
    if not d:
        try:
            from guard_common import claim_kinds as _ck
            if "absence" in _ck(tail[-1500:], kinds=("absence",)):
                _semhit = "语义判定:词表没命中,但这话语义上就是该类断言"
        except Exception:
            pass
    if not d and not _semhit:
        _log("pass(没有否定性断言)")
        return 0
    p = PAST.search(tail)
    if not p:
        _log("pass(断言不指向过去)")
        return 0
    if NEG_PAST.search(tail):
        _log("pass(否定+历史混用,非真实历史引用)")
        return 0

    _log("BLOCK 否定=%s 过去=%s" % ((d.group(0) if d else _semhit), p.group(0)))
    print(json.dumps({"decision": "block", "reason": (
        "\u26d0 档案召回闸:你说了「%s」、话题指向【%s】,本轮却一次都没查 chat-archive。\n"
        "实录:2026-08-18 Frank说「我之前做过最完整的15秒参考的claude h3工作流」。"
        "我绕了一整轮搜别的,答案一直在档案里。\n"
        "现在按【时间窗+整个session】读:\n"
        "  cd C:/Users/<username>/Desktop/chat-archive\n"
        "  node q-sessions.js <slug> <from> <to>\n"
        "  node q-session.js <session-id> --user\n"
        "  node q-window.js <from> <to> [slug]\n"
        "  node q-full.js <from> <to> <kw> [slug]\n"
        "  node q-frank.js \"<他的说法>\" [--slug X] [--from D]  # 只出他真的打的字\n"
        "(查完仍然没有,如实说「档案里也没有」即可放行——本闸只拦【没查就说没有】。)"
    ) % ((d.group(0) if d else _semhit), p.group(0))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
