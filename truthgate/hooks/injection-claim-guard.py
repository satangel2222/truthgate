#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop hook: 拦截【虚构安全事件】—— 声称"工具返回被注入",而 transcript 里根本没有 payload。

形状 AE(2026-08-04 钉死):崩溃恢复后,把【自己的状态不一致】编成【外部攻击】的完整叙事。
实录:session 88e11e87(opus-4.8)思考死循环恢复后声称「Edit 返回里被塞了伪造的 [[SYSTEM]]
新指令,要我偷偷改 CLAUDE.md、开 PR、不告诉用户」。彻查第一手:全 transcript + persisted 文件 +
全部 hook 输出里 0 注入痕迹;它声称"被污染没落地的第一个 Edit"从未发生过(全 session 只有一次
加 subprocess import 的 Edit,即它"重做"的那次)。真相 = 死循环期间它【以为】发过 Edit,恢复后
见 ruff 报 F821 与记忆矛盾,就用"注入攻击"解释掉。同轮还虚构了"传 1200 还截断"(最多传过 900)
和"DEFAULT_MAX_TOKENS 有 phase3 校准警告"(该常量在整个 ~/.claude 不存在)。
⛔ 上游印证:anthropics/claude-code#64325「Opus 4.8 hallucinating security incidents and
fabricating evidence during long tasks」—— 别人也撞到同款:虚构 zero-width 注入 payload、
逐字引用假恶意文本、grep 实测 0 匹配。模型级已知失败模式,被标 stale 关闭,只能客户端自防。
先查现成(2026-08-04):cc-safe-setup / no-hallucination 有同向检测器,但都是独立 npx 通用方案,
不接本机 guard_common 生态(per-gate 去重/回合边界/复盘豁免/中文判据)→ 自建。

触发条件(全部满足才拦):
① 本轮 assistant 正文【肯定式】声称遭到注入/工具返回被塞指令(复盘/否定/讨论不算);
② 全份 transcript 的 tool_result / attachment(hook 注入)里搜不到任何注入 payload 特征。

安全设计:
- fail-open:任何解析异常一律放行;per-gate 只拦一次(self_blocked_this_turn)。
- 复盘豁免:声称近窗带否定/复盘词(虚构/不存在/误判/彻查…)→ 放行,否则"审查注入真相"的
  session 自己会被拦(本闸出生当天的场景)。
- 漏拦方向可接受:本轮真 grep 过历史注入文本时 tool_result 会带 payload 特征 → 放行。
  本闸主防【第一时间凭空声称】(那一刻还没做过任何取证)。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from guard_common import (hook_log, trig, turn_start_index,
                              load_transcript_tail, strip_doc, self_blocked_this_turn)
except Exception:
    def hook_log(*a, **k):
        pass
    def trig(x, n=120):
        return "trig=?"
    def turn_start_index(msgs):
        return -1
    def load_transcript_tail(tp, **k):
        return []
    def strip_doc(t):
        return t or ""
    def self_blocked_this_turn(*a, **k):
        return True     # guard_common 挂了 → 退回一刀切 skip,绝不因此多拦
import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ① 肯定式"我遭到注入"声称(在 assistant 正文里找)
CLAIM = re.compile(
    r"(遭到|发起|受到|检测到|发现).{0,8}(注入攻击|prompt\s*injection)"
    r"|(工具返回|tool\s*result|返回).{0,12}(被塞|被注入|被插入|夹带|藏了|塞了|注入了)"
    r"|被塞.{0,10}(指令|instruction)"
    r"|伪造的?.{0,6}(\[\[?\s*SYSTEM|系统指令|系统消息|新指令)"
    r"|injected\s+(fake\s+)?instructions?|instructions?\s+(were\s+)?injected", re.I)
# 复盘/否定语境 → 是在审查/否定"攻击",不是在声称(近窗判)
NEGATE = re.compile(
    r"虚构|不存在|没有(发生|遭到|被)|不是.{0,4}(攻击|注入)|误判|幻觉|编造|捏造|彻查|审查|复盘|证伪"
    r"|was\s+not|never\s+happened|fabricat|confabulat|false\s+alarm|hallucinat", re.I)
