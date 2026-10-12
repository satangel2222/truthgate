"""事实账本闸(Claude Code 版)—— 我说「测试通过 / 全绿 / N/N pass」,就去 transcript 里查本轮最后一条测试类命令的【真实退出码】。
非 0 = 拦,拦的话里直接引用那条命令和退出码。不看我的措辞对不对,只看工具结果。

⛔ 起因(2026-09-25,Frank 原话):「这套底层设计抓词的设计我觉得本来就不对,就算抓语义也不对」——
   下午的考卷量出来:闸在他之前说中的错 20/117,说中了也 0/20 拦住;根因是判官只看我说了什么。
   同晚先在 Antigravity 桥接里加了同一道(ledger-claim-gate),这是 Claude Code 端的对应实现。
判据:①最后一条回复宣称测试通过(LEDGER_CLAIM_RE)②本轮(最后一条真实用户输入之后)有 Bash 调用且命令匹配测试类
     (TEST_RE)③其中最后一条的结果 is_error 或文本里 Exit code 非 0 ⇒ 拦。②③任一不成立 ⇒ 放行(没跑测试就说过 = 交给 honest-scope 类闸)。
ponytail: 只认 Bash 工具;测试走别的工具、或命令名不含 test/pytest 之类 ⇒ 看不见,老实登记。
豁免:引用/复盘语境里复述那句话。
"""
import json
import os
import re
import sys

CLAIM = re.compile(r"(?:测试|回归|单测|自检|selftest|test)[^。\n]{0,20}?(?:全绿|通过|跑通|全过|都过|已过|绿了|pass(?:ed|es)?\b|green)"
                   r"|(?:\d+\s*/\s*\d+)\s*(?:通过|全过|绿|pass)"
                   r"|(?:all|全部)\s*(?:tests?|测试)\s*(?:pass|通过|绿)", re.I)
QUOTING = re.compile(r"(引用|复盘|实录|原话|复述|我(之前|刚才|两次)说|误报|这道闸|那道闸)")
TEST_RE = re.compile(r"(?i)\b(pytest|npm test|npm run test|node [^\n]*test|py(?:thon)?[^\n]*test_|selftest|--selftest|regression|vitest|jest|cargo test|go test)")
EXIT_RE = re.compile(r"(?i)exit code[:\s]*(\d+)")


def last_turn_bash_results(transcript_path):
    """返回本轮(最后一条真实用户输入之后)的 [(命令, is_error, 退出码或None)],按时间序。"""
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
        c = (r.get("message") or {}).get("content")
        txt = c if isinstance(c, str) else " ".join(b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text")
        if txt.strip() and not txt.lstrip().startswith(("Stop hook", "<command-", "[Request interrupted")):
            last_user = i
    calls, order = {}, []
    for r in rows[last_user + 1:]:
        if r.get("type") == "assistant":
            for b in (r.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash":
                    calls[b["id"]] = (b.get("input") or {}).get("command", "")
                    order.append(b["id"])
        elif r.get("type") == "user":
            for b in (r.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                    c = b.get("content")
                    txt = c if isinstance(c, str) else " ".join(x.get("text", "") for x in (c or []) if isinstance(x, dict))
                    m = EXIT_RE.search(txt[:300])
                    calls[b["tool_use_id"]] = (calls[b["tool_use_id"]], bool(b.get("is_error")), int(m.group(1)) if m else None)
    out = []
    for i in order:
        v = calls.get(i)
        if isinstance(v, tuple):
            out.append(v)
    return out


def check(last_text, results):
    """纯函数,给测试用。返回拦截文案或 None。"""
    if not last_text or not CLAIM.search(last_text) or QUOTING.search(last_text):
        return None
    tests = [t for t in results if TEST_RE.search(t[0] or "")]
    if not tests:
        return None
    cmd, is_err, code = tests[-1]
    if is_err or (code not in (None, 0)):
        return ("⛔ 事实账本闸:你说测试通过,但本轮最后一条测试命令的真实结果是红的:\n"
                "   · 命令: %s\n   · 退出码: %s%s\n"
                "⇒ 账本是从工具结果抄的,不看你的措辞。要么修到退出码 0 再说通过,要么如实写「测试红着」。"
                % (cmd[:90].replace("\n", " "), code if code is not None else "?", "(is_error)" if is_err else ""))
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
        vio = check(text, last_turn_bash_results(tp))
    except Exception:
        sys.exit(0)          # 闸自己坏了不许堵人
    if vio:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from guard_common import hook_log, turn_budget_ok
            if not turn_budget_ok(tp):   # 2026-09-27 PLAN 第 5 步:本轮已拦过一次 / 本轮拽回太多次 ⇒ 让开(turn_budget_ok 自己记账)
                sys.exit(0)
            hook_log("ledger-claim-gate", "BLOCK 说测试通过但账本退出码非 0", text[:80])
        except SystemExit:
            raise
        except Exception:
            pass
        print(vio, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
