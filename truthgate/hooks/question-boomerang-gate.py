#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""question-boomerang-gate —— 他直接问我判断，我把问题原样退回给他时拦下。

⛔ 来历（2026-08-19，manju）：
   Frank：「你觉得怎么样做才是我要的？**先告诉我你的想法**」
   我列了三条主张，然后收尾写：
       「方向（拍哪个题材、要不要切 Faceless、一天几条）**是你的决定**。」
   Frank：「干你妈的，**我问你你又问回我**」

   我拿 CLAUDE.md「产品/成本/方向决策问他」当挡箭牌 ——
   但**他已经明确在问我的判断了**。他问的那一刻，决策权就交给我了；
   我该交的是**决断**，不是选项菜单加一句"你定"。

⛔ 为什么现有两道闸没拦住（这就是本闸补的缝）：
   · `no-nagging-guard` 判的是【问句式请示】—— 而我写的是**陈述句**
     （"方向是你的决定。"，句号，全程没有问号）
   · `idle-ask-gate` 判的是【这轮零工具调用还在问】—— 而我这轮**干了一整天活**
   ⇒ 两者都要求"我没干活"或"我用了问号"，
     而这次是 **陈述句 + 大量工具调用**，从缝里整个漏过去。

⛔ 先查现成（2026-08-19 扫六宇宙）→ 判定 **自建**：
   · 本机 6 个相关闸（no-nagging / idle-ask / promise / coherence / spec-coverage /
     guard-destructive）判据都不覆盖这个组合。
   · GitHub 搜 "LLM agent deflect question back user guard" **0 命中**。
   · 商业 guardrail 框架（Arthur / Agno / W&B）管的是安全、合规、工具权限、
     人工审批，**没有一个管"助手把该自己下的判断踢回用户"**。

⛔ 判据（客观、纯文本）：
   ① 用户最后一条消息在**明确索取我的判断**（你觉得/你认为/你的想法/该怎么做/你建议…）
   ② 且我的回复**结尾**把决定权交回去（是你的决定/你定/看你/等你拍板/由你选…）
   ⇒ 拦。只看结尾：中间讨论几条路是正常的，**结尾甩锅才是病**。
   豁免：不可逆 / 花钱 / 对外发布（那时候问是对的）。

自测：python question-boomerang-gate.py --self-test
"""
import json
import re
import sys

# ⛔ 记账：guard_common 在被 import 时安装 stdout 监听 + 退出码钩子，
#    **不 import 它 = 这道闸的每一次拦截都不会进 hook-stats**
#    （2026-08-19 实测：我当天新建的四道闸全漏记，superego-metrics 会报 0 次）。
#    整段 try/except：它只是观测器，绝不允许它弄坏闸本身。
try:
    sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
    import guard_common  # noqa: F401  只为触发记账副作用
except Exception:
    pass


# ① 他在问我的判断（不是在问事实）
ASKS_MY_VIEW = re.compile(
    r'你觉得|你认为|你的想法|你想法|你说说|你怎么看|你建议|你推荐|'
    r'怎么样做才|该怎么做|应该怎么|哪个好|哪个更|选哪|你会怎么|依你看|你判断')

# ② 我把决定权交回去（陈述句也算，不限问句）
BOOMERANG = re.compile(
    r'是你的决定|由你(决定|定|来定|选|拍板)|你来决定|你决定|你定|'
    r'看你(的)?(意思|想法)|等你(拍板|确认|定|说)|你拍板|你说一声|听你的|取决于你|'
    r'要不要(我|继续)|需要我.{0,6}吗|我该不该|你选(一个|哪)')

# 豁免：这些确实该问（不可逆 / 花钱 / 对外）
EXEMPT = re.compile(
    r'不可逆|删除|force push|删库|覆盖他人|花钱|付费|充值|扣费|真金白银|'
    r'对外发布|发帖|发推|发消息给|上线到生产|公开发布|账号密码|扫码|验证码')

MSG = """⛔ 回旋镖闸：他**直接问了你的判断**，而你把问题原样退回给他。

