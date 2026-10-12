#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checklist 完成度闸 —— 拦【清单上还挂着没做的,我的收尾却没逐条交代】。

⛔ 起因(2026-09-11,Frank 原话):
   「这里每一道问题你都要做个 todo checklist plan,做完要 mark 全部做了没有,
    这个要 superego 加多一个新 gate,不然每次都做不完整」。
   同一天他连发 7 条需求,我的老毛病是做完 3 条就用"已完成"的口吻收尾,剩下 4 条静默消失。

先查现成(2026-09-11,hooks 下扫 promise/false-done/scope-completeness/commitment-execution 四道):
   全都在判【我那句话的措辞】,没有一道去读【清单文件本身】。
   而清单是唯一不靠我措辞的真相 —— 措辞我能绕,文件里的 `- [ ]` 绕不过去。

判据(三步,全是确定性的,不猜意图):
   ① 找清单:cwd 下【48 小时内改过】的 TODO-*.md(老清单不追,防永远拦)
   ② 抽未勾项:`- [ ] **A1 · …` 抽出 ID(没有 ID 的用前 10 个字当键)
   ③ 本轮我写的所有文字里,每个未勾项都必须被点名 —— 缺一个就拦,列出没交代的
⇒ 做完就去勾 [x];做不了就在回复里写明是哪条、为什么、等谁。
   **不许清单上挂着、回复里不提、就收工。**
不误伤:没清单 = 放行;全勾完 = 放行;逐条点名了 = 放行(做不完不是罪,不交代才是)。
"""
import glob
import json
import os
import re
import sys
import time

FRESH_H = 48
ITEM = re.compile(r"^\s*-\s*\[( |x|X)\]\s*(.+)$")
ID = re.compile(r"^\*\*([A-Z]\d{1,2})\b")


def find_checklists(cwd, now=None):
    now = now or time.time()
    return [p for p in glob.glob(os.path.join(cwd or ".", "TODO-*.md"))
            if now - os.path.getmtime(p) < FRESH_H * 3600]


def open_items(paths):
    """返回 [(键, 原文)]。键 = ID(A1/B2…),没有 ID 用去掉 ** 的前 10 个字。"""
    out = []
    for p in paths:
        try:
            lines = open(p, encoding="utf-8").read().splitlines()
        except Exception:
            continue
        for ln in lines:
            m = ITEM.match(ln)
            if not m or m.group(1).lower() == "x":
                continue
            body = m.group(2).strip()
            mid = ID.match(body)
            out.append((mid.group(1) if mid else body.replace("*", "")[:10], body[:60]))
    return out


def _is_quoted(line):
    """原样贴出来的清单行(`- [ ] **A5 · …`)= 引用清单原文,不算交代。
    ⛔ 这道闸的【引用】风险和兄弟闸方向相反:它判的是"有没有提到",引用只会让我多提到、不会误拦;
       真正的洞是把 TODO 文件整段贴进回复 ⇒ 每个 ID 都"提到了" ⇒ 一句没解释就过闸。"""
    return bool(ITEM.match(line))


def missing(items, reply):
    """模块级真函数(测试直接调它,不抄副本 —— promise-gate 的教训)。"""
    reply = "\n".join(ln for ln in (reply or "").splitlines() if not _is_quoted(ln))
    miss = []
    for key, body in items:
        if re.fullmatch(r"[A-Z]\d{1,2}", key):
            hit = re.search(r"(?<![A-Za-z0-9])" + key + r"(?!\d)", reply)
        else:
            hit = key in reply
        if not hit:
            miss.append((key, body))
    return miss


def _mentioned(name, tp):
    """只追【本会话读写过/提到过】的清单 —— 本机常同时开 3~5 个会话,别让别的会话替这份清单挨拦(外审 2026-09-11)。"""
    if not tp or not os.path.exists(tp):
        return True        # 读不到会话记录就退回旧行为:宁可多问一句,别静默放过
    try:
        with open(tp, "r", encoding="utf-8", errors="replace") as f:
            return any(name in line for line in f)
    except Exception:
        return True


def final_turn_text(transcript_path):
    """本轮(最后一条真用户消息之后)我写的全部文字。tool_result 也是 type=user,要跳过。"""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    rows = []
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    # ⛔ 2026-09-11 Frank「你说了两次重复,为何?」:原来凡带文字的 user 消息都当回合起点,
    #   而 Stop 闸的拦截反馈也是带文字的 user 消息(isMeta) ⇒ 每被任一道闸拽回一次,"本轮"就被截成
    #   只剩最新一条回复 ⇒ 前面已逐条点名的 A1/A2/A5 不算数 ⇒ 逼我整段重说一遍。
    #   ⇒ 回合边界改用 guard_common 共用判据(跳过 tool_result / hook 反馈 / 系统通知)。
    try:
        from guard_common import is_real_user_msg as _real
    except Exception:
        _real = lambda m: m.get("type") == "user" and not m.get("isMeta")
    texts = []
    for m in reversed(rows):
        c = (m.get("message") or {}).get("content")
        if m.get("type") == "user":
            real = (isinstance(c, str) or (isinstance(c, list) and any(
                isinstance(x, dict) and x.get("type") == "text" for x in c))) and _real(m)
            if real:
                break
            continue
        if m.get("type") == "assistant" and isinstance(c, list):
            texts += [x.get("text") or "" for x in c if isinstance(x, dict) and x.get("type") == "text"]
    return "\n".join(reversed(texts))


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return
    try:
        from guard_common import turn_budget_ok as _tbo      # 防无限 loop 的回合预算(同 scope-completeness-gate)
        tp = data.get("transcript_path")
        if tp and not _tbo(tp):
            return
    except Exception:
        pass
    paths = [p for p in find_checklists(data.get("cwd") or os.getcwd())
             if _mentioned(os.path.basename(p), data.get("transcript_path"))]
    if not paths:
        return
    # ⛔ 2026-09-11 实测竞态:Stop 闸触发时,我刚写的最后一条回复【还没落进 transcript】
    #    (回放:含最后一条 2392 字、不含 0 字)⇒ 只读 transcript 会把"已逐条点名"判成"一个字没提",每轮误拦。
    #    ⇒ 官方 Stop 输入直接给 last_assistant_message(multi-option-guard 已用),两者合并;
    #      transcript 仍要读,因为最后一条之前、工具调用中间写的交代只在那里。
    said = (data.get("last_assistant_message") or "") + "\n" + final_turn_text(data.get("transcript_path"))
    miss = missing(open_items(paths), said)
    if not miss:
        return
    names = ", ".join(os.path.basename(p) for p in paths)
    try:
        from guard_common import hook_log                    # 开火留证据:事后能判它拦得对不对
        hook_log("checklist-completion-gate", "BLOCK 未交代 %d 条" % len(miss), " ".join(k for k, _ in miss))
    except Exception:
        pass
    print("⛔ Checklist 完成度闸:清单(%s)上还有 %d 条没勾,你这轮的收尾一个字没提:" % (names, len(miss)),
          file=sys.stderr)
    for k, b in miss[:12]:
        print("   · %s  %s" % (k, b), file=sys.stderr)
    print("  ⇒ 做完的去勾 [x];做不了的在回复里逐条点名 —— 是哪条、卡在哪、等谁。\n"
          "  ⛔ Frank 2026-09-11:「做完要 mark 全部做了没有…不然每次都做不完整」。\n"
          "     做不完不是罪,清单挂着、回复不提、就收工才是。", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
