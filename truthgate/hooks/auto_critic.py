#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""L3 异构裁判【自动化】—— 打破 superego 最深的那个根因:盲点共享。

⛔ 为什么这是最该做的一层(形状 2026-09-06-S,来自 Frank 自己的知识库):
   > 「**盲点共享**:生成者与评价者是同一个底座模型 ——
   >   让一个色盲去检查另一个色盲有没有看错红绿灯,根本查不出来。」
   superego 的闸是我写的、判据是我定的、锚点是我调的、连回归测试都是我写的。
   **生成者和评价者全是我。** 就算建了记分板(measure),读它、决定怎么改的还是我。
   ⇒ 唯一的出路是【引入异构裁判】——别的模型、确定性规则、真实运行结果。

⛔ 现状的缺口不是"没有裁判",是"**裁判要我自己想起来去请**":
   `second-opinion.py`(异模型、零 Claude 额度、约 40 秒)早就有了,
   而 `critic-gate` 做的是**打印一段提醒让我去跑**。
   ⇒ 于是它落回"我自己判断要不要请裁判"—— 盲点共享原封不动。

⛔ 为什么做成【异步】而不是同步跑:
   second-opinion 约 40 秒,而 Stop 闸的预算是 25 秒。同步跑会超时被 harness 杀掉
   ⇒ 变成静默失效(今晚刚量过:语义层 45.5% 静默失效就是这么来的)。
   ⇒ 本轮【发出去】,下一轮【收结果】。异模型说不同意 → 那时才拦。
   这也更像真实 CI:提交触发检查,检查完才报告。

安全设计:
  · 全程 fail-open:发不出去、收不到、解析不了 → 一律不拦(绝不因为裁判层出问题而卡住他);
  · 后台进程 detached + 自带超时,不占 Stop 闸的时间预算;
  · 裁定文件按 session 隔离(今晚刚修过熔断器的跨会话传染,别再犯同一个错);
  · 只在【常规档】用它;高危档仍要求派 Agent 子实例(异模型没有工具,核不了现实)。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SO = os.path.join(os.path.dirname(HERE), "superego-critic", "second-opinion.py")

# 裁定文件按 session 隔离 —— 2026-09-06 刚修过熔断器"全机唯一 ⇒ 跨会话传染"的坑,别重犯
def _verdict_path(sid=None):
    sid = (sid or os.environ.get("CLAUDE_CODE_SESSION_ID") or "nosid")[:16]
    d = os.environ.get("SUPEREGO_LOG_DIR") or HERE
    return os.path.join(d, ".auto-critic-%s.json" % sid)


DISAGREE = re.compile(r"不同意|反对|错误|有问题|不成立|矛盾|disagree|incorrect|wrong", re.I)
AGREE = re.compile(r"^\s*同意|^\s*agree|断言正确|判断正确", re.I | re.M)
UNSURE = re.compile(r"无法判断|不确定|信息不足|cannot determine|insufficient", re.I)


def pick_claim(text, max_len=220):
    """从我这轮说的话里挑一条【最像交付断言】的句子当被检验对象。

    ⛔ 判据要贴着"可验证"来:优先带数字/文件名/测试结果的句子 ——
      那种才是异模型能对着代码核的。纯感想句核不了,挑了也是浪费 40 秒。
    """
    segs = [s.strip() for s in re.split(r"[\n。!?！？]+", text or "") if 12 <= len(s.strip()) <= max_len]
    if not segs:
        return ""
    SCORE = re.compile(r"\d|\.py|\.js|测试|回归|接线|生效|跑通|修好|覆盖|全绿")
    scored = [(len(SCORE.findall(s)), i, s) for i, s in enumerate(segs)]
    scored.sort(key=lambda x: (-x[0], -x[1]))       # 分高优先,同分取靠后的(更接近结论)
    return scored[0][2] if scored[0][0] > 0 else segs[-1]


def read_verdict(sid=None):
    """取上一轮发出去的裁定。返回 dict 或 None。任何异常 → None(fail-open)。"""
    try:
        p = _verdict_path(sid)
        if not os.path.exists(p):
            return None
        d = json.load(open(p, encoding="utf-8"))
        if not d.get("done"):
            return None
        return d
    except Exception:
        return None


def clear_verdict(sid=None):
    try:
        p = _verdict_path(sid)
        if os.path.exists(p):
            os.unlink(p)
    except Exception:
        pass


