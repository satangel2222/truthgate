#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Stop 闸:【软提醒重复太多次还没解决 → 升级成硬拦】。

⛔ 起因(2026-08-26,Frank 原话):
   「是不是应该有个机制,**提醒了一定数量后没做就得 hook**?而不是纸老虎的机制?
     还有我的所有记录有没有记录日期,时间,发生了多少次?**今天里记录了多少个提醒了,却啥也没做的?
     有没有人管?** 纸老虎是不是也是自己的纸老虎?」

⛔ 当天查出来的三层真相:
   ① 12 道闸是【非阻塞提醒】(只往我上下文塞文字,我可以无视);
   ② 统计里只有 allow / block 两档 —— **「提醒了」这个状态在系统里根本不存在**;
   ③ 于是「今天提醒了几次、我照做了几次」**数不出来,也没人管**。
   ⇒ 纸老虎的准确定义不是「没跑」,是**「跑了、我可以无视、而且没人数」**。

⇒ 修法分两步(都已落地):
   第一步 `guard_common` 加第三档 `nudge`(软提醒),让它先被【数出来】;
   第二步 = 本闸:**同一道闸在同一会话里连着提醒 N 次,说明我一直没处理 ⇒ 升级成拦截。**

⛔ 判据为什么只数次数、不判「我做没做」:
   「我有没有照它说的做」需要理解语义,机器判不了。但有一条硬事实可用:
   **如果我真处理了,那道闸就不会再响。** 它连响 N 次 = 我一直没解决。
   —— 和 `hook-stats` 里那个「同一 fp 反复出现 = 误拦嫌疑」是同一个思路,方向相反。

⛔ 安全设计:
   · fail-open:读不到统计/解析失败 → 静默放行,绝不因为观测器出错拦住他。
   · 只数【当前会话】(sid),跨会话不累计 —— 昨天的提醒不该今天拦我。
   · 只数【最近 N 分钟】,避免一个长会话里早已解决的旧账被翻出来。
   · 自己拦过一次就不再拦(per-gate 标记),防死循环。
   · 排除自己,免得自指。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from guard_common import hook_log, self_blocked_this_turn
except Exception:
    def hook_log(*a, **k):
        pass

    def self_blocked_this_turn(*a, **k):
        return True          # 拿不到共享层 = 退回"别拦",安全侧

# ⛔ 必须跟 guard_common 记账时用的目录【同一个】—— 它写的是
#   `os.environ.get("SUPEREGO_LOG_DIR") or 脚本所在目录`。
#   第一版这里写死 HERE ⇒ 一旦那个环境变量被设过,**写在一个地方、读在另一个地方**
#   ⇒ 这道闸永远读不到数据、永远不开火(端到端回归当场抓到,3 条全 False)。
#   这就是形状 T「新闸出生即死」:判据没错,接线错了,而只跑内部函数的用例全绿。
def _stats_path():
    d = os.environ.get("SUPEREGO_LOG_DIR") or HERE
    return os.path.join(d, "hook-stats.jsonl")


STATS = _stats_path()
# ⛔ 2026-09-06 Frank 亲口把阈值定死:「**不应该 2 次不听劝就真 hook 吗?**」
#   原值 3 是我自己拍的。当天实证他为什么要 2:`tool-roster-gate` 同一件事连提醒 4 次、
#   `antiscrape-invoke-gate` 连提醒 3 次 —— 都是【软提醒】,我每次都回应、每次都没根治,
#   **把他的 token 烧在同一个循环里**。第 3 次才拦,前两次的浪费已经发生了。
THRESHOLD = 2          # 同一道闸连着提醒几次算"一直没解决"
WINDOW_MIN = 90        # 只看最近多少分钟(旧账不翻)
# ⛔ 全局兜底上限:本闸自己在同一会话最多拦这么多次,之后彻底闭嘴。
#   照抄 `concise-answer-gate` 的 MAX_BLOCKS 模式。**宁可漏拦,绝不锁死他**
#   —— Frank 2026-08-26:「硬拦也有副作用,agent 完全什么都不做,或者 think loop 里」。
#   本闸是【二次拦截】(拦的是已经被提醒过的事),比一般闸更该保守,所以取 2 不是 3。
MAX_BLOCKS = 2


