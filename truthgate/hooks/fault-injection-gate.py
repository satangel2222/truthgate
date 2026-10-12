#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""故障注入闸 —— 我这轮【写/改了测试】,就必须证明那把尺子【真的会红】,否则它可能是摆设。

⛔ 为什么要它(2026-08-07,Frank 一句话问出来的):
   他问「尺子坏了是指 superego 的尺子吗？不用修正吗？」——他其实在问:
   **既然你两天坏了 10 把尺子,为什么没有一道闸管这个?**
   查了:20+ 道闸里**一道都没有**。我一直靠"写完测试要故障注入"这个【自觉习惯】,
   而它只写在 lessons(形状 U-3)= 软提醒。事实:
     · 这两天同一形状犯了 **10 次**
     · 其中「把被测代码注释掉、测试照样全绿」这一种犯了 **2 次**(toast 那条 / return 那条)
   靠自觉显然不管用 ⇒ 上机器。

⭐ 先查现成(2026-08-07 实做:gh search + WebSearch):
   这件事业界叫 **mutation testing(变异测试)**,而且**正是标准做法**:
     · CI 里配【两道闸】—— ①测试必须通过 ②测试必须"有意义"(变异分数低于阈值就让构建失败)
     · 工具:JS/TS → **StrykerJS**;Python → **mutmut**;Java → PIT;PHP → Infection
     · 成熟实践:**diff-mode(只变异改动过的文件)** —— 正好对应我的场景(只验这轮改的东西)
   ⇒ 结论 = **改造复用 + 强制层自建**:
     · 想【彻底】验一整个套件的质量 → 直接上 Stryker / mutmut,别手写变异器;
     · 但那些工具全跑在 **CI 流水线**上,**没有一个会在「我写完测试、跑绿、正要收尾」
       那一刻拦住我** —— 那是 Superego 特有的位置,所以这道闸自建,并在提示里指回那些工具。

判据(全中才拦;只看客观事实、零文本猜测 ⇒ 零假阳性,思路照 evidence-gate):
  ①本轮 Edit/Write 命中了【测试文件】(test_*.py / *.test.js / *_test.py / *.spec.js …)
  ②本轮所有工具结果里,**从头到尾没出现过一次「测试红了」的真实输出**
     (`✖ failing tests` / `ℹ fail N(N>0)` / `AssertionError` / pytest FAILED / `exit=非0` …)
  = 写完测试只跑到绿就想收工 ⇒ 没做过故障注入 ⇒ 这把尺子会不会响是未知的。

⚠️ 刻意的设计取舍:
  · **「一次红都没见过」就是判据本身** —— 故障注入要求主动把 bug 放回去让它红。
    没见过红 = 没做。这不是误伤,是这道闸的全部意义。
  · 只认【测试框架/进程的真实输出】,不认我嘴上说的"已注入/已抓到"(那种太好伪造)。
  · fail-open:任何异常一律放行;全程只读;留日志;per-gate 防死循环(同轮不连拦两次)。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import hook_log, load_transcript_tail, turn_start_index, self_blocked_this_turn
except Exception:                                    # guard_common 坏了也不能让这道闸变成炸弹
    def hook_log(*a, **k):
        pass

    def load_transcript_tail(*a, **k):
        return []

    def turn_start_index(msgs):
        return -1

    def self_blocked_this_turn(*a, **k):
        return True                                  # 拿不到防循环能力 → 宁可不拦

TEST_FILE_RE = re.compile(
    r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.test\.(js|mjs|cjs|ts|tsx)|[^/]+\.spec\.(js|ts|tsx))$", re.I)
MADE_TOOLS = {"Write", "Edit", "MultiEdit"}

