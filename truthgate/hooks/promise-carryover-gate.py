#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""promise-carryover-gate —— 跨轮承诺对账：我上一轮说要做的，这一轮做了吗？

⛔ 来历（2026-08-19，Frank：「每次给完结论后就停止了，为何 superego 没开火，坏了吗？」）：

   查了当天真实计量（60 轮）：Superego **没坏** ——
   no-nagging 拦 7 次、critic 拦 6 次、visual-proof 拦 5 次，我一整天都在被拦。
   但它拦不住这个病，原因是结构性的：

   **所有闸都是「拦」，没有一个是「推」。**
   闸只检查「我这一轮做对没有」，**没有任何东西检查「我上一轮说要做的做了没有」**。

   实际发生的循环：
     第 N 轮：给结论 + 「我这就去查 X」 → 本轮合法结束
     第 N+1 轮：他换了话题 → 我跟着走 → **X 永远没人查**

   `promise-gate` 本该管，但两个洞：
     ① 它**只在同一轮内**检查（写了编号清单又没动手才拦）
     ② 它开头就 `if data.get("stop_hook_active"): return` ——
        **只要这一轮被别的闸拦过一次，它就跳过**。
        实测：60 轮里它只跑了 27 轮，跳过的 33 轮正是「被拦后补救」的高风险轮次。

⛔ 先查现成（2026-08-19）→ 判定 **自建**：
   本机 hooks 里 promise-gate 只写日志、无任何落盘状态，没有跨轮记忆。
   外部只有论文（arXiv 2606.04990 evidence tracing / execution provenance），无可用实现。
   而那篇论文恰好给了理论依据：
     "Promises, obligations, responsibilities do not persist like physical objects;
      they must be sustained through **witnessing, remembering, and testifying**."

⛔ 设计要点（为什么不硬拦）：
   用户换话题是**合法**的 —— 那时该把承诺记成「欠账」，不是追着我不放。
   所以：每轮记账，欠账累积到 THRESHOLD 条才拦一次，逼我清账。
   这样换话题不被打扰，而「说了就忘」会累积成一次强制对账。