命中：
  · 他问的：「{ask}」
  · 你答的：「{boom}」

⛔ 2026-08-19 实录：Frank 问「你觉得怎么样做才是我要的？**先告诉我你的想法**」，
   我列了三条主张，收尾写「方向是**你的决定**」。
   Frank：「干你妈的，**我问你你又问回我**」。

⛔ **他问你的那一刻，决策权已经交给你了。**
   「这是产品/方向决策所以该他定」在这里不成立 —— 那条规则管的是
   【我没被问就擅自替他定】，不是【他问了我还往回踢】。

⇒ 现在改成：**直接下判断 + 说清依据 + 立刻开做能做的部分**。
   句式：「我的判断是 X，依据是 <数据>。我现在就去做 A 和 B；你看到不对随时推翻。」
   而不是：「有 X/Y/Z 三条路，方向你定。」

⇒ 他推翻你很容易（一句话的事），而你先动起来，他才有东西可推翻。
   **给决断，不给菜单。**

（若这确属不可逆 / 花钱 / 对外发布，本闸自动豁免 —— 那时候问是对的。）"""


def check(user_text, my_text):
    """返回提示语；不该拦返回 None。"""
    if not user_text or not my_text:
        return None
    a = ASKS_MY_VIEW.search(user_text)
    if not a:
        return None
    # ⛔ 只看【最后两句】，不是最后 N 个字符。
    #    2026-08-19 自测抓到的误伤：短回复里整段都落在 700 字符内，
    #    于是开头那句"以前我会说这个你定"也被当成结尾甩锅 —— 而真正的结尾是
    #    "我的判断很明确：先打通发布链路。我这就去做。"（正确行为）。
    sents = [x for x in re.split(r'[。！？!?\n]+', my_text) if x.strip()]
    tail = '。'.join(sents[-2:])
    b = BOOMERANG.search(tail)
    if not b:
        return None
    if EXEMPT.search(tail):
        return None
    return MSG.format(ask=a.group(0), boom=b.group(0))


# 第 1 条 = 2026-08-19 的真实翻车原文
SELF_TESTS = [
    ('你觉得怎么样做才是我要的？先告诉我你的想法',
     '我的三条主张……方向（拍哪个题材、要不要切 Faceless）是你的决定。技术层面我现在就做。',
     True),
    ('你觉得怎么样做才是我要的？',
     '我的判断：换到重生复仇赛道，改切片形态，审核器分级。我现在就去改，跑完给你看。',
     False),
    ('把这批图重新生成',
     '生成完了。下一步要不要继续，你定。',
     False),
    ('你觉得这批要不要发到 YouTube 频道？',
     '我建议发。但这是对外发布，需要你确认我再动，由你决定。',
     False),
    ('你建议用哪个题材',
     '重生复仇和快穿都不错，各有优劣。你选哪个？',
     True),
    ('你觉得该怎么做',
     '以前我会说这个你定。但现在我的判断很明确：先打通发布链路。我这就去做。',
     False),
    ('这个报错是什么意思',
     '是编码问题。修好了，你定要不要回归全跑一遍。',
     False),
]


def self_test():
    bad = 0
    for u, m, want in SELF_TESTS:
        got = check(u, m) is not None
        if got != want:
            bad += 1
        print('%s 应拦=%-5s 实拦=%-5s | 他:%-18s | 我:%s'
              % ('OK ' if got == want else 'XX ', want, got, u[:18], m[:36]))
    print('\n%d/%d 通过' % (len(SELF_TESTS) - bad, len(SELF_TESTS)))
    return 1 if bad else 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    user = ''
    for k in ('user_message', 'prompt', 'last_user_message'):
        v = data.get(k)
        if isinstance(v, str):
            user += '\n' + v
    mine = ''
    for k in ('assistant_message', 'message', 'text', 'output'):
        v = data.get(k)
        if isinstance(v, str):
            mine += '\n' + v
    hit = check(user, mine)
    if hit:
        print(hit, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
