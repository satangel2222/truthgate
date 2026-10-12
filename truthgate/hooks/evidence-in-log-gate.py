#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""PostToolUse 闸:【新写/改的闸,开火时必须留触发词】。

⛔ 起因(2026-09-07,记分板自己指认出来的):
   我今天新建的 `capability-boundary-gate` —— 记分板报它
   「同一指纹 180/180 次(复发率 100%)、**无证据率 100%**、跨 3 个项目」,
   按记分板自己的判据它是头号误伤嫌疑。
   查下去真因不是误伤,是**我建它时 `hook_log(SELF, "BLOCK(...)")` 后面没传触发词**:
   · 指纹拿空串算 ⇒ 每次都一样 ⇒ 100% 复发率是【假的】;
   · 100% 无证据是【真的】—— **事后没人能判断它拦得对不对**。

⛔ 而这正是记分板建起来要治的那件事,我自己新建的闸却当场就犯 ⇒
   **说明"建闸要留证据"这条靠我记得是不行的,必须有机器兜底。**
   记分板同日实测:还有 **10 道闸 100% 无证据**。

判据(全中才提醒,宽放窄拦):
  ① 本次改动碰了 `~/.claude/hooks/` 下的闸源码(不管用什么工具改的 —— 判效果不判手法)
  ② 那份源码里存在 `hook_log(..., "BLOCK/NUDGE/DENY...")` 这样的调用
  ③ 而该调用**只有两个参数**(没传第三个 ctx/触发词)
  = 这道闸开火时不会留下"因为哪句话",事后无法审计

安全:非阻塞提醒(nudge) / fail-open / 只读。
⛔ 刻意不做成 block:有些闸的触发词确实涉及隐私或本来就没有可引的文本,
   宁可提醒一句,别锁死他的活。