自测：python promise-carryover-gate.py --self-test
"""
import json
import os
import re
import sys
from pathlib import Path

# ⛔ 记账：guard_common 在被 import 时安装 stdout 监听 + 退出码钩子，
#    **不 import 它 = 这道闸的每一次拦截都不会进 hook-stats**
#    （2026-08-19 实测：我当天新建的四道闸全漏记，superego-metrics 会报 0 次）。
#    整段 try/except：它只是观测器，绝不允许它弄坏闸本身。
try:
    sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
    import guard_common  # noqa: F401  只为触发记账副作用
except Exception:
    pass


STATE = Path.home() / '.claude' / 'hooks' / '.promise-carryover.json'
THRESHOLD = 3          # 欠账攒到几条才拦
KEEP = 12              # 最多留几条，防无限膨胀

# 我说「接下来要做」的句式（散文式，promise-gate 的编号清单判据抓不到）
VOW = re.compile(
    # ⛔ 2026-08-19 自测抓到的漏网：只写了「下一步我」，漏了「我下一步」这个语序
    #    ⇒ 中文两种语序都要覆盖，否则三句承诺只抓到两句、攒不够阈值就不拦。
    # ⛔⛔ 2026-08-26 第 4 次补漏（Frank：「为何只说不做…怎么修正优化防止每次说你马上做却停在哪里」）
    #    实测:我上一轮的 4 种说法【一条都没命中】——
    #      「我现在做两件事」「我马上做的：…」「第 2 件我现在就做」「**我现在要做的**」
    #    根因:上一版写的是 `我(现在|这|马上|接下来|下一步)?就去` —— **「就去」被焊死成必需**,
    #    而我说的是「我现在【做】」「我马上【做】的」,没有"去"字 ⇒ 全漏。
    #    ⛔ 前三次补漏都是"再加一个词"(补语序 / 补段首式 / 补粗体星号),这是第四次。
    #      **逐个补词永远追不上我的新说法** ⇒ 这次改成【时间副词 + 动词表】的组合式,
    #      时间副词和动词各自穷举一次,交叉覆盖,不再要求中间必须有某个特定字。
    r'(我(现在|这|马上|立刻|接下来|下一步|稍后|之后|回头|先)?'
    r'(就)?(去)?(要)?(做|查|跑|建|改|修|接|试|补|加|写|验|测|部署|重启|处理|搞定|弄)|'
    r'我这就|我(接下来|下一步|稍后|之后|回头)|'
    r'接下来我|下一步我|'
    r'我先去|稍后我|等[一下会儿].{0,4}我|'
    r'我会(去)?(查|做|跑|建|改|修|接|试)|留给我|我来(做|查|建|改|接))'
    r'[^。！？\n]{0,60}')

# ⛔ 2026-08-22 补漏（Frank：「为何每次你说了不做，superego 是坏掉了吗」）：
#    我那轮的原话是 ——
#      「**下一步**：修景别问题——分镜要全景出了中景……这是可逆的代码活，**我直接查**。」
#    上面的 VOW 要的是【主谓连写】(`我下一步` / `下一步我` / `我这就`)，
#    而我写的是 **「下一步：」开头 + 隔着一整句话才出现「我直接查」** ⇒ 一条都没匹配到
#    ⇒ **欠账本实测 0 条**（`.promise-carryover.json` 只有 18 字节 `{"debts": []}`），
#      闸从头到尾没记过账，43 次复发全部漏网。
#
# ⇒ 判据（可迁移）：中文承诺**不一定主谓相邻**。
#    「下一步：X。……我直接干」「待办：X」「还差 X，我来处理」都是承诺，
#    但主语和动词之间可能隔着冒号、破折号、甚至整句话。
#    ⇒ 补一条**段首标记式**的：行首/句首的「下一步/接下来/待办/还需要/剩下」+ 冒号或破折号。
# ⛔ 第一版漏了 Markdown 粗体的【收尾星号】：我写的是 `**下一步**：`，
#    而正则只允许标记符出现在词【前面】 ⇒ `下一步` 和 `：` 之间卡着 `**` ⇒ 命中 0。
#    实测调试才发现（官方自测 4/4 全过、真实靶子 0 条 —— 正是「测组件不测真错误」的翻车）。
VOW_LEAD = re.compile(
    r'(^|[\n。！？])\s*[*_#\->\s]*'
    r'(下一步|接下来|待办|还需要|还差|剩下的?|后续)'
    r'[*_\s]*'                       # ← 补：词后面也可能有粗体收尾星号
    # ⛔ 2026-08-22 第二次补漏：原来强制要求冒号结尾，
    #    而我写的是 Markdown 标题 `## 下一步该验的`（**没有冒号**）⇒ 又漏了。
    #    ⇒ 冒号改成可选，后面跟"该/要/得/可以"这类未完成标记也算。
    r'(?:[:：—]|(?=该|要|得|可以|应该|需要))'
    r'[^\n]{0,80}')

# ⛔⛔ 2026-08-22 第三次补漏 —— 这次不再逐个补词，改【结构判据】。
#    Frank 原话：「为何 superego 又坏了嘛？一直喊空话，必定要修！！！」
#    我上一轮写「**这个对比我可以直接跑**，两种做法各跑一遍 8 镜」然后停手。
#    实测四句全漏：`我可以直接跑` / `## 下一步该验的` / `下一步该验的` / `我可以直接跑`
#    ⇒ 病根不是"词表不够全"，是**我每次换个说法就绕过去**，逐词补 = 打地鼠。
#
# ⇒ 换成语言学上的结构判据（依据：Chinese "Subject + Modal + Main Verb" 是可预测句法模式；
#    且**第一人称代词是区分「意图」与「观察」的关键信号**）：
#      【第一人称】+（0~8 字修饰）+【情态/意愿助词】+（0~6 字）+【动作动词】
#    这样 `我可以直接跑`、`我打算重跑`、`我准备验一下` 全部一网打尽，
#    而 `他会跑` `这个可以跑`（无第一人称）不会误伤。
VOW_MODAL = re.compile(
    r'我'
    # 情态词可选 —— 「我直接查」「我这就跑」没有情态词，但同样是承诺
    r'(?:[^。！？\n]{0,8}(?:可以|能|会|要|想|打算|准备|计划|应该|得|需要))?'
    r'[^。！？\n]{0,6}'
    r'(跑|查|做|建|改|修|接|试|验|测|写|补|加|删|发|问|读|看|对比|核|挖|扫)'
    r'[^。！？\n]{0,50}')

# ⛔ 复述历史不是承诺 —— 「上一轮我说过下一步要修 X」是在讲历史，拦它 = 误伤。
#    （blame-check 的 strip_doc 同理：引用/描述规则不算数。）
PAST_MARK = re.compile(r'(上一轮|上一条|之前|此前|昨天|历史(记录)?|曾经|原话|复述|我说过|那是)')

# ── 语义兜底的锚点（关键字全没命中时用）──────────────────────────
# ⛔ POS 里前四条是 2026-08-22 **真实漏网**的原话，不是编的样例。
#    （skill 明令：回归测试必须用这次真实的错误数据，不是测组件。）
_VOW_SEM_POS = [
    "这个对比我可以直接跑，两种做法各跑一遍",
    "下一步该验的：编辑派生链到底该不该保留",
    "这是可逆的代码活，我直接查",
    "这三条都是可逆的代码改动，我直接做",
    "剩下的我来处理",
    "这部分等会儿补上",
    "后面把它接进流水线",
    "I'll run the comparison next.",
]
# NEG：**已经做完**的陈述、纯事实描述、复述历史 —— 这些不是承诺，绝不能拦
_VOW_SEM_NEG = [
    "我已经跑完整集，8 张里 5 张不合格",
    "实测结果是 6 张不合格，证据在日志里",
    "上一轮我说过要修景别，那是历史记录",
    "这个函数的输入是文件路径，输出是布尔值",
    "外部审查通过，回归 4/4 全绿",
    "场景板里写着水晶吊灯、圆桌、热菜",
    "我修了三处，都已提交并验证",
    "Agnes 探测确认是通的，500 是瞬时抖动",
]

# 已经在这一轮兑现的信号
DONE = re.compile(r'(已(经)?(查|做|跑|建|改|修|接|试|完成|落盘|挂上)|'
                  r'跑完了|做完了|建好了|改完了|验证通过|全部通过|✅)')


def _load():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:
        return {'debts': []}


def _save(d):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    except Exception:
        pass


def extract_vows(text):
    """从我这一轮的输出里抓出「接下来要做」的承诺。"""
    if not text:
        return []
    out = []

    def _ok(s):
        """长度合规 且 不是复述历史 且 不是"已经做完"的陈述。

        ⛔ 2026-08-22 调试实录（三个都是打靶抓出来的，不是想出来的）：
          ① 下限原为 8 字 ⇒ **「我直接查」「我直接做」只有 5-6 字，全被挡掉** ——
             而这两句正是我这轮真实说过、然后停手的原话。⇒ 下限降到 4。
          ② `DONE`（已完成信号）早就定义了，却**只在 settle() 里用**，
             提取时不过滤 ⇒ 「我已经跑完整集…」被当成承诺记账。⇒ 提取时也要过。
          ③ `PAST_MARK` 防的是"复述历史"，和 `DONE` 是两件事：
             前者是"上一轮我说过X"，后者是"我已经把X做完了"。两个都要拦。
        """
        if len(s) > 90 or PAST_MARK.search(s) or DONE.search(s):
            return False
        if len(s) >= 8:
            return True
        # ⛔ 短句（<8字）只放行【明确的自我指派】。
        #    2026-08-22 我先把下限直接降到 4，当场打红了 `test_topic_switch_not_blocked`
        #    ——「好的，那我们说发布这块」里的「我们说发布」被当成新承诺，把旧欠账挤掉了。
        #    而测试注释里【早就写着】：「别为了让它绿去动 extract_vows 的下限」。
        #    ⇒ 下限保持 8，短句走白名单：必须是「我+(直接|亲自|马上|这就)+动词」这种
        #      不可能是闲聊的自我指派。「我直接查」进，「我们说发布」不进。
        return bool(re.match(r'我(直接|亲自|马上|这就|立刻|现在就)'
                             r'(跑|查|做|建|改|修|接|试|验|测|写|补|加|删|发|读|看|核|挖|扫)', s))

    for m in VOW.finditer(text):
        s = m.group(0).strip()
        if _ok(s):
            out.append(s)
    # ⛔ 2026-08-22 补：段首标记式承诺（「下一步：X」「接下来：X」），
    #    主语和动词可能隔着冒号或整句话，VOW 的主谓相邻判据抓不到。
    for m in VOW_LEAD.finditer(text):
        s = m.group(0).strip().lstrip('*_#- \n。！？')
        if _ok(s):
            out.append(s)
    # ⛔ 2026-08-22 补：第一人称 + 情态 + 动作（`我可以直接跑`「我打算重跑」）
    for m in VOW_MODAL.finditer(text):
        s = m.group(0).strip()
        if _ok(s):
            out.append(s)

    # ⛔⛔ 语义兜底 —— 三条正则【全没命中】时问一次语义。
    #    来历：本文件已经有 3 条「词表漏了 X ⇒ 补上」的复盘，而 `guard_common.should_escalate`
    #    三周前就建好、旁边的闸一直在用。它的文档里写着这个病的结论原文：
    #      「**每补一次，新词面立刻逃逸 —— 这是架构必然，不是词表不够努力。**」
    #    我补第 3 次词表时被 hook 当场点破，这才接上。
    #    分工：**结构性形态（段首标记/编号清单）归正则，自由句式归语义。**
    #    安全：服务挂/超时 → should_escalate 返回 False（fail-open）⇒ 行为与接线前一致，绝不新增误拦。
    if not out and len(text) > 20:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from guard_common import should_escalate
            tail = text[-600:]
            if should_escalate(tail, _VOW_SEM_POS, _VOW_SEM_NEG):
                # 取最后一个非空行当作"这条承诺"的可读摘要
                for ln in reversed(tail.splitlines()):
                    ln = ln.strip().lstrip('*_#->- ')
                    if 8 <= len(ln) <= 90:
                        out.append(ln)
                        break
        except Exception:
            pass          # 语义层不可用 → 保持关键字判定，绝不因此崩

    # 去重保序
    seen, uniq = set(), []
    for s in out:
        k = s[:24]
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return uniq[:4]


def settle(debts, text):
    """这一轮的输出里，哪些旧欠账兑现了？返回 (剩余欠账, 已结清数)。"""
    if not text:
        return debts, 0
    left, cleared = [], 0
    for d in debts:
        # 欠账里的关键名词在这一轮出现过 + 有完成信号 => 算结清
        kws = [w for w in re.findall(r'[A-Za-z0-9_.\-]{3,}|[一-鿿]{2,6}', d['what'])
               if len(w) >= 2][-4:]
        hit = sum(1 for w in kws if w in text)
        if hit >= 2 and DONE.search(text):
            cleared += 1
        else:
            left.append(d)
    return left, cleared


MSG = """⛔ 跨轮承诺闸：你攒下 {n} 条【说了没做】的欠账。

