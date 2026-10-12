#!/usr/bin/env python3
"""PostToolUse 闸:【改到第 N 处时,逼我问一次"这几处是不是本该一处"】。

2026-07-28 建。这是 Superego 里**唯一一道问"方案对不对"的闸** —— 此前 32 处挂载
全部是【过程纪律】闸(查没查现成/有没有虚报/有没有甩锅/有没有请示/时间对不对),
**没有一道问「这个方案是不是最好的那个方案」**。

⛔ 缺口是 Frank 的师兄指出来的(2026-07-26 群聊原话):
   「他给的解决方案都是小部分组成的」「若你的改动很大,要认真去看每个细节,
     考虑是不是要合并或者更好的方案」「do right things / do things right —— 他只能做前者」
   Frank 2026-07-28 复述并要求补齐:「补缺我师兄说的哪些空缺」。

⛔ **同日的活标本(就是我自己犯的,别当理论)**:我给 `spec-coverage-guard` 写判据时,
   从 `prior-art-gate` 抄了一行 `if os.path.exists(fp): return False`。两处代码单看都对,
   **但那是 PreToolUse 闸(文件尚未写入)、我这道是 PostToolUse 闸(文件必然已存在)**
   ⇒ 判据恒 False ⇒ **整道闸从挂上到被外部审查发现,一次都没开过火**,而我还宣布"装好了"。
   典型的【局部零件都对、拼起来是错的】。当天所有其它闸没有一道拦得住它 —— 因为它们
   问的都是"你有没有偷懒",而这件事我一点没偷懒,我是**认真地做错了方向**。

━━ 判据(纯计数,零语义) ━━
 本轮(transcript 里当前 turn)用 Edit/Write 动过的【不同实业务文件】数量 == THRESHOLD 时,
 注一次三问。**恰好等于才注**(>THRESHOLD 不再注)⇒ 天然每轮只提醒一次,不需要
 per-turn 标记(今天实测那套标记在 PostToolUse 上做不出真正的"本轮",见 spec-coverage 注释)。

⛔ 档位:**nudge,绝不阻塞**(2026-07-28 定的规矩:新闸首版一律软档,拿真实日志再谈升级)。
   它只把三个问题摆到我眼前 —— 这正是它要治的病:我不是懒,是**没停下来想**。

先查现成(2026-07-28):WebSearch「architecture coherence review hook / fragmented patchwork /
 consolidation detector」+ gh search → `agent-coherence`(多 agent 共享状态脏读,不是这回事)、
 其余全是论文与综述,**无现成 hook 形态实现** ⇒ 只能自建。
回归:`test_coherence_guard.py`。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from guard_common import hook_log
except Exception:
    def hook_log(*a, **k): pass
try:
    from guard_common import trig
except Exception:
    def trig(s, n=120): return (s or "")[:n]
try:
    from guard_common import load_transcript_tail
except Exception:
    def load_transcript_tail(*a, **k): return []

import sys, os, json, re

# 2026-07-28:判据统一到 guard_common(critic:两个闸各抄一份 = 补豁免只补一边)。
#   取不到就回退本文件下面那份 —— 共享失败绝不能让整道闸失效。
try:
    from guard_common import SHARED_EXEMPT_PATH as EXEMPT_PATH, SHARED_CODE_EXT as CODE_EXT
    _SHARED_OK = True
except Exception:
    _SHARED_OK = False


try:
    sys.stdout.reconfigure(encoding="utf-8"); sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

NAME = "coherence"
THRESHOLD = 3          # 改到第 3 个不同文件时问一次

# 只数【实业务文件】:测试/临时/生成物/依赖不算"方案的一部分"
if not _SHARED_OK:
    EXEMPT_PATH = re.compile(
    r"scratchpad|[\\/]tmp[\\/]|[\\/]temp[\\/]|AppData[\\/]Local[\\/]Temp"
    r"|[\\/]test_|[\\/]tests?[\\/]|\.test\.|\.spec\.|_test\.|conftest\.py"
    r"|[\\/]migrations?[\\/]|[\\/]generated[\\/]|[\\/]vendor[\\/]|\.generated\."
    r"|node_modules|[\\/]\.git[\\/]|dist[\\/]|build[\\/]|\.min\.",
    re.I,
)
# 文档/配置改动不触发"方案整合"思考(改 md 不是在设计方案)
if not _SHARED_OK:
    CODE_EXT = re.compile(
    r"\.(py|mjs|cjs|js|jsx|ts|tsx|vue|svelte|go|rs|java|rb|php|html|htm|css|scss|sql|ps1|sh)$", re.I)


def touched_business_files(turn_msgs):
    """本轮用 Edit/Write 动过的不同实业务文件(规范化路径集合)。"""
    out = set()
    try:
        for m in turn_msgs or []:
            if m.get("type") != "assistant":
                continue
            for c in (m.get("message") or {}).get("content") or []:
                if (isinstance(c, dict) and c.get("type") == "tool_use"
                        and c.get("name") in ("Edit", "Write", "NotebookEdit")):
                    fp = str((c.get("input") or {}).get("file_path") or "")
                    if not fp or EXEMPT_PATH.search(fp) or not CODE_EXT.search(fp):
                        continue
                    out.add(os.path.normcase(os.path.abspath(fp)))
    except Exception:
        return set()          # 解析不了 → 当作没改,静默(fail-open)
    return out


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    try:
        # ⛔⛔ 2026-09-07 判效果不判手法(形状 2026-09-07-C 的第 3 处):
        #   原来只认 Edit/Write/NotebookEdit,而我**大量用 Bash 跑脚本改文件**
        #   (避转义坑,是 shell-writes-code-gate 教的)⇒ 这道闸对最常用那条路完全看不见。
        #   它的职责恰恰是"问方案对不对/数这轮改了几处"——看不见就等于没有。
        #   ⇒ 工具路径照旧(精准);Bash 类走 recently_changed()(实测扫一次 0.026~0.048s);
        #     Read/Grep 这种不可能写文件的照旧不管(见谁都扫 = 新噪音源)。
        _tn = data.get("tool_name")
        _scan_targets = []
        if _tn not in ("Edit", "Write", "NotebookEdit"):
            if _tn in ("Bash", "PowerShell", "Task", "Agent"):
                try:
                    from guard_common import recently_changed
                    _scan_targets = recently_changed(within=90, exts=(".py",), limit=5)
                except Exception:
                    _scan_targets = []
            if not _scan_targets:
                sys.exit(0)

        # ⛔⛔ 2026-08-14 新增判据(lessons 形状 2026-08-14-E 的机器防御):
        #   **同一个文件里第 N 次为同一个病补词表 = 方法错了,不是还不够努力。**
        #   实录:promise-gate 的注释里已经写着两条「词表没有 X ⇒ 补上」的复盘,今天我补第三次;
        #   而语义兜底 `guard_common.should_escalate` 三周前就建好、旁边的闸一直在用,
        #   它的文档里甚至写着 Frank 的原话「是不是用死板的缝缝补补抓文字,而不是语义?」和结论
        #   「**每补一次,新词面立刻逃逸——这是架构必然,不是词表不够努力**」。
        #   ⇒ 判据用【结构信号】而不是词面:数这个文件里有几条「补词表」性质的复盘注释。
        #     ≥2 条 = 至少补过两次 = 该停下来问「有没有结构性替代」,而不是补第三次。
        fp = ((data.get("tool_input") or {}).get("file_path") or "")
        if not fp and _scan_targets:
            fp = _scan_targets[0]          # Bash 路径:拿最近变过的那个 .py 来看
        if fp.endswith(".py") and os.path.exists(fp):
            try:
                _src = open(fp, encoding="utf-8", errors="replace").read()
                _pat = re.compile(r"(词表(没有|里没|不够|漏)|漏掉.{0,8}(词|说法|形)|补(上|齐)?.{0,4}词"
                                  r"|新词面|又漏了.{0,6}(一个|这个)?(词|说法))")
                _hits = _pat.findall(_src)
                if len(_hits) >= 2 and "should_escalate" not in _src and "intent_margin" not in _src:
                    # ⛔ 2026-09-07 补触发词:留下命中的那几句,否则事后判不出是真该提醒还是撞词。
                    hook_log(NAME, "NUDGE(词表第N次) %s 里有 %d 条补词表复盘、且没用语义兜底"
                             % (os.path.basename(fp), len(_hits)),
                             " | ".join(str(h) for h in _hits[:3]))
                    print(json.dumps({"hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": (
                            "⛔ 补词表闸:`%s` 里已经有 **%d 条「词表漏了 X ⇒ 补上」的复盘注释**,"
                            "而它**没有用任何语义兜底**。\n"
                            "⛔ 2026-08-14 实录(形状 E,最贵的一条):promise-gate 为同一个病补了三次词表 —— "
                            "而语义兜底 `guard_common.should_escalate` **三周前就建好、旁边的闸一直在用**,"
                            "它的文档里写着 Frank 的原话「是不是用死板的缝缝补补抓文字,而不是语义?」"
                            "和结论「**每补一次,新词面立刻逃逸 —— 这是架构必然,不是词表不够努力**」。\n"
                            "⇒ 停一下,先答一句:**这个病是不是已经有结构性答案、而那个能力已经在仓库里?**\n"
                            "   · 自由句式的判断 → `should_escalate(text, POS, NEG)`(关键字没命中时问语义)\n"
                            "   · 结构性的形态(编号清单/枚举/代码模式)→ 正则仍然是对的,继续补没问题\n"
                            "   两者分工:**结构归正则、自由句归语义**。补第 N 次之前先分清这次属于哪一半。"
                            % (os.path.basename(fp), len(_hits)))}}, ensure_ascii=False))
                    sys.exit(0)
            except Exception:
                pass

        files = touched_business_files(load_transcript_tail(data.get("transcript_path")))
        n = len(files)
        # ⛔ 2026-07-28 当天修的真 bug:初版写的是 `if n != THRESHOLD: exit` —— 用【恰好等于】
        #   做边沿检测。但 hook 只在每次工具调用后跑一次、transcript 还有落盘延迟 ⇒ 计数会
        #   从 2 直接跳到 4,**边沿一旦被跳过就永远不响**。实测:本轮计数已到 10,闸一次没响,
        #   `coherence.log` 根本不存在 —— 我今天【第二次】建出死闸(第一次是 spec-coverage)。
        #   ⇒ 改成【累计门槛】:每新积累 THRESHOLD 个文件问一次,用标记记住上次问时的计数。
        #   这样既不漏(>= 而非 ==),也不刷屏(不到下一个门槛不重复)。
        if n < THRESHOLD:
            sys.exit(0)
        sid = (os.environ.get("CLAUDE_CODE_SESSION_ID") or "nosid")[:16]
        mdir = os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
        mark = os.path.join(mdir, f".coherence-{sid}")
        last = 0
        try:
            last = int(open(mark, encoding="utf-8").read().strip() or 0)
        except Exception:
            last = 0
        # ⛔ critic 抓到:load_transcript_tail 读的是 4MB **尾窗**,长会话里窗口滑动会让 n 回落,
        #   而 marker 是单调高水位 ⇒ **恰恰在最长、最该提醒的会话里永久哑掉**。n 回落即重置。
        if n < last:
            last = 0
        if n < last + THRESHOLD:
            sys.exit(0)
        try:
            open(mark, "w", encoding="utf-8").write(str(n))
        except Exception:
            pass

        names = sorted(os.path.basename(p) for p in files)
        hook_log(NAME, f"NUDGE {n} files touched (threshold={THRESHOLD}), asking coherence 3Q", trig(", ".join(names), 120))
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"🧩 整合三问(你这轮已动了 {n} 个实现文件:{', '.join(names)})\n"
                "⛔ 这不是问你有没有偷懒 —— 是问你**方向对不对**。Superego 其余所有闸都只盯"
                "「有没有虚报/甩锅/没查现成」,唯独这一条盯【认真地做错方向】。\n"
                "停 10 秒,逐条答(答完照常继续,本闸不阻塞):\n"
                "  1️⃣ **这几处是不是本该一处?** 它们在解决同一个根因吗?如果是,散着改 = 下次同一个病"
                "还会从没改到的那处冒出来。(ponytail:一个共享函数里加一道守卫 < 在每个调用方各加一遍)\n"
                "  2️⃣ **有没有更简单的走法?** 现在这条路是不是我第一个想到的、而不是最好的?"
                "能不能删掉一半、或者用已经存在的东西?\n"
                "  3️⃣ **这东西到底该不该存在?** 如果答案是「其实不需要」,那前两问都白问。\n"
                "⛔ 特别当心【跨场景抄判据】:同一段逻辑搬到另一个地方,它依赖的前提可能正好反过来。\n"
                "   实录(2026-07-28,我自己):把 `os.path.exists` 从 PreToolUse 的闸抄进 PostToolUse 的闸 —— "
                "前者文件还没写、后者文件必然已存在 ⇒ 判据恒假 ⇒ **整道闸从没开过火,我还宣布装好了**。"
                "两段代码单看都对,拼起来是错的。这正是师兄说的「方案都是小部分组成的」。"
            ),
        }}, ensure_ascii=False))
        sys.exit(0)
    except Exception:
        sys.exit(0)                        # fail-open


if __name__ == "__main__":
    main()