"""
import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from guard_common import hook_log, recently_changed
except Exception:
    def hook_log(*a, **k):
        pass

    def recently_changed(*a, **k):
        return []

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GATE = "evidence-in-log"
FIRE_WORD = re.compile(r"^(?:⛔\s*)?(?:BLOCK|NUDGE|DENY)", re.I)


def offenders(path):
    """返回【开火却不会在日志里留下 trig='...' 】的 hook_log 调用。

    ⛔ 判据盯的是【日志行里最后有没有 trig='...'】,不是"有没有第三个参数"。
       记分板认的就是这个字段(`TRIG = re.compile(r"trig='([^']{0,80})")`)。
       所以把触发词写进消息里也算数 —— 实录:
         hook_log("guard-destructive", f"BLOCK(...) {trig(command, 110)}")
       只有两个参数,却照样留下证据。

    ⛔ 用 ast 真解析,不用正则(2026-09-07 两次踩坑):
       ① 第一版按"两个参数"判 ⇒ 误报 5 道本来合格的闸;
       ② 第二版加了 `trig( not in` 之后仍误报 —— 因为正则跨不过嵌套括号:
          `hook_log(N, "..." % (os.path.basename(fp), n), ctx)` 里的 `)` 让它提前收尾,
          于是**三参数的调用也被当成两参数**。
       正则每补一个特例就长出一个新盲区;ast 直接给出真实参数个数,判据反而更短。
       误报的代价很具体:这是提醒类闸,噪音一多我就开始无视它 —— 它自己先变成纸老虎。
    """
    # ⛔ 2026-09-07:**不再豁免本文件**。那条豁免是正则版才需要的(说明文字里的反面例子会被匹配),
    #   而 ast 只看真实的 Call 节点,文档字符串里的例子根本进不来。
    #   留着它的代价当场兑现:记分板报 `evidence-in-log` 自己 **40 次开火 100% 无证据** ——
    #   我建的这道闸自己就犯了它要治的病,而正是那条自我豁免让我看不见。
    #   **给自己开的例外,恰好是最容易藏病的地方。**
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
        tree = ast.parse(src)
    except Exception:
        return []          # 语法错另有 lint-fatal 管,这里不越权
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "hook_log"):
            continue
        if len(node.args) >= 3 or any(k.arg == "ctx" for k in node.keywords):
            continue                                   # 有第三个参数 ⇒ 会写 trig='...'
        if len(node.args) < 2:
            continue
        try:
            seg = ast.get_source_segment(src, node) or ""
        except Exception:
            seg = ""
        if "trig(" in seg:
            continue                                   # 触发词写在消息里,同样留得下证据
        msg = node.args[1]
        lit = msg.value if isinstance(msg, ast.Constant) and isinstance(msg.value, str) else None
        if lit is None and isinstance(msg, ast.JoinedStr):     # f-string:取开头那段常量
            first = msg.values[0] if msg.values else None
            lit = first.value if isinstance(first, ast.Constant) else None
        if lit is None and isinstance(msg, ast.BinOp):         # "..." % (...)
            left = msg.left
            lit = left.value if isinstance(left, ast.Constant) and isinstance(left.value, str) else None
        if lit and FIRE_WORD.match(lit):
            out.append(" ".join(seg.split())[:90] or lit[:90])
    return out


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tn = data.get("tool_name")

    # ⛔ 判效果不判手法(形状 2026-09-07-C):不管用 Edit/Write 还是 Bash 跑脚本改的,都要看得见
    targets = []
    fp = str((data.get("tool_input") or {}).get("file_path") or "")
    if tn in ("Edit", "Write", "NotebookEdit") and fp:
        targets = [fp]
    elif tn in ("Bash", "PowerShell", "Task", "Agent"):
        targets = recently_changed(within=90, exts=(".py",), limit=6)
    if not targets:
        return 0

    hooks_dir = os.path.normcase(HERE)
    hits = []
    for t in targets:
        try:
            if os.path.normcase(os.path.dirname(os.path.abspath(t))) != hooks_dir:
                continue                      # 只管闸自己的源码
        except Exception:
            continue
        b = os.path.basename(t)
        if b.startswith(("test_", "_", "fault")) or not b.endswith(".py"):
            continue
        for call in offenders(t):
            hits.append((b, call))

    if not hits:
        hook_log(GATE, "pass(没有不留证据的开火)")
        return 0

    # ⛔ 2026-09-07:这道闸自己也要留证据 —— 记分板当场报它 40 次开火 100% 无证据。
    #   第三个参数放【具体是哪一处调用】,否则事后只知道"某个文件有问题"、修不了。
    hook_log(GATE, "NUDGE %s" % ",".join(sorted({h[0] for h in hits})),
             " | ".join("%s: %s" % (b, c) for b, c in hits[:2]))
    lines = ["⛔ 留证据闸:你改的闸里有**开火却不记触发词**的调用 ——"]
    for b, call in hits[:4]:
        lines.append("   · %-30s %s" % (b, call))
    lines += [
        "⛔ 后果很具体(2026-09-07 我自己刚犯):`capability-boundary-gate` 就是这么写的,",
        "   于是记分板报它「同一指纹 180/180 次、复发率 100%、**无证据率 100%**」——",
        "   复发率是【假的】(指纹拿空串算,当然每次一样),但无证据是【真的】:",
        "   **事后没有任何人能判断它那 180 次拦得对不对。**",
        "⛔ 这正是「只有 enforce、没有 measure」的微观形态:闸响了,但没留下可复核的痕迹。",
        "⇒ 改成三参数:`hook_log(NAME, \"BLOCK(...)\", trig(命中的那句话, 140))`",
        "   —— 命中的文本通常就在手边(hit / m.group(0) / said 的那一段)。",
        "(若这道闸确实没有可引的文本、或触发词涉及隐私,说明一句即可。)",
    ]
    # ⛔ 2026-09-11:原来是裸 print。PostToolUse 的纯文本输出只进用户的记录视图、【送不到模型】——
    #   这道闸提醒得再对,模型也一次都没收到过(同批查出 lesson-anchor-gate / flat-table-gate 同病)。
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                             "additionalContext": "\n".join(lines)}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)      # fail-open:观测类闸,绝不挡住他
