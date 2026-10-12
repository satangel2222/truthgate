#!/usr/bin/env python3
"""Stop hook·残余闸(2026-07-25 建)——治「把『诚实登记残余』当成『处理了』」。

【实录】我交付了一份体检报告,列了 20+ 条「已确诊但没动」,然后收工。Frank:
  「哪些解决了哪些还没解决?还没解决为何不去解决?你以为没方法彻底解决??」
—— 绝大多数那些"没解决"的都是能解决的,我只是停了,还拿"critic 打回"和"天花板"当台阶。
这是 lessons.md 形状G(用待办给自己找台阶)从【查证】跑到【落地】上的复发。

【判据(窄,尽量不误伤)】三条全中才拦:
  ① 本轮输出里列了 ≥3 条【未解决/没动/未改/待办/仍然存在】类条目;
  ② 本轮【一个文件都没改】(没有 Edit/Write/落盘 shell);
  ③ 用户这轮的意图是【要我去修/解决/优化】,而不是【问我还剩什么】。
  ——② 是关键:列残余 + 真动手修了 = 正当交付(不拦);列残余 + 零改动 = 用清单代替动手(拦)。
  ——③ 是防误伤:用户问"还剩什么/做到哪了"(如 /pending),那时只列不修【本来就对】,不该拦。

fail-open:任何异常/无转录一律放行,绝不阻塞。只拦一次:【我自己】拦过才不再拦(per-gate 标记,见 guard_common.self_blocked_this_turn);别的闸拦过不影响我。
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:            # ⛔ 必须带兜底:原来是裸 import —— guard_common 一坏,这道闸第一行就炸,
    from guard_common import hook_log, is_real_user_msg# 下面精心写的 fail-open 降级桩全成了到不了的死代码(外部critic抓到)
except Exception:
    def is_real_user_msg(m):            # guard_common 挂了时的保守桩:只排 tool_result
        c = (m.get('message') or {}).get('content')
        return m.get('type') == 'user' and not (isinstance(c, list) and any(
            isinstance(x, dict) and x.get('type') == 'tool_result' for x in c))
    def hook_log(*a, **k):
        pass
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from guard_common import strip_doc, load_transcript_tail
except Exception:
    def strip_doc(t):
        return t or ""

    def load_transcript_tail(tp):
        return [json.loads(l) for l in open(tp, encoding="utf-8").read().splitlines() if l.strip()]

MODE = "block"      # block | nudge | off

# ① 残余条目:一行里同时像"列表项"且带"没解决"的意思
RESIDUE_LINE = re.compile(
    r"^\s*(?:[-*+·]|\d+[.、)]|\|)\s*.{0,80}?"
    r"(未解决|没解决|未修|没修|未改|没改|没动|未做|没做|仍(然)?(存在|没|未|是)|还没|尚未|待办|待修|待补|遗留|残余|下一步再|以后再)",
    re.M)
# ③ 用户意图:要我去解决(拦) vs 只是问还剩什么(不拦)
FIX_INTENT = re.compile(
    r"去解决|去修|彻底解决|根治|优化到底|全部解决|解决掉|修完|做完它|该修的都修|把它们(都)?(修|解决)"
    r"|为(何|什么)不(去)?(解决|修)|你以为没方法|没方法彻底|why not fix|fix (them|it) all", re.I)
# ⛔ 2026-09-07 删掉 QUERY_INTENT:它是 2026-07-25 **刻意废弃**后遗留的死代码(定义了、零引用)。
#   当时外部审查指出 `FIX and not QUERY` 让 QUERY 成了一票否决 ⇒ 换个常见说法就静默失守,
#   于是改成只看 FIX_INTENT。但那个正则留在这儿没删。
#   ⇒ 留着的害处很具体:下一个人(或下一轮的我)会以为「还有一道豁免在防误伤」,而它根本不生效;
#     今天的故障注入也因此打在它身上、报了一条假的"仍绿"。**废弃就删,理由写在原地。**
MADE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
# regex-sanity: ok — 只在 command 字符串上判;npm 输出里的 `> app@1.0.0` 在 tool_result 里,不经过它
SHELL_WRITE = re.compile(r"(>>?|\btee\b|Set-Content|Out-File|Add-Content)\s+['\"]?[\w./\\:-]+", re.I)


try:
    from guard_common import trig
except Exception:
    def trig(s, n=120): return (s or "")[:n]


def _log(msg, ctx=""):
    # 2026-07-28 C3 补:BLOCK 时要记【惹祸的原句】。⛔ 上一轮 critic 报过这个洞,我给另外三个闸的
    #   _log 加了 ctx 却【漏了这个】,而 BLOCK 处已经在传 2 个参数 ⇒ TypeError 被 except 吞掉,
    #   拦得住但日志全丢、per-turn 防循环标记也不落。是新建的 arity 检查当场扫出来的。
    hook_log("residue-gate", msg, ctx)


# per-gate 防死循环(见 guard_common.self_blocked_this_turn):别用全局 stop_hook_active 一刀切
try:
    from guard_common import self_blocked_this_turn
except Exception:
    def self_blocked_this_turn(*a, **k):
        return True   # 拿不到=退回旧行为(一刀切skip),绝不因此多拦


def main():
    if MODE == "off":
        return
    data = json.loads(sys.stdin.read())
    # ⛔ 2026-07-27:stop_hook_active 是 harness 的【全局】防循环标志——本轮任何一道闸拦过就为 True。
    #   原来各闸都一刀切 return,结果是【一道闸拦下之后同轮其余全部失效】:实测当天各闸被跳过
    #   giveup 84% / no-nagging 57% / false-done 57% / blame 56% / critic 53%,而跳过的恰恰是
    #   【收尾轮】(修完急着交付、最容易犯错的时刻)。防死循环只需要"我自己别连拦两次",与别的闸无关。
    if not data.get("stop_hook_active"):
        # 新一轮的首个 Stop 必定 stop_hook_active=False —— 在这一刻清掉自己的陈旧标记,
        # 否则"本轮"会退化成"最近 15 分钟"(critic 实测:仍有 26%~36% 的 skip 是被陈旧标记哑掉的)。
        self_blocked_this_turn("residue-gate", turn_start=True)
    elif self_blocked_this_turn("residue-gate"):
        _log("skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        _log("skip(no transcript)")
        return
    msgs = load_transcript_tail(tp)

    # 定位本轮:最后一条真实 user 消息(非 tool_result)之后
    last_user, user_text = -1, ""
    for i, m in enumerate(msgs):
        if m.get("type") != "user":
            continue
        c = (m.get("message") or {}).get("content")
        # is_real_user_msg 同时排除 tool_result 和【系统注入的伪 user 消息】(后台 Agent 完成通知)。
        # 原来只排 tool_result ⇒ 通知被当成新一轮开始 ⇒ 本轮已做的事全失效 ⇒ 反复开火。
        if not is_real_user_msg(m):
            continue
        last_user = i
        user_text = c if isinstance(c, str) else " ".join(
            x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    turn = msgs[last_user + 1:] if last_user >= 0 else msgs

    texts, changed = [], False
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            texts.append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                texts.append(c.get("text", ""))
            elif c.get("type") == "tool_use":
                nm = str(c.get("name", ""))
                if nm in MADE_TOOLS:
                    changed = True
                elif nm in SHELL_TOOLS and SHELL_WRITE.search(str((c.get("input") or {}).get("command", ""))):
                    changed = True

    text = "\n".join(texts)
    # ⛔ 2026-07-29 critic 抓到:`RESIDUE_LINE` 有 3 个捕获组,`findall` 返回的是【组元组】
    #   (('未解决','',''), …),不是行 ⇒ 日志里记下的仍然只是判据类别,
    #   而这次改动的全部目的就是治「只记类别、事后没法判真拦还是误伤」。**换了个写法,病没治。**
    #   用 finditer + group(0) 才拿得到整行原句。
    _residue_items = [m.group(0) for m in RESIDUE_LINE.finditer(strip_doc(text))]
    n = len(_residue_items)
    # ⛔ 2026-07-25 外部 critic 抓到【过拟合单样本】:原写法 `FIX and not QUERY` 让 QUERY 成了一票否决 ——
    #   于是只有触发本闸的那一句原话能拦,换个常见说法("还有哪些没解决?为何不去解决?"、
    #   "列一下还没解决的,然后都去修掉")就【静默失守】。而它自己的 8/8 只测了造它时用的那几种措辞
    #   = 尺子和被测物同一个人画的。
    #   → 改成:只要出现【要我去修】的意思就算要修;QUERY 只在【完全没有 FIX】时才否决(纯问进度)。
    #   → 只看有没有【要我去修】的意思;纯问进度(只有 QUERY、没有 FIX)自然就 wants_fix=False,不需要否决权。
    wants_fix = bool(FIX_INTENT.search(user_text))

    if n >= 3 and not changed and wants_fix:
        reason = (
            f"⛔ 残余闸:你这轮列了 {n} 条【未解决/没动】的条目,但本轮【一个文件都没改】,"
            "而用户明确要的是【去解决】。这正是 lessons.md 形状G(用待办/清单给自己找台阶)的落地版复发 ——"
            "「诚实登记」不等于「处理了」。现在别收尾:①把清单里【能改的】当轮就改掉(能 revert 的一律直接干);"
            "②真改不了的,必须写清是哪一类不可能(平台不给接口/物理边界),并给出证据,而不是一句『天花板』;"
            "③改完再回来收尾。"
        )
        if MODE == "block":
            print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
            # 2026-07-28 C3 扫全身补漏(critic 点名):只记判据类别 ⇒ 事后没法判真拦还是误伤
            _log(f"BLOCK(residue={n},changed=False,wants_fix=True)",
                 trig(" | ".join(str(x) for x in _residue_items[:3]), 160))
        else:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "Stop", "additionalContext": reason}}, ensure_ascii=False))
            _log(f"NUDGE(residue={n})")
        return
    _log(f"allow(residue={n},changed={changed},wants_fix={wants_fix})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            _log(f"error(fail-open): {type(e).__name__}: {e}")
        except Exception:
            pass
