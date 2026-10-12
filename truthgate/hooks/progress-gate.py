#!/usr/bin/env python3
"""Stop hook: 进度记录闸 —— 本轮做了实质改动，却没往 PROGRESS.md 记一行就想收尾。

⛔ 为什么需要它（2026-08-12 实录）：
   那天在 bananaflow 修了标签泄漏、装了取证探头、修了两个静默吞错、迁移 pagefile/TEMP、
   抢救凭证、删了 34GB、做了整套换机还原套件 —— **9 次 auto commit 的 message 全是
   "auto: session changes"，项目里压根没有 PROGRESS.md**，是 Frank 问「progress 有全量
   完整更新了吗」我才手写了一份。⇒ 人又成了唯一探测器。
   而 SessionStart 已经有 progress-inject.py 负责【读】进度 —— 读写不对称，
   Stop 这边没人负责【写】，下个 chat 只能从零重挖。

先查现成（2026-08-12 实查 gh api）：
   first-fluke/oh-my-agent (★1221)  stop-hook gates + append-only event logs，思路高度重合，
     但它是一整套多 agent harness，与本机已有的 24 个 Superego 闸会互相打架 → 不装，只借鉴
     「按 artifact 判断而不是按声明判断」这一点
   blader/taskmaster (★515) / andylizf/nonstop (★263)  都是别的用途的 stop hook → 不适用
   ⇒ 改造复用：复用本机 guard_common.py + institutionalize-guard.py 的安全模式，写第 25 个闸

⛔ 为什么 hook 不能自己写 PROGRESS：判断「这轮哪些值得记」要理解语义，脚本做不到。
   所以本闸的定位和 institutionalize-guard 相同 —— 不代劳，只拦住「做了不记」。

触发（全部满足才拦）：
  ① 本轮 Write 了【新】代码文件，或 Edit/Write 了 >=3 个代码文件（改一行不烦人）
  ② 不在 scratchpad/tmp/temp 下、不是 .bak
  ③ 不在 ~/.claude/ 下（改 hooks/skills 本身由 institutionalize-guard 管，别双重拦）
  ④ 本轮没有写 PROGRESS.md 的动作，助手文本也没提「记进 PROGRESS / 更新进度」

安全设计（照 false-done-gate.py / institutionalize-guard.py）：
  fail-open 异常放行 · 只拦一次（per-gate 标记）· 只读 transcript · 窄触发 · 每次留日志
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from guard_common import (hook_log, load_transcript_tail, turn_start_index,
                              self_blocked_this_turn)
except Exception:                       # guard_common 挂了也不能挡住 Frank
    def hook_log(*a, **k): pass
    def load_transcript_tail(tp): return []
    def turn_start_index(msgs): return -1
    def self_blocked_this_turn(*a, **k): return False

GATE = "progress-gate"
CODE_EXT = (".py", ".ps1", ".js", ".mjs", ".cjs", ".ts", ".sh", ".psm1")
SKIP_PATH = re.compile(r"scratchpad|[\\/](?:tmp|temp)[\\/]|\.bak|__pycache__|node_modules", re.I)
IN_CLAUDE = re.compile(r"[\\/]\.claude[\\/]", re.I)
PROGRESS_FILE = re.compile(r"PROGRESS[\w\-]*\.md", re.I)
INTENT = re.compile(r"PROGRESS|进度(文件|记录|文档)|记进度|写进度|更新进度", re.I)


def _log(msg, ctx=""):
    """⛔ 2026-09-09:补 ctx 透传。此前本闸 **59 次开火 100% 无证据**(记分板实测)——
    因为这个包装只传 msg,而记分板认的是 hook_log 的第三个参数 ctx(会被包成 trig='...')。
    信息其实一直都在手上(files 就在 msg 里),只是放错了字段 ⇒ 事后没人能判断它拦得对不对。"""
    try:
        hook_log(GATE, msg, ctx)
    except Exception:
        pass


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    tp = data.get("transcript_path")
    if not tp or not os.path.isfile(tp):
        _log("skip(no transcript)")
        return 0

    try:
        msgs = load_transcript_tail(tp)
        start = turn_start_index(msgs)
        turn = msgs[start:] if start >= 0 else msgs
    except Exception as e:
        _log(f"skip(transcript error: {e!r})")
        return 0

    try:
        if self_blocked_this_turn(GATE, data):
            _log("skip(already blocked)")
            return 0
    except Exception:
        pass

    wrote_new, edited, touched_progress = [], set(), False
    texts = []

    for m in turn:
        # ⛔ transcript 的每行是 {"type":"assistant","message":{"role":..,"content":[..]}}
        #    —— 顶层是 type 不是 role，内容在 message.content。首版我写了 m["role"] 和
        #    m["content"]，于是【永远读不到任何 tool_use】⇒ 这个闸出生即死、永不开火。
        #    负例全过 + 语法通过 + ruff 干净，看着完全正常；只有故障注入的两个正例
        #    (exit=0 而不是 2) 暴露了它。判据恒假的又一次（当天第 N 次）。
        if m.get("type") != "assistant":
            continue
        c = (m.get("message") or {}).get("content")
        if isinstance(c, str):
            texts.append(c)
            continue
        if not isinstance(c, list):
            continue
        for blk in c:
            if not isinstance(blk, dict):
                continue
            if blk.get("type") == "text":
                texts.append(blk.get("text", ""))
            elif blk.get("type") == "tool_use":
                inp = blk.get("input", {}) or {}
                path = str(inp.get("file_path") or inp.get("path") or "")
                if not path:
                    continue
                if PROGRESS_FILE.search(os.path.basename(path)):
                    touched_progress = True
                    continue
                if SKIP_PATH.search(path) or IN_CLAUDE.search(path):
                    continue
                if not path.lower().endswith(CODE_EXT):
                    continue
                if blk.get("name") == "Write":
                    wrote_new.append(path)
                elif blk.get("name") in ("Edit", "MultiEdit", "NotebookEdit"):
                    edited.add(path)

    if touched_progress:
        _log("allow(progress touched)")
        return 0
    if INTENT.search("\n".join(texts)):
        _log("allow(intent mentioned)")
        return 0
    # ⛔ 门槛按"这个项目有没有在用 PROGRESS"分档（2026-08-12 16:xx 调）：
    #    首版是「新建 1 个代码文件就拦」，在别的项目里新建 .py 太常见 ⇒ 会天天烦人，
    #    而「天天烦人的闸」两周后一定被忽略/关掉，等于没有。
    #    · 项目已有 PROGRESS.md → 说明在用这套，严格要求（新建 1 个 或 改 >=3 个就要记）
    #    · 项目还没有 PROGRESS.md → 只在【大改动】时提醒建一个（新建 >=3 个 或 改 >=6 个）
    cwd = data.get("cwd") or os.getcwd()
    has_progress = any(os.path.isfile(os.path.join(cwd, n))
                       for n in ("PROGRESS.md", "progress.md"))
    if has_progress:
        substantial = bool(wrote_new) or len(edited) >= 3
    else:
        substantial = len(wrote_new) >= 3 or len(edited) >= 6
    if not substantial:
        _log(f"allow(not substantial: new={len(wrote_new)} edited={len(edited)})")
        return 0

    # ⛔ 2026-09-07:原来是 `(wrote_new + sorted(edited))[:4]` —— **拼完再截**,
    #   只要新建的够 4 个,【改动过的文件】一个都显示不出来 ⇒ 我看到消息会以为"只新建、没改动"。
    #   这和当晚 guard_common 指纹那个 bug 是**同一个形状**(两段拼一起后整体截断,后一段被全丢),
    #   是照着那次的根因扫全仓找出来的第 2 处(共扫 284 个 .py,其余 10 处逐条核过均良性)。
    #   ⇒ 两边各取一半,谁也挤不掉谁。
    _ed = sorted(edited)
    files = (wrote_new[:2] + _ed[:2]) or (wrote_new + _ed)[:4]
    names = ", ".join(os.path.basename(f) for f in files)
    # ⛔ files 走 ctx(记分板认的证据字段),不再只塞在 msg 里 —— 这样事后能判它拦得对不对。
    _log(f"BLOCK new={len(wrote_new)} edited={len(edited)}", ctx=names or str(files))
    print(
        f"⛔ 进度记录闸：本轮有实质改动（新建 {len(wrote_new)} 个 / 改动 {len(edited)} 个"
        f"代码文件：{names}），但 PROGRESS.md 一个字都没写就想收尾。\n"
        "⛔ 2026-08-12 实录：那天修了标签泄漏、装了取证探头、修了两个静默吞错、做了整套换机"
        "还原套件 —— 9 次 auto commit 的 message 全是 'auto: session changes'，项目里压根没有"
        "PROGRESS.md，是 Frank 问了才手写。**人成了唯一探测器。**\n"
        "⛔ SessionStart 已有 progress-inject.py 负责【读】进度，Stop 这边必须有人负责【写】，"
        "否则下个 chat 只能从零重挖。\n"
        "现在往 PROGRESS.md 补一段再收尾，只记三样（每条带数字，不记打算做什么）：\n"
        "  ① 做了什么　② 什么证据证明它成了（测试/日志/实测数字）　③ 我错在哪（记形状不记细节）\n"
        "（若这轮确实只是临时诊断/探针、不值得记，一句话说明为什么不记即可放行。）",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:              # 任何意外都放行，绝不挡路
        _log(f"fail-open({e!r})")
        sys.exit(0)
