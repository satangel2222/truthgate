#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复读闸(Stop):被别的 Stop 闸拦下后,我再收尾时【把上一条长回复原样重贴一遍】⇒ 拦,只准发增量。

起因 2026-09-26 Frank 甩两张截图:「为何你会变成复读机,重复两次,正常吗?」—— 同一早上三次:
每次被 Stop 闸拦,我补完动作后把整段回答(1~2 千字)重贴,只在开头加一句「XX 补完」。他屏幕上看不见拦截,只看见两份一样的长文。
病根:我在赌闸(怕只发一句会被判"没答他"),不是在为他写。口头记住没用(同早已三次),所以做成闸。

判据(纯事实,不读措辞):本轮(最后一条真实用户输入之后)我发过的文本里,只要有一条和这次收尾的文本
【长度 ≥ 400 字 且 相似度 ≥ 0.8】⇒ 拦。相似度 = difflib 序列比;0.8 是 8 成重合,加一段开场白仍会中,真正改写不会中。
闸自己坏了不许堵人(任何异常 → 放行)。
"""
import sys, os, io, json, difflib

sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
MIN_LEN = 400
RATIO = 0.8


def _text(row):
    c = (row.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text")


def turn_assistant_texts(transcript_path):
    """本轮(最后一条真实用户输入之后)所有 assistant 文本,按时间序;Stop 闸的反馈行不算用户输入。"""
    rows = []
    for ln in open(transcript_path, encoding="utf-8", errors="replace"):
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    last_user = -1
    for i, r in enumerate(rows):
        if r.get("type") != "user" or r.get("isMeta") or r.get("isCompactSummary"):
            continue
        t = _text(r)
        if t.strip() and not t.lstrip().startswith(("Stop hook", "<command-", "[Request interrupted")):
            last_user = i
    out = []
    for r in rows[last_user + 1:]:
        if r.get("type") == "assistant":
            t = _text(r).strip()
            if t:
                out.append(t)
    return out


def check(last_text, earlier_texts):
    """纯函数。last_text = 这次收尾的文本;earlier_texts = 本轮更早的文本(不含它自己)。返回拦截文案或 None。"""
    last = (last_text or "").strip()
    for n, prev in enumerate(earlier_texts, 1):
        if len(prev) < MIN_LEN:      # 只有【长文】重贴才算复读;短句原样再说(「闸误报,内容不变」)不算。last 短而 prev 长时相似度天然低,不用再单独卡
            continue
        sm = difflib.SequenceMatcher(None, prev, last, autojunk=False)
        if sm.quick_ratio() < RATIO:
            continue
        r = sm.ratio()
        if r >= RATIO:
            return ("⛔ 复读闸:这条收尾和你本轮第 %d 条回复重合 %d%%(%d 字)。你被别的闸拦下后把整段重贴了一遍 ——\n"
                    "   Frank 屏幕上看不见拦截,只看见两份一样的长文(2026-09-26 他甩截图问「为何你会变成复读机」)。\n"
                    "⇒ 只发【增量】:补了什么、结果几比几、「上面那段不变」一句话。别重贴全文,别为了过别的闸赌一把。"
                    % (n, round(r * 100), len(last)))
    return None


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)
    tp = data.get("transcript_path")
    text = data.get("last_assistant_message") or ""
    if not tp or not os.path.exists(tp):
        sys.exit(0)
    try:
        texts = turn_assistant_texts(tp)
        # 最后一条通常就是 last_assistant_message 本身,比对时去掉它
        if texts and texts[-1].strip() == text.strip():
            texts = texts[:-1]
        vio = check(text, texts)
    except Exception:
        sys.exit(0)
    if vio:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from guard_common import hook_log
            hook_log("no-repeat-reply-gate", "BLOCK 重贴上一条长回复", text[:80])
        except Exception:
            pass
        print(vio, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
