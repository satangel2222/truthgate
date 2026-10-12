#!/usr/bin/env python3
r"""Stop 闸:用户一条消息里问了很多件事 → 收尾前把【他问的每一条】列回我面前,逼我自查漏没漏。

⛔ 2026-08-14 起因(Frank 第 N 次抓到):
   他一条消息里连问了十几件事(完整列系统 / 拆工作流 / 每个功能干什么 / 帮到还是帮倒忙 /
   准确度 / 用什么模型 / 是不是 SOTA / 跨项目通用 / **冗余** / 前中后覆盖 / 尺准不准 /
   污染 / 拦了不做的根因 / PROGRESS 结构冲突 / 资源前提醒 / 资源后回看 …)。
   我答了其中十来条,**漏掉「每道闸具体干什么」和「冗余分析」两大块,而且没说我漏了**。
   他:「列出所有问题啊,那些需要优化,那些需要重构,我刚才说的东西逐个你都有给我去研究嘛?」

⇒ 形状(形状 I 家族·lessons 已第 23 次):**多问清单我只答擅长的几条,没答的既不做、也不标出来。**
   最毒的地方和"失忆"那条一样:**我的回答看起来很完整**(长、有数据、有表格),
   所以我自己不会怀疑漏了 —— 只有把他原话拆开逐条摆出来,缺口才现形。

机器判据(完全客观,不需要理解语义):数他这条消息里有几个【独立问句/诉求】。
   ≥5 个就在收尾时把清单摆回我面前,拦一次。**本闸不判断我答没答**(那是语义、判不准,
   判不准的闸会变噪音、两周后被我略读),只保证【原话逐条摆在我眼前】,
   让我没法用"我以为答完了"蒙混过去。

⛔ 先查现成(2026-08-14 按铁律执行):
   · WebSearch:学术界有覆盖率指标(CovGT)、多智能体测试框架(FLARE),但**都是离线评测**,
     不是能挂进 Stop hook 的东西
   · `gh search repos` 三组关键词(multi question answer coverage / decompose subquestions
     completeness / claude code hook response completeness)**全部零结果**
   ⇒ **判定:只能自建**,零依赖薄壳。

安全:同一条消息只拦一次(按内容哈希记,24h 过期);<5 问不管;拿不到 transcript 静默放行;
     stop_hook_active 直接放行;任何异常 fail-open。
"""
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_common as _gc          # noqa: F401 —— 只为接进「闸的分母」统计(hook-stats.jsonl)
except Exception:
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, ".ask-coverage-seen.json")
MIN_ASKS = 5

# 中文问句/诉求的识别。三类任一命中就算一个诉求。
# ⛔ 2026-08-14 回归当场抓到:第一版只认【语气词 + 祈使动词】,漏掉中文最常用的疑问结构 ——
#   「有没有…」「是不是…」「怎么…」「为何…」「哪些…」。后果:Frank 那条真消息里
#   「拿来复用的**有没有**沉余的东西」和「所有东西**是不是**都分前中后」被整条丢掉,
#   **而那两条正是我当时真的漏答的**。闸要是这么装上去,等于精准放过它该抓的那一条。
#   (教训形状:识别器按【我脑子里的问句长什么样】写,没按【中文实际怎么问】写。)
Q_MARK = re.compile(r"[吗呢嘛]|有没有|是不是|有无|怎么|怎样|如何|为何|为什么|哪些|那些|多少|几个"
                    # 2026-09-06 补:反问式诉求整类漏掉。实测 Frank 一条真消息里
                    # 「你不测试」「你都还没有真正应用」「你也没有去检查」三条识别不出,
                    # 被下面的"粘回上一条"吞掉 => 诉求数 7+ 塌成 3 < 门槛 5 => 整道闸放行。
                    r"|你不|你都不|你也不|你没|你也没|你都没|还没有|都还没|没有去")
IMPERATIVE = re.compile(r"(给我|列出|列个|拆解|审查|检查|优化|重构|研究|分析|对比|统计|证明|修正|解决)")
# 以人称代词开头 = 一件新的事(而不是上一条枚举的后半截)。配合下面 split_asks 里的"不许粘回"用。
NEW_CLAUSE = re.compile(r"^(你|我|他|她|它|咱|大家)")