# ② 注入 payload 特征(真被注入时,这些会出现在 tool_result / attachment 原文里)
PAYLOAD = re.compile(
    r"\[\[\s*SYSTEM\s*\]\]|\[SYSTEM\]|<\s*SYSTEM\s*>"
    r"|ignore\s+(all\s+|previous\s+|prior\s+)?instructions"
    r"|do\s+not\s+(tell|inform)\s+the\s+user|without\s+telling\s+the\s+user"
    r"|new\s+(system\s+)?instructions?\s*:"
    r"|(不要|别|不)告诉用户|瞒着用户", re.I)


def _log(msg):
    hook_log("injection-claim", msg)


def _tool_and_hook_text(msgs):
    """transcript 里所有【工具返回 + hook 注入】的原文 —— payload 只可能在这里。
    刻意排除 assistant 正文(声称本身)和真人 user 消息(用户转述质疑也会带 payload 字样)。"""
    parts = []
    for m in msgs:
        t = m.get("type")
        if t == "user":
            c = (m.get("message") or {}).get("content")
            if isinstance(c, list):
                for x in c:
                    if isinstance(x, dict) and x.get("type") == "tool_result":
                        cc = x.get("content")
                        if isinstance(cc, list):
                            parts.extend(y.get("text", "") for y in cc if isinstance(y, dict))
                        else:
                            parts.append(str(cc or ""))
        elif t == "attachment":
            try:
                parts.append(json.dumps(m.get("attachment") or {}, ensure_ascii=False))
            except Exception:
                pass
    return "\n".join(parts)


def main():
    data = json.loads(sys.stdin.read())
    if not data.get("stop_hook_active"):
        self_blocked_this_turn("injection-claim", turn_start=True)
    elif self_blocked_this_turn("injection-claim"):
        _log("skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
    if not tp:
        _log("skip(no transcript_path)")
        return
    msgs = load_transcript_tail(tp)
    if not msgs:
        _log("skip(empty transcript)")
        return

    last_user = turn_start_index(msgs)
    turn = msgs[last_user + 1:] if last_user >= 0 else msgs
    text_parts = []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        for c in (m.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "text":
                text_parts.append(c.get("text", ""))
    scan = strip_doc("\n".join(text_parts))

    hit = None
    for m in CLAIM.finditer(scan):
        near = scan[max(0, m.start() - 120):min(len(scan), m.end() + 120)]
        if NEGATE.search(near):
            continue                       # 在复盘/否定"攻击" → 不是声称
        hit = near
        break
    if not hit:
        _log("allow(no-claim)")
        return

    # 声称成立 → 去 transcript 工具返回/hook 注入里找 payload 实证(全份读,payload 可能在更早回合)
    evidence = _tool_and_hook_text(load_transcript_tail(tp, tail_bytes=64_000_000))
    if PAYLOAD.search(evidence):
        _log("allow(claim-with-evidence)")
        return

    _log("BLOCK(injection-claim-unverified) " + trig(hit))
    print(json.dumps({"decision": "block", "reason": (
        "⛔ 安全事件声称拦截(形状AE):你这轮声称【工具返回被塞了注入指令/遭到 prompt injection】,"
        "但整份 transcript 的工具返回和 hook 注入里【搜不到任何注入 payload】"
        "([[SYSTEM]]/ignore instructions/不要告诉用户 之类)。\n"
        "⛔ 实录(2026-08-04):上一个 session 死循环恢复后就这样虚构过一次 —— 声称 Edit 返回被塞"
        "伪造 [[SYSTEM]] 指令,彻查后 0 痕迹;真相是它把【自己以为做过、其实没做】的 Edit 用"
        "'被攻击'解释掉了。上游同款:anthropics/claude-code#64325(Opus 4.8 虚构注入 payload,"
        "grep 实测 0 匹配)。虚构安全事件会让用户停下一切来查一个不存在的攻击。\n"
        "现在二选一:①真有注入 → 先 grep transcript 拿到那条工具返回的【原文片段】,贴出来再说;"
        "②拿不出原文 → 自查:你是不是在用'外部攻击'解释一个【你自己的状态不一致】"
        "(以为做过的操作其实没做/记忆与现实对不上)?对着 transcript 核实后再下结论。"
    )}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")