def io_read(p):
    """读一个小文件,读不到就返回空串(绝不抛)。"""
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except Exception:
        return ""
SELF = "nudge-escalation-gate"
# 每轮都注入、天生会重复的,不算"我没做"(它们不是冲我来的)
EXEMPT = {"progress-inject", "superego-recall-inject", "dissatisfaction-postmortem",
          "session-context-inject", "host-machine-archive-first", SELF,
          # ⛔ 2026-09-10 把 10 道没记账的软闸接进账本时加的两条:这两道是【对环境的观察】
          #   (抓取回了 timeout / 管道里有 head|tail 可能截断),我照不照做它都会响 ——
          #   一轮响几十次,不豁免的话本闸第 2 次就拦我,而我没有任何"处理"能让它停。
          #   判据:能通过【照做】让它不再响的才数;做什么都照响的是信息,不是提醒。
          "anti-scraping-response-detector", "pipe-truncation-guard",
          # 2026-09-11:提问型的闸(整合三问)按改动文件数每过一截就再问一次、自己写着「不阻塞」——
          #   它没有「已处理」这个状态,数它的次数只会制造假升级(当天它问 3 次、我答 3 次,升级闸照样拦)。
          #   Frank 同日原话:「为何那么慢是不是superego过度设计导致很多重复和无限循环bug？」
          "coherence-guard"}


BURST_SEC = 3           # 同一道闸 3 秒内的多次提醒 = 同一阵(一次并行发出的几个 Edit 各触发一遍)


def _stat_lines(path):
    """当前账本 + 轮转前的 .1(轮转会把 90 分钟窗口拦腰截断)。"""
    for p in (path + ".1", path):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                yield from f
        except Exception:
            continue


def count_nudges(sid, now=None, path=None):
    """返回 {闸名: 次数} —— 只算当前会话、最近 WINDOW_MIN 分钟内的 nudge。

    ⛔ 2026-09-16(Frank 问「这是 superego 的 bug 吗」,查实是):lint-fatal-guard 18:24:37/38
       两条提醒来自【同一次并行发出的两个 Edit】、同一个 F821,被数成 2 次 ⇒ 18:34 误升级。
       ⇒ 同一闸一阵连发(以这一阵的【第一条】为锚,BURST_SEC 内)只算一次。锚定而非滑动:
         滑动窗口会把每 8 秒一次、持续 10 分钟的真提醒串成 1 次(外审实测 75 条 → 1)。
    ⛔ 同日试过「之后出现 allow 就清零」—— 外审用 6 小时真账本否掉:工具调用型闸在【无关文件】上
       也记 allow,48 对提醒里 33 对会被清零,regress-on-guard-edit 的真阳性 15/15 被放掉。别再加回来,
       除非 hook-stats 记了对象指纹、能按"同一件事"清零。
    """
    now = now or time.time()
    out, anchor = {}, {}
    try:
        for ln in _stat_lines(path or STATS):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            if d.get("r") != "nudge":
                continue
            if sid and d.get("s") != sid:
                continue
            g = str(d.get("g") or "")
            if not g or g in EXEMPT:
                continue
            try:
                ts = time.mktime(time.strptime(str(d.get("t")), "%Y-%m-%d %H:%M:%S"))
            except Exception:
                continue                     # 时间坏了 ⇒ 判不了窗口 ⇒ 不算(fail-open)
            if now - ts > WINDOW_MIN * 60:
                continue
            if g in anchor and 0 <= ts - anchor[g] <= BURST_SEC:
                continue                     # 同一阵连发,不重复计;锚点不动
            anchor[g] = ts
            out[g] = out.get(g, 0) + 1
    except Exception:
        return {}
    return out


