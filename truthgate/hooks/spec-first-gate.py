# -*- coding: utf-8 -*-
"""规格优先闸 —— 本机有对口指南，本轮却没打开就动手 ⇒ 拦。

⛔ 它治的是 Frank 2026-08-20 亲口点破的病：
   「那是你没用用对方法，**你真的懂怎么写 minimax h3 规格的提示词来控制画面和字幕吗？
     本地和多宇宙没用指南，你自己全部做的事是不是猜测的？**」

   实录：我按「项目里某个老脚本的注释」+ 推断写 H3 提示词，跑 4 次、烧 300+ 币，
   还把自己写错造成的「字幕被烧」当成模型缺陷去报告、准备再烧 3×114 币试参数。
   而本机躺着三份权威指南我一份没读，其中一份的文件名当天还被我 `ls` 到、打印在眼前：
     · skills/h3-prompt-writing/references/ref-en.txt   （Ref2VA 官方六段式）
     · skills/h3-prompt-writing/references/base-en.txt  （台词 <d> 标签 / 屏幕文字规则）
     · skills/runninghub/references/h3-production-field-manual.md（现场手册 14KB）
   读完按规格重写，**一次跑通**，字幕/发呆/走位三个问题全解。
   ⇒ lessons 形状 2026-08-20-U：**看见文件名 ≠ 读过**。

⛔ 为什么已有的 13 条铁律拦不住：
   它们都是**单点行为规则**，没有一条管**顺序**。当天我每条都打了勾
   （查了现成、验证了、外审了），**顺序却是反的** —— 先动手，再用那些动作补票。
   本闸补的就是这个顺序：**先读规格，才动手**。

先查现成（2026-08-20 本轮实跑，六宇宙）→ 判定【自建，架构照业界】：
  · 本机：`pipeline-first-gate.py` 思想最近（没画链路图不许开工），
    其 `read_this_turn(transcript)` 机制**直接复用**，不重写检测逻辑
  · GitHub：`disler/claude-code-hooks-mastery`(★3899) · `karanb192/claude-code-hooks`(★481)
    · `BotchetDig/workout-gate`(★219，同构的"阻塞直到你做了某事") —— 生态成熟，
    但**没有一个是「强制读本机指南」**的（那必须绑我的文件布局）
  · 业界模式：这是公认的 "neurosymbolic pattern"（LLM 推理 + 不可被模型覆盖的确定性规则），
    各框架都有 pre-tool hook（Claude Code PreToolUse / LangChain on_tool_start /
    Cursor beforeShellExecution / CrewAI @before_tool_call）。
    业界原话正是我的病：**「the LLM read it and ignored it」** —— 文档写了也没用，要框架级拦。
  ⇒ 架构照业界，判据自建。

判据（三条同时成立才拦，避免误伤）：
  ① 本轮在做【实质开工】动作（写提示词/调生成 API/跑生产脚本），不是只读或验证
  ② 本机 `skills/*/references/` 下存在与当前主题**同名匹配**的指南
  ③ 本轮 transcript 里**没有出现过那个文件名**（= 没读过）
"""
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
SKILLS = os.path.join(HOME, ".claude", "skills")

# ① 实质开工动作：会产出内容 / 花钱 / 改生产文件的
PRODUCE = re.compile(
    r"(prompt\s*=|PROMPT\s*=|提示词|--run\b|\.generate\b|generate\("
    r"|chat/completions|/v1/(images|videos|audio)|submit_task|enqueue_"
    r"|runninghub_workflow\.py\s+--run|gen_\w+\.py|e2e\w*\.py)", re.I)

# 只读 / 验证 / 测试类：放行
# ⛔ 2026-08-21 补：加了 hooks 目录自身 —— 我改闸的代码时，文件里必然出现
#    "runninghub"/"h3" 这些词（因为闸就是靠它们判主题），结果**闸拦住了改闸的人**。
#    当轮真实误伤：我在 Edit scenario-fit-gate.py，被 spec-first-gate 要求先去读 H3 指南。
EXEMPT = re.compile(
    r"(--info\b|--explain\b|--check\b|--dry-run|--help\b|\bcat\b|\bhead\b|\bls\b"
    r"|\bgrep\b|ffprobe|volumedetect|pytest|test_|_test\.py|self_test"
    r"|SPEC-OK|--list\b|fault_inject|verify_"
    r"|[\\/]\.claude[\\/]hooks[\\/]|-gate\.py|guard_common)", re.I)