def split_asks(text):
    """把一整条消息切成【独立诉求】。切分点用中文里真实的并列信号,不是随便按标点切。"""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return []
    # ⛔ 2026-08-14 回归当场抓到:第一版只切「?。;」和并列词,对那条真实消息只拆出 4 条(实际十几条)。
    #   根因:**Frank 写的是用「,」串起来的长句**,不是一句一问。
    #   ⇒ 逗号也必须算切分点;过噪音靠后面那道「必须含 吗/呢/嘛 或 祈使动词」的过滤器挡,不靠切得保守。
    #   (教训形状:尺子按【我以为用户怎么写】设计,而不是按【他真的怎么写】—— 用真实语料测才现形。)
    parts = re.split(r"[?？!！。；;，,、]\s*|\s*(?:还有|以及|另外|其次|再来|而且|同时)\s*", t)
    # ⛔ 2026-08-14 回归抓到第三个问题:按逗号切会把【枚举】切碎。
    #   实录:他写「所有东西是不是都分前,中,后三种拦截」→ 切成
    #   `所有东西是不是都分前` / `中` / `后三种拦截`,后两截都 <6 字被丢掉,
    #   清单里只剩半句"…都分前",**关键词『拦截』整个消失**,我照着清单也看不出他在问什么。
    #   ⇒ 短碎片不丢弃,**粘回上一条**。这样枚举保持完整、清单才读得懂。
    asks = []
    for p in parts:
        p = p.strip(" ,，、")
        if not p:
            continue
        # 2026-09-06:以「你/我/他」开头的片段是【新的一件事】,不是枚举后半截 —— 不许粘回去。
        # 原来无条件粘回,把「你不测试」「你也没有去检查」这类独立诉求糊进上一条,计数被压到门槛以下。
        new_clause = bool(NEW_CLAUSE.match(p)) and (Q_MARK.search(p) or IMPERATIVE.search(p))
        if len(p) < 6 and not new_clause:
            if asks:
                asks[-1] = asks[-1] + "," + p     # 枚举的后半截,接回去
            continue
        if Q_MARK.search(p) or IMPERATIVE.search(p):
            asks.append(p)
        elif asks and len(p) < 14:
            asks[-1] = asks[-1] + "," + p         # 不成句的补语,也接回去别丢
    out, seen = [], set()
    for a in asks:                       # 去重:同一诉求被重复问不重复计数
        k = a[:24]
        if k in seen:
            continue
        seen.add(k)
        out.append(a)
    return out


def last_user_prompt(tp):
    """从 transcript 取【最后一条真实用户消息】。
    ⛔ 必须跳过 hook 注入的 system-reminder —— 否则数到的是闸自己的文字,
      那才是真正的自欺:拿我自己的输出当用户的输入(2026-07-28 授权来源铁律同源)。"""
    if not tp or not os.path.exists(tp):
        return ""
    rows = []
    try:
        with open(tp, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "user":
                    continue
                c = (d.get("message") or {}).get("content")
                if isinstance(c, list):
                    c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                if not isinstance(c, str) or not c.strip():
                    continue
                if "<system-reminder>" in c or c.startswith("Caveat:"):
                    continue
                rows.append(c)
    except Exception:
        return ""
    return rows[-1] if rows else ""


def main():
    data = json.loads(sys.stdin.read() or "{}")
    if data.get("stop_hook_active"):
        return
    # 2026-09-06 防无限 loop:本轮被 Stop 闸拽回次数到上限就让开。
    #   实测 55 道 Stop 闸只有 64% 受回合预算管,自己读 transcript 的 12 道全绕过。
    #   安全类闸在 _BUDGET_NEVER 里永不熔断;逃生阀 SUPEREGO_NO_BUDGET=1。
    try:
        from guard_common import turn_budget_ok as _tbo
        _tp = data.get("transcript_path")
        if _tp and not _tbo(_tp):
            return
    except Exception:
        pass
    prompt = last_user_prompt(data.get("transcript_path"))
    if not prompt:
        return
    asks = split_asks(prompt)
    if len(asks) < MIN_ASKS:
        return

    key = hashlib.sha1(prompt.strip().encode("utf-8")).hexdigest()[:16]
    st = {}
    try:
        with open(SEEN, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    now = int(time.time())
    st = {k: v for k, v in st.items() if now - v < 86400}
    if key in st:
        return                      # 这条消息已经拦过一次,放行
    st[key] = now
    try:
        with open(SEEN, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception:
        pass

    lines = "\n".join("  %2d. %s" % (i + 1, a[:88]) for i, a in enumerate(asks[:20]))
    print(
        "⛔ 逐条覆盖闸:他这一条消息里有 **%d 个独立诉求**,原话拆开如下 ——\n%s\n"
        "⇒ **逐条对照你刚写的回答**:哪几条答了、哪几条【一个字没提】?\n"
        "   · 答了的 → 一句话点名它在哪答的\n"
        "   · 没答的 → **现在就去做**(能做的一律直接做完,别列成待办丢回去)\n"
        "   · 真做不了的 → 明说是哪条边界,别装作没这一问\n"
        "⛔ 2026-08-14 实录:他一条消息问了十几件,我答了十来条、**漏掉「每道闸具体干什么」和\n"
        "   「冗余分析」两大块,而且没说我漏了**。最毒的是**我的回答看起来很完整**(长、有数据、\n"
        "   有表格),所以我自己根本不会怀疑漏了 —— 只有把他原话拆开摆出来,缺口才现形。\n"
        "   形状 I 家族,lessons 里已第 23 次。\n"
        "⇒ 本闸只摆清单、不判对错(那是语义、判不准),同一条消息只拦这一次。"
        % (len(asks), lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass        # fail-open:绝不因为一道提醒闸挡死正常收尾
