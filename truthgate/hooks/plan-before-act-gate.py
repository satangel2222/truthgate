# -*- coding: utf-8 -*-
"""计划优先闸 —— 要花钱 / 要长跑的动作，本轮没有 plan ⇒ 拦。

⛔ 它补的是 SOP 第 ⑤ 步（才动手）。Frank 2026-08-20 原话：
   「**你凭什么就开始动**？…**你做任何东西前有没用 plan？铁规则！！！！！**」

⛔ 为什么单独做一道：
   `pipeline-first-gate` 只在【有链路文档的项目】管用（它找 pipeline/workflow 类文档）；
   跨项目的通用情形（跑一次要花钱的生成、后台挂几小时的任务）它一律放行。
   而这两类恰恰是**做错了代价最高**的：2026-08-20 我没 plan 就连跑 4 次 H3 出片，
   烧 300+ 币，其中前 3 次全因为提示词写错（没先读本机规格）——
   **有 plan 的话第一步就会写「先读 h3-prompt-writing 规格」**，后面三次都不用跑。

先查现成（2026-08-20 本轮实跑）→ 判定【自建，架构照业界】：
  · 本机：60+ hook 里没有通用 plan 闸；复用 `pipeline-first-gate` 的 transcript 检测机制
  · GitHub：`agent plan before execute enforce` / `claude code plan mode hook gate`
    两组关键词**零命中**
  · 业界（cost guardrail 领域已有定论）：控制逻辑要**贴近执行**、在**不可逆动作之前**拦，
    而不是事后告警；且 **plan 里应有 "what if I am wrong?" 一节**（本闸提示词已采纳）
  ⇒ 架构照业界，判据自建。

⛔ 判据故意收窄（宁可漏拦，不要天天误伤）：
   只卡【花钱】和【长跑】，不卡普通写代码/改文件——那些错了 revert 就行，代价低。
"""
import json
import os
import re
import sys

HOME = os.path.expanduser("~")

# ① 花钱 / 长跑：做错了代价高的动作
COSTLY = re.compile(
    r"(--run\s+\d{15,}"                       # RunningHub 跑工作流（花币）
    r"|/v1/(images|videos|audio)/gener"        # 生成类 API
    r"|submit_task|enqueue_videos|generate_video_episode"
    r"|\bnohup\b"
    r"|timeout\s+([6-9]\d{2}|\d{4,})"         # timeout ≥ 600 秒
    r"|e2e\w*\.py|autowrite\.py)", re.I)

# 2026-09-08:「这条命令只是查看/测试」那半段与 scenario-fit-gate 一字不差,
#   补一种新测试跑器写法只补一边 ⇒ 另一边继续误伤同一条命令。共享前半,各留自己的放行码。
try:
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from guard_common import SHARED_DRYRUN_EXEMPT as _SHARED_DRY
    _DRY = _SHARED_DRY.pattern
except Exception:
    _DRY = r"(--dry-run|--help\b|--list\b|pytest|test_|verify_)"   # 应急最小版
EXEMPT = re.compile(_DRY + r"|(ffprobe|ffmpeg|PLAN-OK|\bgrep\b|\bcat\b|\bls\b|\bhead\b)", re.I)

# ③ plan 的迹象：本轮出现过这些即算有计划
PLAN_SIGNS = re.compile(
    r"(ExitPlanMode|EnterPlanMode|TodoWrite"
    r"|#+ *(计划|方案|步骤|plan)\b"
    r"|我(打算|准备|会)(先|按)"
    r"|第一步|①.{0,80}②"
    r"|PLAN\.md|plan\.md)", re.I)

MSG = u"""⛔ 计划优先闸：这是个【要花钱 / 要长跑】的动作，而你本轮没有任何 plan。

命中：{hit}

⛔ Frank 2026-08-20 原话：「**你凭什么就开始动**？…
   **你做任何东西前有没用 plan？铁规则！！！！！**」

⛔ 当天实录：我没 plan 就连跑 4 次 H3 出片，烧 300+ 币 ——
   前 3 次全因为提示词写错（没先读本机规格）。**有 plan 的话第一步就会写
   「先读 h3-prompt-writing 规格」**，后面三次根本不用跑。

⇒ 先写三行 plan 再动手，不用长，但要有这三样：
   ① 做什么、按什么顺序   ② 怎么算成功（可验证的判据）
   ③ **万一我错了会怎样** —— 业界 cost-guardrail 的标准要求：
      跑飞了要多久发现？花多少钱？能不能回滚？

（只读/验证/测试类不受此限；确认不需要 plan 时命令里加 `PLAN-OK` 放行。）
"""


def has_plan(transcript_path, extra_text=""):
    """本轮有没有 plan 的迹象。"""
    if PLAN_SIGNS.search(extra_text or ""):
        return True
    if not transcript_path or not os.path.exists(transcript_path):
        return True                       # 拿不到 transcript 不误伤
    try:
        sys.path.insert(0, os.path.join(HOME, ".claude", "hooks"))
        import guard_common as gc
        raw = gc.load_transcript_tail(transcript_path)
        msgs = raw if isinstance(raw, list) else gc._parse_jsonl(raw)
        msgs = msgs[gc.turn_start_index(msgs):]
    except Exception:
        return True
    for m in msgs:
        try:
            blob = json.dumps(m, ensure_ascii=False)
        except Exception:
            continue
        if PLAN_SIGNS.search(blob):
            return True
    return False


def check(text, transcript_path=None, _plan_checker=None):
    """返回命中的动作字符串表示要拦；None 放行。抽出来供测试直接调。"""
    planner = _plan_checker or has_plan
    if not text or len(text) > 200000:
        return None
    if EXEMPT.search(text):
        return None
    m = COSTLY.search(text)
    if not m:
        return None
    if planner(transcript_path, text):
        return None
    return m.group(0)[:60]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    ti = data.get("tool_input") or {}
    text = " ".join(str(ti.get(k) or "") for k in
                    ("command", "content", "new_string", "prompt"))
    hit = check(text, data.get("transcript_path"))
    if not hit:
        sys.exit(0)
    sys.stderr.write(MSG.format(hit=hit))
    sys.exit(2)


if __name__ == "__main__":
    main()
