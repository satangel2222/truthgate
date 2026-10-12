#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""范围完整性闸 —— 拦【他要的是一类，我只做了其中一个】。

⛔ 起因（2026-08-26，Frank 原话）：
   「为何你只是换 twitter，干你妈的，整个项目不换留着最好的工具不替换？」
   实录：实测出 opencli 抓 X 账号 5/5 成功、camofox 0/5，我就宣布「把 Twitter 改成
   opencli 优先」——而同一个 opencli 支持本项目 youtube / bilibili / reddit / zhihu /
   v2ex / 36kr / weibo 全部源，我一个都没提。

⛔ 这个病 2026-07-21 就写进 lessons，起名【元形状 L】：
   「把完成用户字面指的最小动作当成完成任务」，并注明「通用工作病，跨所有项目」。
   写了一个多月**从没做成闸** —— 查证：hooks 下 216 个 py 闸，管这件事的 0 个
   （唯一名字沾边的 cross-scope-guard 管的是"别跨项目乱动"，方向正好相反）。
   ⇒ 这正是同一份 lessons 的另一条：「规则写了 + 工具有 + 没有闸 = 等于没有」。

先查现成（2026-08-26，两条通道都空 ⇒ 自建）：
  · WebSearch「detect incomplete fix sibling call sites missed refactor linter」
    → 只有通用 linter（golangci-lint / oxlint）和 2019 kernel objtool，全是**静态代码分析**
  · gh search repos ×2（incomplete refactor / agent guardrail scope）→ 零结果
  ⇒ 我要判的不是代码里的同类调用点，是【对话层】：他要一类、我只覆盖一个。
    依赖 Superego 特有的 transcript 结构，无现成实现。

判据（两条同时成立才拦，宁漏勿误杀）：
  ① 用户话里有【类别信号】：整个/全部/所有/每个 + 项目/源/工具/平台…，或「N 个平台」
  ② 我的回复里有【缩小范围信号】：只换/仅改/先做一个/其余先不/剩下的以后
     且没有【全量完成信号】：全部都改完/逐个/5/5 这类全覆盖比分
⇒ 不误伤的理由：真做了全量的人不会写「只换了 X」「先做 X，其余不碰」。
  **缩小范围的措辞本身就是这个病的自白** —— 判据跟着自白走，不猜意图。
"""
import json
import os
import re
import sys

CLASS_SIGNAL = re.compile(
    r"(整个|全部|所有|每一?个|全套|通通|一律)\s*[的]?\s*"
    r"(项目|系统|源|工具|平台|地方|文件|模块|流程|渠道|账号|站)"
    r"|(三|四|五|六|七|八|九|十|\d+)\s*个\s*(平台|源|工具|站|项目|地方|模块)"
    r"|全都|都换|都改|都修|全换|全改"
)

NARROW = re.compile(
    r"(只|仅|仅仅)\s*(换|改|修|做|动|覆盖|处理|替换)"
    r"|(先|暂时|目前|这次)\s*(只|仅)?\s*(换|改|做|动)\s*(一个|一处|那个|这个)"
    r"|其余(的)?(先)?(不|暂)"
    r"|剩下的(先|暂|下次|以后)"
    r"|不(碰|动)其(他|它)"
)

FULL_DONE = re.compile(
    r"(全部|所有|逐个|一个不落|无一遗漏|统统|通通)\s*(都)?\s*"
    r"(改|换|修|做|覆盖|处理|替换|验)(完|好|了|过)"
    r"|\b(\d+)\s*/\s*\1\b"
    r"|覆盖(了)?(全部|所有|每一?个)"
)

QUOTE = re.compile(
    r"(反面例子|正面例子|比如说|举个例子|实录|原话|引述|违规示例|这道闸|本闸|判据|起因)")


def verdict(reply, user_msgs):
    """True = 该拦。⛔ 必须模块级 —— promise-gate 的教训：写成 main() 内的闭包，
    测试只能抄副本，故障注入 6/7 全『仍绿』= 测的是副本不是这道闸。"""
    try:
        from guard_common import strip_doc
        reply_clean = strip_doc(reply or "")
    except Exception:
        reply_clean = reply or ""
    if QUOTE.search(reply_clean):
        return False
    if not CLASS_SIGNAL.search("\n".join(user_msgs or [])):
        return False
    if FULL_DONE.search(reply_clean):
        return False
    return bool(NARROW.search(reply_clean))


def _read(transcript_path):
    if not transcript_path or not os.path.exists(transcript_path):
        return "", []
    rows = []
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return "", []
    reply, users = [], []
    for m in reversed(rows):
        if m.get("type") == "assistant" and not reply:
            for c in (m.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    reply.append(c.get("text") or "")
        if m.get("type") == "user" and len(users) < 3:
            c = (m.get("message") or {}).get("content")
            if isinstance(c, str):
                users.append(c)
            elif isinstance(c, list):
                for cc in c:
                    if isinstance(cc, dict) and cc.get("type") == "text":
                        users.append(cc.get("text") or "")
        if reply and len(users) >= 3:
            break
    return "\n".join(reply), users


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return
    # 2026-09-06 防无限 loop:本轮被 Stop 闸拽回次数到上限就让开。
    #   实测 55 道 Stop 闸只有 64% 受回合预算管,自己读 transcript 的 12 道全绕过。
    #   安全类闸在 _BUDGET_NEVER 里永不熔断;逃生阀 SUPEREGO_NO_BUDGET=1。
    # ⛔ 2026-09-07 修:这一段原来在 `data` 解析【之前】⇒ 每次 NameError,
    #   被下面的 `except Exception: pass` 静默吞掉 ⇒ **这道闸的熔断逃生阀从来没生效过**。
    #   而它正是 Frank 骂过的「一直让你无限 loop 做」那个形状的护栏(形状 2026-08-26-H)。
    #   典型的「加了护栏、护栏自己没接上线」——顺序错一行,功能等于不存在,而且不报错。
    try:
        from guard_common import turn_budget_ok as _tbo
        _tp = data.get("transcript_path")
        if _tp and not _tbo(_tp):
            return
    except Exception:
        pass
    reply, users = _read(data.get("transcript_path"))
    if not verdict(reply, users):
        return
    print(
        "⛔ 范围完整性闸:他要的是【一类】,你只做了【其中一个】。\n"
        "  实录 2026-08-26(Frank 原话):「为何你只是换 twitter,整个项目不换"
        "留着最好的工具不替换?」\n"
        "  —— 我实测出 opencli 在 X 上 5/5 完胜就只提换 Twitter,而同一个工具支持本项目\n"
        "     youtube/bilibili/reddit/v2ex/36kr 全部源,一个都没提。\n"
        "  ⛔ 这是 lessons 的【元形状 L】(2026-07-21 记的、一个多月没做成闸):\n"
        "     『把完成用户字面指的最小动作当成完成任务』。\n"
        "  ⇒ 把【同类的其余部分】一起做完再汇报;真有做不了的,逐个写清\n"
        "     【为什么这个不行】(实测过什么、卡在哪),而不是默默只做一个。",
        file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
