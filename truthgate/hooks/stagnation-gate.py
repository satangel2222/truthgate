#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Stop 闸:【语义停滞】—— 我连着几轮换着说法说同一件事,实质没有推进。

⛔ 起因(2026-09-07,Frank 一整晚在看的就是这个):
   「已经迭代了3个月没有一点进步…很多时候变成了累赘的工具」
   而他自己知识库里那篇(`agent-self-correction-loop-detection-strategies.md`)
   把这个状态命名为 **soft loop / agent death spiral**:
   > 「表面上一直在工作、日志跑得热热闹闹,实际上在原地反复横跳,持续烧 token。
   >   这种循环如果不做专门的工程化监控,可能凌晨三点跑掉你一大笔钱,你都不知道。」

⛔ 它给的四个检测手段里,这是**第一个也是对 soft loop 最有效的那个**:
   > 「语义停滞检测:拿一个滑动窗口覆盖最近几轮的输出,计算它们之间的余弦相似度。
   >   如果连续三轮相似度都超过阈值(比如 0.92),说明 agent 虽然在不停换说法,
   >   但实质内容没有任何推进 —— 这就是原地打转。」

⛔ 实测(2026-09-07):本机 superego 有 53 道 Stop 闸,**做语义停滞检测的:0 道**。
   `churn-guard` 做的是"同一文件反复改"(动作层),不是"说法在变、内容没变"(语义层)。

判据(全中才拦,宽放窄拦):
  ① 本轮起点往前,取最近 N=3 轮我的完整发言
  ② 两两余弦相似度(用本机语义服务的 /embed,零成本)
  ③ **全部 ≥ 0.92** ⇒ 三轮在说同一件事 ⇒ 拦,要求跳出细节重新规划
  ④ 每段至少 200 字(太短的相似度没意义,寒暄/确认句会误伤)

⛔ 安全设计:
   · fail-open:服务挂/取不到三轮/异常 → 一律放行;
   · 自己拦过一次就不再拦(防死循环 —— 这道闸自己就是治循环的,更不能变成循环源);
   · 走 `turn_budget_ok`,受回合预算管;
   · 阈值 0.92 直接用那篇给的经验值,并留 env 可调。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from guard_common import (hook_log, self_blocked_this_turn, is_real_user_msg,
                              load_transcript_tail, turn_budget_ok)
except Exception:
    def hook_log(*a, **k):
        pass

    def self_blocked_this_turn(*a, **k):
        return False

    def is_real_user_msg(m):
        return False

    def load_transcript_tail(tp, **k):
        return []

    def turn_budget_ok(*a, **k):
        return True

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SELF = "stagnation"
WINDOW = 3
MIN_CHARS = 200
try:
    THRESH = float(os.environ.get("SUPEREGO_STAGNATION_TH") or 0.92)
except Exception:
    THRESH = 0.92


def _embed(text, timeout=8.0):
    import urllib.request
    base = "http://127.0.0.1:17911"
    try:
        sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude"))
        from superego_port import BASE as base
    except Exception:
        pass
    b = json.dumps({"text": text[:2000]}).encode("utf-8")
    r = urllib.request.Request(base + "/embed", b, {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read())["embedding"]


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))      # 服务端已归一化


def turn_texts(msgs, n=WINDOW):
    """把 transcript 切成【每个真人回合里我说的话】,返回最近 n 段(旧→新)。"""
    turns, cur = [], []
    for m in msgs:
        if is_real_user_msg(m):
            if cur:
                turns.append("\n".join(cur))
            cur = []
            continue
        if m.get("type") != "assistant":
            continue
        c = (m.get("message") or {}).get("content")
        if isinstance(c, str):
            cur.append(c)
        else:
            for it in c or []:
                if isinstance(it, dict) and it.get("type") == "text":
                    cur.append(it.get("text") or "")
    if cur:
        turns.append("\n".join(cur))
    return [t for t in turns if len(t.strip()) >= MIN_CHARS][-n:]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if self_blocked_this_turn(SELF):
        return
    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return
    try:
        if not turn_budget_ok(tp):
            return                       # 本轮已被拽回太多次,让开(防 loop)
        msgs = load_transcript_tail(tp)
    except Exception:
        return
    segs = turn_texts(msgs)
    if len(segs) < WINDOW:
        hook_log(SELF, "pass(只有 %d 段够长的发言,不够判)" % len(segs))
        return

    try:
        vecs = [_embed(s) for s in segs]
    except Exception as e:
        hook_log(SELF, "MISS(语义服务没答上来:%s)" % type(e).__name__)
        return                           # fail-open

    sims = [_cos(vecs[i], vecs[i + 1]) for i in range(len(vecs) - 1)]
    if not sims or min(sims) < THRESH:
        hook_log(SELF, "pass(相似度 %s < %.2f)"
                 % ("/".join("%.3f" % s for s in sims), THRESH))
        return

    _sims_txt = "/".join("%.3f" % s for s in sims)
    # ⛔ shadow mode:本闸标定时【今晚 29 对最高才 0.814,阈值 0.92 触发 0 次】。
    #   但那份样本全是 Frank 在场高频纠正的轮次,证明不了没人盯时也不会打转。
    #   ⇒ 按行业做法先影子跑(只记账不拦人),抓到一次真打转、且确实该拦,再毕业。
    #   毕业方式:把 `stagnation` 从 hooks/shadow-gates.txt 里删掉。
    try:
        from guard_common import in_shadow, shadow_log
        if in_shadow(SELF):
            shadow_log(SELF, "语义停滞 %s >= %.2f" % (_sims_txt, THRESH),
                       (segs[-1] or "")[:100])
            hook_log(SELF, "SHADOW(would-block %s)" % _sims_txt)
            return
    except Exception:
        pass

    self_blocked_this_turn(SELF, mark=True)
    # ⛔ 2026-09-07 补触发词:只记相似度数字,事后看不出【我到底在重复哪句话】——
    #   而这道闸拦的正是"车轱辘话",不留原话就完全无法判断它拦得对不对。
    hook_log(SELF, "BLOCK(stagnation %s)" % _sims_txt, (segs[-1] or "")[:140])
    print(json.dumps({"decision": "block", "reason": (
        "⛔ 语义停滞闸:你最近 **%d 轮**的发言两两相似度 = %s(阈值 %.2f)——\n"
        "   **换着说法在说同一件事,实质内容没有推进。**\n"
        "⛔ 这个状态有名字:`soft loop` / `agent death spiral` ——\n"
        "   「表面上一直在工作、日志跑得热热闹闹,实际在原地反复横跳,持续烧 token。」\n"
        "   它最隐蔽的地方就是**看起来很忙**,所以只能靠机器测,人靠感觉发现不了。\n"
        "⇒ 现在【不要再在细节层面纠错】。跳出来做这三件事:\n"
        "   ① 用一句话说清:**这件事的完成标准到底是什么**(说不出 = 目标无界,这是死循环三大成因之一);\n"
        "   ② 说清**卡在哪一步、缺什么信息**——不是再解释一遍你已经解释过的;\n"
        "   ③ 换一条**和前面完全不同**的路径,或者直接说「这条路走不通」并给出原因。\n"
        "(阈值可调:SUPEREGO_STAGNATION_TH;这道闸每轮最多拦一次。)"
    ) % (len(segs), "/".join("%.3f" % s for s in sims), THRESH)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            hook_log(SELF, "error(fail-open):%s" % str(e)[:100])
        except Exception:
            pass
        sys.exit(0)
