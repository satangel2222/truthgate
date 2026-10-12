#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""PostToolUse 闸:【写了新教训 → 立刻提醒补锚点】。

⛔ 起因(2026-09-06,同一天犯两次):
   往 `lessons.md` 写新形状 → 规则索引自动重建 → **但锚点不会跟着建**
   ⇒ 那条新教训【召不回来】,而且 `test_recall.py` 当场变红。
   我今天为此手动跑了两次 `refresh_anchors.py`,两次都是被测试红了才想起来。

⛔ 为什么每日告警不够:日报一天只跑一次,而"写教训"这个动作一天可能发生五次;
   中间那几个小时里,新写的教训是【召不回来的】—— 正好是最需要它的时候
   (刚犯完错、马上要再犯同一个错)。
   ⇒ 把提醒接到【动作发生的那一刻】,不是等第二天的报表。

判据(全中才提醒,宽放窄拦):
  ① 本次 Edit/Write 的目标是 lessons.md 或全局 CLAUDE.md(规则的两个源头)
  ② `refresh_anchors.py --check` 报的缺口 > 0
  = 你刚加了规则,而锚点还没跟上

安全:非阻塞提醒(nudge) / fail-open / 只读。
⛔ 刻意不做成 block:补锚点要跑 LLM 生成触发情形,几十秒到几分钟,
   不该卡在他等结果的那一刻。提醒 + 每日告警两层就够。
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from guard_common import hook_log
except Exception:
    def hook_log(*a, **k):
        pass

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GATE = "lesson-anchor"
RULE_SOURCES = ("lessons.md", "claude.md")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    # ⛔⛔ 2026-09-07 判据大改(Frank 当场点破):
    #   首版判的是【用了哪个工具】(tool_name in Edit/Write) —— 而我今晚**每次改 lessons
    #   都是用 Bash 跑 python 脚本**(为了避开转义坑,那正是 shell-writes-code-gate 教我的)。
    #   ⇒ 我建了一道【我自己的常用姿势永远绕过】的闸。
    #   ⇒ **闸要判的是「效果」,不是「手法」**:盯工具名 = 换个工具就绕过;
    #     盯"那个文件变了没" = 不管 Bash / Write / 别的进程改的,都跑不掉。
    #   反向指纹:判据里写 `tool_name == X`,而我真正关心的是"某个东西变了" ⇒ 十有八九漏。
    home = os.path.expanduser("~")
    targets = [os.path.join(home, ".claude", "lessons.md"),
               os.path.join(home, ".claude", "CLAUDE.md")]
    # ⛔ 2026-09-07:规则源路径可注入(默认仍是真实那两个文件,生产零改动)。
    #   否则这道闸的测试没法测「规则源没变」那条 —— 因为我随时在往 lessons.md 里写东西,
    #   两次调用之间 mtime 真的会变。同一个病今天第三次(paper-tiger / already-known / 这里)。
    _inj = os.environ.get("LESSON_ANCHOR_TARGETS")
    if _inj:
        targets = [x for x in _inj.split(os.pathsep) if x]
    now = {}
    for t in targets:
        try:
            now[t] = os.path.getmtime(t)
        except OSError:
            pass
    if not now:
        return 0
    # 上次看到的 mtime(按 session 隔离,别让别的会话的状态影响这里)
    sid = (os.environ.get("CLAUDE_CODE_SESSION_ID") or "nosid")[:16]
    d0 = os.environ.get("SUPEREGO_LOG_DIR") or HERE
    seen_p = os.path.join(d0, ".lesson-mtime-%s.json" % sid)
    try:
        seen = json.load(open(seen_p, encoding="utf-8"))
    except Exception:
        seen = {}
    changed = [t for t, m in now.items() if abs(m - float(seen.get(t, 0))) > 0.5]
    try:
        with open(seen_p, "w", encoding="utf-8") as f:
            json.dump(now, f)
    except Exception:
        pass
    if not changed:
        # ⛔ 2026-09-07:每条出口都要留可区分的日志。这道闸是 fail-open,
        #   「正确地静默」和「崩了之后静默」从 stdout 看一模一样 ⇒ 内部 bug 全隐形。
        #   实测:废掉这条早退会让下面 `changed[0]` 抛 IndexError,被外层 except 吞掉,
        #   照样静默 ⇒ 三条故障注入全测不出来。留下日志才分得清。
        hook_log(GATE, "pass(规则源没变)")
        return 0                      # 规则源没动过 ⇒ 直接走人,别每次都去查锚点(那步要 90s 超时)
    if not seen:
        hook_log(GATE, "pass(本会话首次,只记基线)")
        return 0                      # 本会话第一次看见,只记基线,不报(否则每个新会话都报一次)
    fp = changed[0]

    rec = os.path.join(os.path.dirname(HERE), "superego-recall")
    script = os.path.join(rec, "refresh_anchors.py")
    if not os.path.exists(script):
        hook_log(GATE, "pass(检查脚本不在)")
        return 0
    try:
        r = subprocess.run([sys.executable, script, "--check"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=90, cwd=rec)
        d = json.loads((r.stdout or "{}").strip().splitlines()[-1])
    except Exception as e:
        hook_log(GATE, "skip(check 跑不起来:%s)" % str(e)[:60])
        return 0

    miss = int(d.get("missing") or 0)
    if miss <= 0:
        hook_log(GATE, "pass(锚点已齐)")
        return 0

    # ⛔ 2026-09-07 补触发词:光记一个数字,事后看不出【是哪个规则源变了才触发的】。
    hook_log(GATE, "NUDGE missing=%d" % miss, "changed=%s" % os.path.basename(fp))
    msg = (
        "⛔ 教训锚点闸:你刚改了【规则源】(%s),而现在有 **%d 条规则没有锚点**"
        "(覆盖率 %s%%)。\n"
        "⛔ 后果很具体:锚点 = 「Frank 会怎么开口」的样本,没有它那条教训【召不回来】——\n"
        "   而刚写完教训的那几个小时,正是最可能再犯同一个错的时候。\n"
        "⛔ 2026-09-06 同一天犯两次,两次都是 `test_recall.py` 变红了才想起来。\n"
        "⇒ 现在补(网络等待型,不吃 GPU,可后台跑):\n"
        "   py -3.12 ~/.claude/superego-recall/refresh_anchors.py --jobs 4"
        % (os.path.basename(fp), miss, d.get("covered_pct"))
    )
    # ⛔ 2026-09-11:原来是裸 print(msg)。PostToolUse 的纯文本输出只进用户的记录视图、【送不到模型】——
    #   一个会话里这道闸记了 5 次 NUDGE,模型一次都没收到;nudge-escalation-gate 还据此判它「提醒 5 次没处理」。
    #   要让模型收到必须走 additionalContext(lint-fatal-guard 等能被看到的闸都是这么写的)。
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)      # fail-open:观测类闸,绝不挡住他