def classify(answer):
    """异模型的回答 → agree / disagree / unsure。

    ⛔ 顺序要紧:先看有没有明确"同意"开头(它的输出格式就是首行给结论),
      再看不同意词,最后才是"无法判断"。反过来会把"同意…但要注意错误处理"读成 disagree。
    """
    a = (answer or "").strip()
    if not a:
        return "unsure"
    head = a[:40]
    if AGREE.search(head):
        return "agree"
    if UNSURE.search(head):
        return "unsure"
    if DISAGREE.search(head):
        return "disagree"
    # 首行没结论 → 看全文倾向,但保守:拿不准算 unsure(不拦)
    if DISAGREE.search(a) and not AGREE.search(a):
        return "disagree"
    return "unsure"


def pick_file(claim, files):
    """从本轮改过的文件里挑【断言真正在说的那个】。挑不出 ⇒ 返回 None(=这轮不审)。

    ⛔ 单独成函数,是为了能被回归**直接调**(`test_auto_critic_pick.py`)——
       原来这段埋在 fire() 里,而 fire() 会 spawn 后台进程 + 有外部依赖,
       测试只能绕着走或复制一份判据。**复制判据正是今晚在治的病**,所以抽出来。

    ⛔ 2026-09-07:**断言里提到的文件优先**。
      原来是 `next(第一个代码文件)` —— 完全不看断言在说哪个文件。
      实录:断言说的是 residue-gate.py 里的一段注释,送过去的却是我刚改的临时脚本
      ⇒ 异模型回「这段代码里没有那段注释」—— 它说得对,但那不是被断言的文件。
      ⇒ 裁判被喂错材料 = 它的"不同意"变成噪音,而噪音多了我会开始无视这一层,
        那才是最坏的结果(它是我唯一的外部视角)。
    """
    cands = [x for x in (files or [])
             if isinstance(x, str) and os.path.exists(x)
             and x.endswith((".py", ".js", ".mjs", ".cjs", ".ts"))]
    # ⛔ 2026-09-08 补①:**草稿不是交付物,永远不该被当成被审对象**。
    #   scratchpad/tmp 里的探针是我为了验证【别的文件】临时写的,送过去 = 保证审错。
    cands = [x for x in cands
             if not re.search(r"scratchpad|[\\/]tmp[\\/]|[\\/]temp[\\/]"
                              r"|AppData[\\/]Local[\\/]Temp", x, re.I)]
    if not cands or not claim:
        return None
    f = next((x for x in cands if os.path.basename(x) in claim), None)
    if f is None:
        # 退一步:断言里提到不带扩展名的名字(如 `residue-gate`)也算
        f = next((x for x in cands
                  if os.path.splitext(os.path.basename(x))[0] in claim), None)
    if f is None:
        # 再退一步:连字符/下划线归一化后再比(`self-loop-gate` ↔ `self_loop_gate`)
        _nc = re.sub(r"[-_]", "", claim.lower())
        f = next((x for x in cands
                  if re.sub(r"[-_]", "",
                            os.path.splitext(os.path.basename(x))[0].lower()) in _nc), None)
    # ⛔ 2026-09-08 补②:兜底**保留**(原设计:断言没点名时也别让这一层沉默),
    #   但它现在只在【已经排除草稿】的候选里挑 —— 昨晚的真凶是草稿被选中,
    #   不是"有兜底"这件事本身。
    #   我第一版把兜底整个删掉,当场被既有回归打红:
    #   `⭐断言里没点名时仍有兜底(不至于发不出去)` —— **那是刻意的设计,不是疏漏**。
    #   ⇒ 修 A 时别顺手拆掉 B。排除草稿 + 保留兜底,两个目的同时满足。
    return f or cands[0]


def fire(claim, files, sid=None, timeout=180):
    """后台发一次异构审查。返回 True=发出去了。全程 fail-open。"""
    try:
        if not claim or not files or not os.path.exists(SO):
            return False
        f = pick_file(claim, files)
        if not f:
            return False
        p = _verdict_path(sid)
        payload = {"done": False, "claim": claim, "file": f, "t": time.time(),
                   "fp": hashlib.sha1((claim + f).encode("utf-8")).hexdigest()[:10]}
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        runner = os.path.join(HERE, "auto_critic_run.py")
        if not os.path.exists(runner):
            return False
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x08000000   # DETACHED_PROCESS | NO_WINDOW
        subprocess.Popen([sys.executable, runner, p, str(timeout)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         cwd=HERE, **kw)
        return True
    except Exception:
        return False
