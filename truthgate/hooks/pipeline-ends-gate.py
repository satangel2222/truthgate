#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline-ends-gate —— 我自称画了「端到端/全流程」，但两头没接上业务时拦下。

⛔ 来历（2026-08-19，manju）：
   Frank 让我梳理**端到端流水线**。我扫了 `novel/*.py` 抓出 11 个脚本，
   排成一张表交上去 —— 从「拆章」到「生成视频」，还标了每步用哪个模型、走哪条路由。
   Frank：「什么是完整流水线端到端工作流，你确定是这样，**拆章前**？
           还有**做完视频后的所有**你懂吗？」

   他是对的。真正的链是：
     选赛道 → 找 IP → 版权 → 拿原文 → [我做的那段] → 杀青 → 封面 → 标题
     → **发布到平台** → 数据回收 → 反哺选题
   我交的是**中间一段，而且是唯一不直接产生收入的那一段**。

⛔ 病根（lessons 形状 2026-08-19-L）：
   **我梳理"全流程"时，边界是从我的代码目录长出来的，不是从业务目标长出来的。**
   扫到 11 个脚本 ⇒ 流水线就等于这 11 个脚本；
   **没有脚本的环节，在我视野里根本不存在** —— 不是"知道但没做"，是"压根没想起来"。
   与同日形状 I 同源：那条是【验收清单】从"我改了什么"长出来，
   这条是【流程图】从"我写了什么"长出来。合起来：**我用自己的产出定义"应该有什么"**。

⛔ 先查现成（2026-08-19）→ 判定 **自建**：
   本机 60+ 个 hook 里，管承诺(promise-gate)、管放弃(giveup-guard)、
   管甩锅(blame-check)、管搜索层次(search-layer-gate) 的都有，
   **没有一个管「你画的流程是否接到了业务两头」**。

⛔ 判据（客观、纯文本，不需要理解业务）：
   ① 我自称「端到端 / 全流程 / 完整流水线 / 全链路 / 整条链路 / pipeline」
   ② 且确实在描述一个多步骤流程（表格行或编号项 >= 4）
   ③ 而同一段输出里**缺上游词或缺下游词**
   ⇒ 提示（不硬拦，因为有时确实只讨论中间某段，那时说明一句即可）

自测：python pipeline-ends-gate.py --self-test
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


CLAIM = re.compile(r'端到端|全流程|完整.{0,4}流水线|全链路|整条链路|端到尾|pipeline', re.I)

# 上游：这条链的第一个输入从哪来、谁决定要做
UPSTREAM = re.compile(
    r'选题|选赛道|立项|需求来源|从哪来|采购|版权|授权|IP\b|客户|甲方|市场调研|'
    r'原始素材|数据源头|谁提出|为什么做这个')
# 下游：最后的产出给谁、怎么变成钱或结果
DOWNSTREAM = re.compile(
    r'发布|上线|投放|交付|变现|收入|营收|观众|读者|用户拿到|平台|分发|'
    r'上架|推送给|复盘|数据回收|反哺|转化')

STEPY = re.compile(r'^\s*(\|.*\|.*\||[-*]\s|\d+[.、)]\s)', re.M)

MSG = """⚠️ 流程两头闸：你自称画了一条【{claim}】，但这段输出里{miss}。

⛔ 2026-08-19 实录：Frank 让我梳理端到端流水线，我扫了目录抓出 11 个脚本排成表就交了 ——
   从「拆章」到「生成视频」。他一句话戳穿：「**拆章前**？还有**做完视频后的所有**你懂吗？」
   我交的是**中间一段，而且是唯一不直接产生收入的那一段**。
   病根：**流程边界是从我的代码目录长出来的，不是从业务目标长出来的** ——
   没写代码的环节，在我视野里压根不存在。

⇒ 交之前先只答两个问题：
   ① **最上游**：这条链的第一个输入从哪来？谁决定要做这个？
      （选题 / 立项 / 需求 / 采购 / 版权 / 客户）
   ② **最下游**：最后一个产出给谁？怎么变成钱或结果？
      （发布 / 上线 / 交付 / 变现 / 观众 / 复盘）

⇒ 更锋利的自检：**这条链上哪几步是我做的？如果全都是，它一定不完整** ——
   真实业务链条不可能全部落在一个人的仓库里，总有人工、外部平台、钱、决策。

（若这次确实只讨论中间某一段，把话说明白即可：写「这是其中的 X→Y 段，
  上游的 A 和下游的 B 不在本次范围」，而不是管它叫"端到端"。）"""


def check(text):
    """返回提示语；不该提示返回 None。"""
    if not text or not CLAIM.search(text):
        return None
    if len(STEPY.findall(text)) < 4:      # 不是在描述多步骤流程
        return None
    miss = []
    if not UPSTREAM.search(text):
        miss.append('**没有任何一步说清最上游从哪来**（选题/立项/需求/版权/客户）')
    if not DOWNSTREAM.search(text):
        miss.append('**没有任何一步说清最下游给谁、怎么变现**（发布/上线/交付/观众）')
    if not miss:
        return None
    claim = CLAIM.search(text).group(0)
    return MSG.format(claim=claim, miss='：\n   · ' + '\n   · '.join(miss))


# 第一条 = 2026-08-19 我真实交出去的那张表（缩写版）
SELF_TESTS = [
    ("""这是端到端流水线：
| 环节 | 脚本 | 模型 |
| 拆章 | beat_split.py | agnes |
| 剧本 | write_screenplay.py | agnes |
| 选角 | gen_character_sheets.py | agnes-image |
| 分场 | gen_storyboard.py | agnes |
| 立版 | gen_shot_keyframe.py | nano banana |
| 开机 | gen_shot_video.py | runninghub |
""", True),
    # 补齐两头 -> 放行
    ("""端到端流水线：
- 选题：先定赛道，查哪个题材能变现
- 找 IP 拿版权
- 拆章 / 剧本 / 分场 / 立版 / 开机
- 杀青拼接
- 发布到平台，回收数据反哺选题
""", False),
    # 只有上游、缺下游 -> 拦
    ("""完整流水线：
1. 选题立项
2. 拆章
3. 写剧本
4. 生成视频
""", True),
    # 只有下游、缺上游 -> 拦
    ("""全链路：
1. 拆章
2. 剧本
3. 出片
4. 发布到平台变现
""", True),
    # 没自称端到端 -> 不管
    ("""我改了三个地方：
1. 场景板加菜
2. 编辑链缩短
3. 睁眼规则
""", False),
    # 自称了但不是多步骤流程 -> 不管
    ("这条端到端跑通了，耗时 12 分钟。", False),
]


def self_test():
    bad = 0
    for txt, want in SELF_TESTS:
        got = check(txt) is not None
        if got != want:
            bad += 1
        print('%s 应提示=%-5s 实提示=%-5s | %s'
              % ('OK ' if got == want else 'XX ', want, got,
                 txt.strip().splitlines()[0][:52]))
    print('\n%d/%d 通过' % (len(SELF_TESTS) - bad, len(SELF_TESTS)))
    return 1 if bad else 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    text = ''
    for k in ('assistant_message', 'message', 'text', 'output'):
        v = data.get(k)
        if isinstance(v, str):
            text += '\n' + v
    hit = check(text)
    if hit:
        print(hit, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