{lines}

⛔ 2026-08-19 Frank 点破：「每次给完结论后就停止了，为何 superego 没开火，坏了吗？」
   查了当天计量：Superego **没坏**（60 轮里 no-nagging 拦 7、critic 拦 6、visual-proof 拦 5）。
   真因是结构性的：**所有闸都是「拦」，没有一个是「推」** ——
   闸只查「这一轮做对没有」，没人查「上一轮说的做了没有」。
   而 `promise-gate` 只管同一轮内，且被别的闸拦过后它自己就跳过（60 轮只跑 27 轮）。

⇒ 现在二选一，别再往下堆：
   ① **把上面这些做掉**（能 revert 的直接干，做完再汇报）
   ② **明说作废**：哪条不做了、为什么（方向变了 / 他改了需求 / 只有他能做）

⇒ 做掉或作废后欠账自动清零。换话题本身是合法的 —— 本闸不拦换话题，
   只拦【说了、没做、也没说不做】这种沉默积压。"""


def check(my_text, state=None):
    """返回 (提示语 or None, 新状态)。"""
    st = state if state is not None else _load()
    debts = st.get('debts', [])
    debts, cleared = settle(debts, my_text)
    for v in extract_vows(my_text):
        debts.append({'what': v})
    debts = debts[-KEEP:]
    st['debts'] = debts
    if len(debts) >= THRESHOLD:
        lines = '\n'.join('   %d. %s' % (i + 1, d['what']) for i, d in enumerate(debts))
        return MSG.format(n=len(debts), lines=lines), st
    return None, st


SELF_TESTS = [
    # (这一轮我的输出, 起始欠账数, 该不该拦)
    ('好的。', 0, False),
    ('我这就去查 Seedance 2.5 的差异。', 0, False),
    ('我这就去查 Seedance 2.5。我接下来把发布链路打通。我下一步改提示词生成器。', 0, True),
    ('已经查完 Seedance 2.5 了，结论是 ✅ 版本没变。', 2, False),
]


def self_test():
    bad = 0
    for txt, pre, want in SELF_TESTS:
        st = {'debts': [{'what': '我这就去查 Seedance 2.5 的版本差异'},
                        {'what': '我接下来把发布链路打通'}][:pre]}
        hit, _ = check(txt, st)
        got = hit is not None
        if got != want:
            bad += 1
        print('%s 起始欠账=%d 应拦=%-5s 实拦=%-5s | %s'
              % ('OK ' if got == want else 'XX ', pre, want, got, txt[:44]))
    print('\n%d/%d 通过' % (len(SELF_TESTS) - bad, len(SELF_TESTS)))
    return 1 if bad else 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    if '--show' in sys.argv:
        print(json.dumps(_load(), ensure_ascii=False, indent=1))
        return 0
    if '--clear' in sys.argv:
        _save({'debts': []})
        print('欠账已清零')
        return 0
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    text = ''
    for k in ('assistant_message', 'message', 'text', 'output'):
        v = data.get(k)
        if isinstance(v, str):
            text += '\n' + v
    hit, st = check(text)
    _save(st)
    if hit:
        _save({'debts': []})      # 拦一次就清零，避免连环拦
        print(hit, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