# ② 主题 → 该主题的指南必须读过
TOPICS = [
    (re.compile(r"(minimax|hailuo|\bh3\b|ref2va|fl2va|i2va|t2va)", re.I),
     ("h3-production-field-manual", "ref-en.txt", "base-en.txt")),
    (re.compile(r"runninghub|workflow_id|--instance-type", re.I),
     ("h3-production-field-manual", "video-models", "ai-application")),
    (re.compile(r"seedance|ai2box", re.I), ("seedance-cookbook",)),
    (re.compile(r"comfyui", re.I), ("h3-production-field-manual", "video-models")),
]

MSG = u"""⛔ 规格优先闸：这件事【本机有指南】，而你本轮一份都没打开。

主题命中：{topic}
本机有、你没读的：
{docs}

⛔ 2026-08-20 实录（Frank 原话：「你真的懂怎么写 minimax h3 规格的提示词来控制画面和字幕吗？
   本地和多宇宙没用指南，**你自己全部做的事是不是猜测的**？」）：
   我按「某个老脚本的注释」+ 推断写 H3 提示词 → 跑 4 次、烧 300+ 币，
   还把自己写错造成的「字幕被烧」当模型缺陷报告、准备再烧 3×114 币试参数。
   读完指南后按规格重写，**一次跑通** —— 字幕/发呆/走位三个问题全解。
   我当天还 `ls` 到过其中一份的文件名：**看见了，没打开**（lessons 形状 2026-08-20-U）。

⇒ 现在用 Read 真的打开它们（不是 grep 一行），再回来动手。

（只读/验证类不受此限：--info/--explain/--check/--dry-run/ffprobe/pytest…；
 确认无关时命令里加 `SPEC-OK` 放行。）
"""


def find_docs(patterns):
    """在 skills/*/references/ 下找匹配的指南，返回真实路径。"""
    hits = []
    if not os.path.isdir(SKILLS):
        return hits
    for skill in sorted(os.listdir(SKILLS)):
        ref = os.path.join(SKILLS, skill, "references")
        if not os.path.isdir(ref):
            continue
        try:
            fns = sorted(os.listdir(ref))
        except OSError:
            continue
        for fn in fns:
            if any(p.lower() in fn.lower() for p in patterns):
                hits.append(os.path.join(ref, fn))
    return hits


def read_this_turn(docs, transcript_path):
    """本轮有没有真读过这些指南（复用 pipeline-first-gate 的做法）。"""
    if not transcript_path or not os.path.exists(transcript_path):
        return True                      # 拿不到 transcript 不误伤
    try:
        sys.path.insert(0, os.path.join(HOME, ".claude", "hooks"))
        import guard_common as gc
        raw = gc.load_transcript_tail(transcript_path)
        msgs = raw if isinstance(raw, list) else gc._parse_jsonl(raw)
        msgs = msgs[gc.turn_start_index(msgs):]
    except Exception:
        return True
    bases = [os.path.basename(d) for d in docs]
    for m in msgs:
        try:
            blob = json.dumps(m, ensure_ascii=False)
        except Exception:
            continue
        if any(b in blob for b in bases):
            return True
    return False


def check(text, transcript_path=None, _docs_finder=None, _read_checker=None):
    """返回 (topic, docs) 表示要拦；None 表示放行。抽出来供测试直接调。"""
    finder = _docs_finder or find_docs
    reader = _read_checker or read_this_turn
    if not text or len(text) > 200000:
        return None
    if EXEMPT.search(text):
        return None
    if not PRODUCE.search(text):
        return None
    for rx, pats in TOPICS:
        m = rx.search(text)
        if not m:
            continue
        docs = finder(pats)
        if not docs:
            continue                     # 本机没这份指南，不能怪我没读
        if reader(docs, transcript_path):
            return None
        return (m.group(0), docs)
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    ti = data.get("tool_input") or {}
    text = " ".join(str(ti.get(k) or "") for k in
                    ("command", "content", "new_string", "prompt", "file_path"))
    hit = check(text, data.get("transcript_path"))
    if not hit:
        sys.exit(0)
    topic, docs = hit
    sys.stderr.write(MSG.format(
        topic=topic,
        docs="\n".join("  · %s" % d.replace(HOME, "~") for d in docs[:6])))
    sys.exit(2)


if __name__ == "__main__":
    main()