def main():
    data = json.loads(sys.stdin.read())
    if not data.get("stop_hook_active"):
        self_blocked_this_turn(SELF, turn_start=True)
    elif self_blocked_this_turn(SELF):
        hook_log(SELF, "skip(self-blocked-this-turn)")
        return
    sid = (os.environ.get("CLAUDE_CODE_SESSION_ID") or data.get("session_id") or "-")[:8]
    hot = {g: n for g, n in count_nudges(sid).items() if n >= THRESHOLD}
    if not hot:
        hook_log(SELF, "allow(no-hot-nudge)")
        return

    # ⛔⛔⛔ 双保险,防死循环(Frank 2026-08-26 亲口提醒:
    #   「硬拦也有副作用,就是 agent 完全什么都不做,或者 think loop 里,这个之前有修过,避免再发生」)
    # ⛔ 我原来只靠 `self_blocked_this_turn`,而 SUPEREGO.md 第 16 行明写它**挡不住**:
    #   7-29 实录 **一分钟 63 次、4 分钟 136 次**风暴 —— 标记在回合边界被清掉,
    #   而子实例的完成通知会重置回合边界 ⇒ 清标记 ⇒ 再拦 ⇒ 再派。
    # ⛔ 更要命的是本闸【自己的设计缺陷】:nudge 计数窗口 %d 分钟,
    #   **我就算真处理完了,那些旧的 nudge 记录还在窗口里** ⇒ 它会一直拦我 ⇒ 永远出不去。
    # ⇒ 照抄两个现成模式,不重造:
    #   ① `churn-guard`:**同一个对象只拦一次,绝不锁死**(这里=同一道闸每会话只升级一次)
    #   ② `concise-answer-gate` 的 MAX_BLOCKS:**连拦 N 次后自动放行**(全局兜底)
    _mark_dir = os.environ.get("SUPEREGO_LOG_DIR") or HERE
    fresh = []
    for g in list(hot):
        p = os.path.join(_mark_dir, ".escalated-%s-%s" % (g.replace(os.sep, "_"), sid))
        if os.path.exists(p):
            continue                       # 这道闸本会话已经升级过 ⇒ 不再拦(绝不锁死)
        fresh.append(g)
    if not fresh:
        hook_log(SELF, "allow(all-already-escalated)")
        return
    # 全局兜底:本闸自己拦满 MAX_BLOCKS 次就彻底闭嘴,宁可漏拦也不锁死他
    _cnt_p = os.path.join(_mark_dir, ".escalation-count-%s" % sid)
    try:
        _cnt = int(io_read(_cnt_p) or "0")
    except Exception:
        _cnt = 0
    if _cnt >= MAX_BLOCKS:
        hook_log(SELF, "allow(max-blocks-%d-reached)" % MAX_BLOCKS)
        return
    for g in fresh:                        # 落标记:这几道闸本会话不再升级
        try:
            open(os.path.join(_mark_dir, ".escalated-%s-%s"
                              % (g.replace(os.sep, "_"), sid)), "w").close()
        except Exception:
            pass
    try:
        with open(_cnt_p, "w") as _f:
            _f.write(str(_cnt + 1))
    except Exception:
        pass
    hot = {g: hot[g] for g in fresh}
    top = sorted(hot.items(), key=lambda x: -x[1])
    lines = "\n".join("   · %-30s 已提醒 **%d** 次" % (g, n) for g, n in top[:5])
    # ⛔ 2026-09-07:触发词挪到第三个参数。实测这道闸 359 次开火【100% 无证据】—— 全仓最狠的一个,
    #   而它拦的是"同一道闸一直提醒你" ⇒ 不留下是哪几道闸,这 359 次事后完全没法复核。
    hook_log(SELF, "BLOCK(nudge-repeated)", ",".join("%s=%d" % (g, n) for g, n in top[:5]))
    print(json.dumps({"decision": "block", "reason": (
        "⛔ 软提醒重复闸:下面这些闸在**这一段对话里**已经提醒你多次,而它们还在响 ——\n"
        "%s\n"
        "⛔ 判据很硬:**如果你真处理了,它就不会再响。** 连响 %d 次 = 一直没解决。\n"
        "⛔ 这正是 Frank 2026-08-26 问的那件事:「提醒了一定数量后没做就得 hook,"
        "而不是纸老虎的机制」——在此之前,「提醒了」这个状态在统计里根本不存在,没人数得出来。\n"
        "⇒ 现在二选一,别再往下走:\n"
        "   ① 真去处理它说的那件事(处理完它自然不再响);\n"
        "   ② 它确实误伤 —— 那就**说清楚为什么**(哪一条判据错了),这句话会留在 log 里当证据。"
    ) % (lines, THRESHOLD)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            hook_log(SELF, "error(fail-open):%s" % str(e)[:100])
        except Exception:
            pass