# 「我见过红」—— 只认测试框架/进程的真实输出,不认自然语言
RED_PATTERNS = [
    re.compile(r"failing tests"),                     # node --test 的 "✖ failing tests"
    re.compile(r"^\W*fail\s+[1-9]", re.M | re.I),     # node --test 汇总 "ℹ fail 3"
    re.compile(r"AssertionError"),                    # node assert / pytest
    re.compile(r"^\s*(FAILED|ERROR)\b", re.M),        # pytest
    # 本项目自写的中文 runner。⛔ 不能加 `^`:真实输出是「16/19 通过   3 条失败」——
    #   "3 条失败" 不在行首,加了 ^ 就永远匹配不上(这道闸自己的回归当场抓到)。
    #   也必须要求【非零】,否则「0 条失败」会被当成见过红 ⇒ 全绿也放行 = 闸失效。
    re.compile(r"[1-9]\d*\s*条?失败"),
    re.compile(r"\bexit=\s*[1-9]"),                   # 我惯用的 `echo "exit=$?"`
    re.compile(r"\bFAIL\b"),                          # 自写 runner 的 FAIL 行
    # ⛔⛔ 2026-08-26 补的自伤缺口:**这道闸认不出【本机故障注入跑器】自己的输出**。
    #   `~/.claude/skills/fault-injection/scripts/fault-inject.js` 打的是中文:
    #       ✅ 变红       空壳判据整体失效(...)
    #       ✅ 6/6 达标:每个 bug 放回去都真的被测出来
    #   上面那张表全是英文测试框架的字样(FAILED/ERROR/AssertionError/FAIL),一个都对不上
    #   ⇒ 我【正确地做完了】故障注入,它照样拦我。当天连拦两次,每次都是在我刚跑完 6/6 达标之后。
    #   ⇒ 这是最坏的一种闸:**惩罚正确行为**。误伤多了我必然开始想办法绕过它,那它就彻底废了。
    # ⛔ 判据必须窄到【只有真跑过那个跑器才会出现】,不能只认"达标"两个字
    #   (否则我随口打一行字就免检)。"变红" 后面必须跟空白+内容 = 跑器逐条报告的固定形状。
    re.compile(r"变红\s+\S"),                          # fault-inject.js:某条注入真的把测试打红了
    re.compile(r"[1-9]\d*/[1-9]\d*\s*达标"),           # fault-inject.js 的汇总行(要求非零)
]


def scan(turn):
    """返回 (本轮改过的测试文件列表, 是否见过红)。只读 transcript,不碰磁盘。"""
    changed, saw_red = [], False
    for m in turn:
        content = (m.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and str(c.get("name")) in MADE_TOOLS:
                fp = str((c.get("input") or {}).get("file_path", "")).replace("\\", "/")
                if fp and TEST_FILE_RE.search(fp) and fp not in changed:
                    changed.append(fp)
            elif c.get("type") == "tool_result" and not saw_red:
                body = c.get("content")
                text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
                if text and any(rx.search(text) for rx in RED_PATTERNS):
                    saw_red = True
    return changed, saw_red


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        # 防死循环:新一轮首个 Stop 清标记;同轮我已拦过就不再拦(照 guard_common 的约定)
        if not data.get("stop_hook_active"):
            self_blocked_this_turn("fault-injection-gate", turn_start=True)
        elif self_blocked_this_turn("fault-injection-gate"):
            return 0

        msgs = load_transcript_tail(data.get("transcript_path")) or []
        if not msgs:
            return 0
        last = turn_start_index(msgs)
        turn = msgs[last + 1:] if last >= 0 else msgs
        changed, saw_red = scan(turn)
        if not changed or saw_red:
            return 0

        names = [os.path.basename(p) for p in changed[:4]]
        # ⛔ 2026-09-07:触发词挪到第三个参数 —— 拼进消息里记分板解析不到 ⇒ 记成"无证据"。
        hook_log("fault-injection-gate", "BLOCK(test-changed-never-saw-red)", ",".join(names))
        print(json.dumps({
            "decision": "block",
            "reason": (
                "⛔ 故障注入闸:你这轮写/改了测试(" + ", ".join(names) + "),"
                "但本轮**从头到尾没出现过一次「测试红了」的真实输出** ⇒ 没做过故障注入 ⇒ "
                "这把尺子会不会响、是不是摆设,现在是未知的。\n"
                "⛔ 这不是理论风险:2026-08-05~07 两天坏了 **10 把尺子**,其中"
                "「把被测代码注释掉、测试照样全绿」这一种犯了 **2 次**(toast 那条、return 那条)"
                "——每一把都是靠故障注入才暴露的,**只跑绿的永远发现不了**。\n"
                "现在补上再收尾:\n"
                "  ① 把你刚修好的 bug **逐个放回去**(改【被测文件】,不是改测试)\n"
                "  ② 每放回一个跑一次测试,要求**它真的变红**\n"
                "  ③ 没红的那条 = 摆设,当场重写断言"
                "(最常见的病:搜字符串而不管它是不是被注释掉了、是不是真的在生效路径上)\n"
                "  ④ 全部验完把被测文件**还原**,复跑确认回到全绿\n"
                "💡 要【彻底】验一整个套件的质量,别手写变异器——业界现成的:\n"
                "   JS/TS → StrykerJS(stryker-mutator) · Python → mutmut(boxed/mutmut)\n"
                "   标准做法是 CI 配两道闸(①测试要过 ②变异分数要达标),并用 diff-mode 只验改动过的文件。\n"
                "(若这轮只改了测试的注释/措辞、没动任何断言,说明一句即可放行。)"
            ),
        }, ensure_ascii=False))
        return 0
    except Exception as e:                            # fail-open,但绝不静默
        try:
            hook_log("fault-injection-gate", "error(fail-open): %s" % str(e)[:120])
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    main()
