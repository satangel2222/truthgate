#!/usr/bin/env python3
r"""Stop hook: 防止"不懂装懂"——有能力查/搜/跑却说不懂。

2026-08-31 实录：
  Frank: "不是你能力边界能做能知道的事、你能力那么逆天、可以调动那么多工具、可以上网搜索、不是比我更厉害吗？"
  判据（Frank 原话）：能力边界内（查六个宇宙/能装/能改/能跑）= 不许说"我不懂"。
  触发：扫描本轮我所有 tool_result + assistant 输出，
    含"我不懂/不确定/可能/也许/I don't know/I'm not sure"等认怂词。
    若近期有 WebSearch/Bash/Grep/Read 等搜索类工具调用 → 降级为 warn（不是 block）。
    若没有任何搜索动作却说不懂 → deny。

安全：fail-open; 只 block 第一次; 状态坏了放行; 已知无解场景免检。
"""
import json, re, sys, os
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / ".unknowing-pretending.json"
LOG = HERE / "unknowing-pretending-gate.log"

# Frank 2026-08-31 原话判据：能力边界内 = 不许认怂
# 能做的动作类型
SEARCH_TOOLS = {
    "Bash", "Read", "Glob", "Grep", "WebSearch", "WebFetch",
    "mcp__codegraph__codegraph_explore", "mcp__weixin_reader__read_weixin_article",
    "DesignSync", "Bash",  # deduplicated but included
}

# 判据（Frank 2026-08-31 原话）：
#   搜了（WebSearch/Grep/Read/Bash）→ 可以说「没找到/不确定」（真没找到不丢人）
#   没搜 → 必须说「我搜了/没结果」，不能说「大概」「我猜」「可能吧」
# 核心改变：不再只看认怂词，而是看【搜了没 + 回答是否反映搜索结果】

# 已知无解 / 无需查 的安全话题（跳过）
SAFE_TOPICS = [
    "密码", "手机", "眼睛", "口味", "心情", "感受", "想吃什么",
    "想要", "觉得", "你的密码", "frank 的密码",
]


def _load_state():
    try:
        if STATE.exists():
            with open(STATE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_state(state):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass


def _hook_log(msg):
    ts = __import__("datetime").datetime.now().isoformat()
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _is_safe_topic(text):
    t = text.lower()
    return any(s in t for s in SAFE_TOPICS)


def _had_search_action(messages):
    """本轮有没有搜索/查证类工具调用"""
    for m in messages:
        if m.get("type") == "assistant":
            msg = m.get("message") or {}
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue
                tool = block.get("name", "")
                if tool in SEARCH_TOOLS:
                    return True
                # Bash 里含搜索关键词也算
                args = block.get("input") or {}
                cmd = str(args) + tool
                searchy = any(k in cmd.lower() for k in [
                    "grep", "rg", "find", "search", "query", "look", "check",
                    "ls ", "ls\n", "ls$", "dir ", "cat ", "head ", "wc ", "stat ",
                    "q-", "q.", "qfrank", "q-session", "q-window",
                ])
                if searchy:
                    return True
    return False


def _check(messages) -> tuple[bool, str]:
    """
    语义判断（新逻辑）：
    ① 搜了（WebSearch/Read/Grep/Bash/codegraph） → 可以说「没找到/不确定」（真搜了不算不懂）
    ② 没搜 → 不能说「大概/我猜/可能吧」这类【没搜就猜】的词

    旧逻辑（正则认怂词）的问题是：分不清「搜了但真没找到」和「没搜就说大概」。
    """
    state = _load_state()
    if state.get("this_turn_blocked"):
        return False, ""

    # ── ① 本轮有没有搜 ──────────────────────────────────────
    had_search = _had_search_action(messages)

    # ── ② 收集 assistant 文本 ──────────────────────────────────
    my_texts = []
    for m in messages:
        if m.get("type") == "assistant":
            msg = m.get("message") or {}
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        my_texts.append(block.get("text", ""))
            elif isinstance(content, str):
                my_texts.append(content)

    full_text = "\n".join(my_texts)

    # ── ③ 收窄判据：只抓【没搜却说猜词】的组合 ───────────────────
    # 不抓「搜了但说没找到」（那是对的），只抓【没搜 + 猜词】
    hedge_re = (
        "大概(是|吧|说)?|我猜|估计(是)?|也许(吧)?|可能(吧|是)?|或许(吧)?|"
        "should be|probably|might be|could be|maybe|perhaps\\b|"
        "我不知道|我不清楚|我不确定|我不明白|我不懂|"
        "I don't know|I don't understand|I'm not sure|I'm not certain|"
        "（不确定）|（不懂）|（不清楚）|"
        "(not sure)|(I'm not sure)|(not certain)"
    )
    HEDGE_RE = re.compile(hedge_re, re.IGNORECASE)

    hedge_match = HEDGE_RE.search(full_text)
    if not hedge_match:
        return False, ""   # 没有猜词 → 不拦

    hedge_phrase = hedge_match.group(0)
    ctx = full_text[max(0, hedge_match.start()-80): hedge_match.end()+80]

    # 安全话题免检（个人话题永远不拦）
    if _is_safe_topic(ctx):
        return False, ""

    # ── ④ 判 ─────────────────────────────────────────────────
    if had_search:
        # 搜了 → 降 warn，说「没找到」是合法的
        _hook_log(f"搜了但说 hedged: '{hedge_phrase}' → warn only: {ctx[:100]}")
        return False, ""

    # 没搜却说猜 → block
    reason = (
        f"你说「{hedge_phrase}」但本轮没有任何搜索动作。\n"
        "Frank 2026-08-31：\"你能力那么逆天，可以调动那么多工具、可以上网搜索\"\n"
        "→ 先去查（WebSearch/Grep/Read/Bash/git），搜完再说「没找到」或者「搜了但不确定」。"
        " 不能没搜就用猜的。"
    )
    _hook_log(f"BLOCK: {reason[:200]}")
    state["this_turn_blocked"] = True
    _save_state(state)
    return True, reason


def _read_transcript(tp):
    """读 transcript jsonl，返回消息列表（和 authority-source-gate 同路）"""
    try:
        from pathlib import Path
        lines = Path(tp).read_text(encoding="utf-8").splitlines()
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    try:
        data = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"decision": "pass"}))
        return

    # 优先用 transcript_path（Stop hook 传入），否则直接用 messages 列表
    tp = data.get("transcript_path")
    # 2026-09-06 防无限 loop:本轮被 Stop 闸拽回次数到上限就让开。
    #   实测 55 道 Stop 闸只有 64% 受回合预算管,自己读 transcript 的 12 道全绕过,
    #   本闸就在那 12 道里(Frank:「触发了无限Loop的bug…think twice 然后阻塞」)。
    #   安全类闸在 _BUDGET_NEVER 里永不熔断;逃生阀 SUPEREGO_NO_BUDGET=1。
    try:
        from guard_common import turn_budget_ok as _tbo
        if tp and not _tbo(tp):
            return
    except Exception:
        pass
    if tp:
        messages = _read_transcript(tp)
    else:
        messages = data.get("messages", [])

    block, reason = _check(messages)

    if block:
        print(json.dumps({
            "decision": "block",
            "reason": reason
        }, ensure_ascii=False))
    else:
        print(json.dumps({"decision": "pass"}))


if __name__ == "__main__":
    main()
