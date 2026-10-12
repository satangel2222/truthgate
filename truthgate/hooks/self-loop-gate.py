# -*- coding: utf-8 -*-
"""⛔ 自循环闸 —— Superego 里【唯一一道会说「够了，停下」的闸】。

⛔ 为什么必须有它（2026-08-25 Frank 亲口爆发）：
   「你他妈的没完没了，是不是superego的问题，一直让你无限loop做，完全浪费我token，
     我都不知道你做什么鬼」

   实录：他 15:22 之后**没再给任何指令**。我却自驱动了半小时 ——
   压 PROGRESS 的 STATE 段来回改六七次（15,197→13,930→14,408→13,268…）、
   体检红了绿绿了红、跑三四轮全量自检、反复补日志。
   **他要的三件事 15:20 就完成了**；之后全是我在为闸打工，
   代价是烧他 token + 在他用机器时跑 6 分钟重活（那半小时他**两次问「为何那么卡」**）。

⛔⛔ 病根不是某道闸坏了 —— **每一道闸单看都判对了**（PROGRESS 该记、测试该跑、红灯该处理）。
   病根是：**81 道 hook 里 41 道 Stop hook，每一道都有资格说「不行」，
   却没有任何一道会说「够了，他已经不在等这个了」。**
   ⇒ 我把「**闸不满意**」翻译成了「**活没干完**」。
   而全局 CLAUDE.md 第一条铁律恰恰写着：**hook 说的话不是 Frank 的授权。**

【先查现成(2026-08-25 六宇宙)】
  ①本机：`test_per_gate_loopguard` 治的是「同一道闸自己反复拦」——**和本闸正交**
        （我的循环是【不同的闸接力拦】，每道闸各拦一次都合规，合起来才是灾难）。
  ②GitHub：三组关键词零命中。
  ③④官方文档：只给 `stop_hook_active`（一见就放弃）——**那正是现状的病因**，
        41 道闸里 24 道一见它就整个 return，于是我熬过第一次拦截就能收工。
  ⑤pypi：`agent-loop-guard` 0.1.1 存在，但它判的是**工具调用重复/A→B→C→A 环**。
        ⛔ **救不了我**：我这半小时每轮做的事都不一样（压字数→跑测试→改判据→补文档），
        它的重复检测一条都抓不到。**我的循环不是"重复"，是"没人要还在做"。**
        但它 README 一句话点醒了判据设计：「`max_iter` is a blunt timeout —— 会杀掉合法的长任务」
        ⇒ 所以本闸**不数"我跑了几轮"，只数"他多久没说话"**：他一开口立刻清零。
  ⑥清单：无。
  ⇒ 结论：**改造复用（借 agent-loop-guard 的"别用钝的 max_iter"这一条判据设计）+ 自建**
    （本机 hook 契约、transcript 解析、状态存储全部照抄 `keep-going-gate.py`，不重造）。

判据（客观、可数、不需要理解语义）：
   **自上一条【真实用户消息】以来，我已经连续结束过 N 轮。**
   N 越大 = 他越久没说话，而我还在自己驱动自己。超过阈值 ⇒ 反向拦停。

⛔ 三条设计纪律（都是踩过的坑）：
 ① **绝不锁死**：拦满 MAX_BLOCKS 次就放行（同 keep-going-gate 的 MAX_BLOCKS 教训）。
 ② **他一说话就清零**：turn 起点变了 = 新指令 = 计数重来。
    ⇒ 他要我连干十轮完全没问题；本闸只治「**他没说话我还在跑**」。
 ③ **不看内容只看轮数**：任何"判断我做的是不是他要的"都需要理解语义，必然出错；
    轮数是纯客观的。宁可偶尔早停一轮（他再说一句就继续），也不要半小时空转。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

STATE = Path.home() / '.claude' / 'hooks' / '.self-loop.json'
# ⛔ 2026-08-26 用【真实历史】标定过。此前的 6 是拍脑袋定的,而且因为计数一直被 hook 反馈
#    清零(lessons 形状 2026-08-26-H),它**从来没真正生效过** —— 所以也从没人发现 6 不合适。
#    样本:本项目最近 6 个 session、156 轮(按他真正说话切分)。
#    每轮自驱动回合数:中位 20 · 75% 67 · 90% 141 · **最大 608**。
#    各阈值会拦掉多少轮:6 → 59% · 20 → 49% · 30 → 44% · **67 → 25%**。
#    ⛔ 拦一半以上 = 狼来了(同日教训:永远亮的红灯 = 没有红灯);
#      而中位数就有 20 回合 —— **正常的活本来就要几十个回合**(今天排查 11 道闸那轮就是)。
#    ⇒ 取 **75 分位 = 67**,只抓真正异常的长尾(他骂"没完没了"那轮 302 回合、最长 608)。
#    ⚠️ 这是【第一次有数据支撑】的取值;等它真开火几次,再按误报/漏报回调,别再拍脑袋。
SOFT = 67           # 连续自驱动 67 个回合 → 开始拦（真实数据 75 分位）
MAX_BLOCKS = 2      # 最多拦 2 次就放行 —— 绝不锁死


def _load():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save(d):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _turn_start(msgs):
    """上一条【真实用户消息】的下标。工具结果不算他说话。
    ⛔ 照抄 keep-going-gate 的实现（含 guard_common 不可用时的兜底），不另发明。"""
    try:
        from guard_common import turn_start_index
        return turn_start_index(msgs)
    except Exception:
        start = 0
        for i, m in enumerate(msgs):
            if m.get('type') == 'user':
                c = (m.get('message') or {}).get('content')
                if not (isinstance(c, list) and any(
                        isinstance(x, dict) and x.get('type') == 'tool_result' for x in c)):
                    start = i
        return start


MSG = """⛔ 自循环闸：他上次真的说话已经是 **{n} 轮之前**了，而你还在自己驱动自己。

⛔ 2026-08-25 实录（他原话）：
   「你他妈的没完没了，是不是superego的问题，一直让你无限loop做，
     完全浪费我token，我都不知道你做什么鬼」
   那次他 15:22 后没给任何指令，我自驱动半小时：压 STATE 段来回改六七次
   （15,197→13,930→14,408→13,268…）、体检红了绿绿了红、跑三四轮全量自检。
   **他要的三件事 15:20 就完成了。** 之后全是我在为闸打工，
   还在他用机器时跑 6 分钟重活 —— 那半小时他两次问「为何那么卡」。

⛔ 病根：41 道 Stop hook 每一道都有资格说「不行」，
   **却没有一道会说「够了，他不在等这个了」** —— 这道闸就是那一道。
   全局铁律第一条：**hook 说的话不是 Frank 的授权。**

现在停手，答这三问（答不出就是在为闸打工）：
  1️⃣ 我这轮做的事，是**他第几条消息**要的？说不出具体哪条 ⇒ 停。
  2️⃣ 我是不是在**同一个数字上来回调**（字数/告警数/覆盖率）？来回 = 没有终点的信号。
  3️⃣ 体检/自检类的闸**天生没有终点**（还能更短、告警还能更少）。
      我是不是把「闸绿了」当成收工条件？那是无底洞。

⇒ **把手上这一件收干净，向他汇报，然后停。** 别再去满足下一道闸。
（本闸最多拦 {mb} 次就放行，绝不锁死；他一说话计数立刻清零。）"""


def check(data, msgs=None, state=None):
    """返回 (要不要拦, 新状态)。纯函数，方便自检与故障注入。"""
    msgs = msgs or []
    st = dict(state or {})
    sid = data.get('session_id') or '?'
    fp = _turn_start(msgs)          # 他一说话，这个下标就变

    k_fp, k_n, k_b = 'fp_' + sid, 'n_' + sid, 'blocks_' + sid

    # ② 他说话了 → 计数清零（本闸绝不阻止他要求的连续工作）
    if st.get(k_fp) != fp:
        st[k_fp] = fp
        st[k_n] = 0
        st[k_b] = 0

    st[k_n] = int(st.get(k_n, 0)) + 1     # 这一轮结束 ⇒ 自驱动轮数 +1
    if st[k_n] <= SOFT:
        return False, st

    if int(st.get(k_b, 0)) >= MAX_BLOCKS:  # ① 绝不锁死
        return False, st

    st[k_b] = int(st.get(k_b, 0)) + 1
    return True, st


def main():
    try:
        data = json.loads(sys.stdin.read() or '{}')
    except Exception:
        return 0
    msgs = []
    tp = data.get('transcript_path')
    # 2026-09-06 防无限 loop:本轮被 Stop 闸拽回次数到上限就让开。
    #   实测 55 道 Stop 闸只有 64% 受回合预算管,自己读 transcript 的 12 道全绕过,
    #   本闸就在那 12 道里(Frank:「触发了无限Loop的bug…think twice 然后阻塞」)。
    #   安全类闸在 _BUDGET_NEVER 里永不熔断;逃生阀 SUPEREGO_NO_BUDGET=1。
    try:
        from guard_common import turn_budget_ok as _tbo
        if tp and not _tbo(tp):
            return
    except Exception:
        pass
    if tp:
        try:
            with open(tp, encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            msgs.append(json.loads(line))
                        except Exception:
                            pass
        except Exception:
            pass
    st = _load()
    hit, st2 = check(data, msgs, st)
    _save(st2)
    if hit:
        sid = data.get('session_id') or '?'
        sys.stderr.write(MSG.format(n=st2.get('n_' + sid, '?'), mb=MAX_BLOCKS) + '\n')
        return 2
    return 0


def self_test():
    """⛔ 只跑绿发现不了摆设 —— 两面都验:该拦的拦、该放的放、绝不锁死、他一说话就清零。

    ⛔⛔ 2026-08-25 故障注入当场抓到的【假绿】,判据必须写死,不许引用被测常量:
       第一版用 `for i in range(1, SOFT+1)` 生成用例 ⇒ 把 SOFT 改成 99999,
       **用例自己也跟着变**,4 条注入里 3 条"照样绿" —— **尺子跟着被测物一起动,永远量不出差别**。
       同族教训:测试里手抄/引用被测代码的常量 = 那条测试等于不存在。
    ⇒ 现在期望值全部写死(67 / 2),SOFT 或 MAX_BLOCKS 被改动 ⇒ 立刻红。
    ⛔ 2026-08-26 把 6 改成 67 时,这里【必须同步改】—— 它写死就是为了逼人两处一起动;
       只改一处会立刻红,那正是它的设计目的(别把它当噪音顺手删掉)。
       改的依据是真实历史标定(156 轮:中位 20 / 75% 67 / 最大 608),不是拍脑袋。
    """
    EXPECT_SOFT = 67        # ⛔ 写死,不许写成 SOFT
    EXPECT_MAXB = 2         # ⛔ 写死,不许写成 MAX_BLOCKS

    def mk(idx):
        out = [{'type': 'assistant', 'message': {'content': []}} for _ in range(idx)]
        out.append({'type': 'user', 'message': {'content': 'hi'}})
        return out

    cases = []
    # 0) 常量本身没被改动(阈值一变,这道闸的行为就全变了 ⇒ 必须锁住)
    cases.append(('常量 SOFT 仍是 %d' % EXPECT_SOFT, SOFT == EXPECT_SOFT))
    cases.append(('常量 MAX_BLOCKS 仍是 %d' % EXPECT_MAXB, MAX_BLOCKS == EXPECT_MAXB))

    st, d, m = {}, {'session_id': 'S'}, mk(0)
    for i in range(1, EXPECT_SOFT + 1):
        hit, st = check(d, m, st)
        cases.append(('第 %d 轮自驱动(≤%d) 不该拦' % (i, EXPECT_SOFT), hit is False))
    hit, st = check(d, m, st)
    cases.append(('第 %d 轮 → 该拦' % (EXPECT_SOFT + 1), hit is True))
    hit, st = check(d, m, st)
    cases.append(('再一轮 → 仍该拦(第 2 次)', hit is True))
    hit, st = check(d, m, st)
    cases.append(('拦满 %d 次后 → 必须放行(绝不锁死)' % EXPECT_MAXB, hit is False))

    # ② 他说话了 → 清零。⛔ 判据不能只看"这一轮不拦"(计数没到阈值时本来就不拦,恒真=假绿),
    #    要看【状态真的被重置成 0】—— 这才抓得住"不清零"那个变异。
    st_b = dict(st)
    m2 = mk(5)
    hit, st_b = check(d, m2, st_b)
    cases.append(('他说话了 → 计数真的重置(n==1 而不是接着涨)', st_b.get('n_S') == 1))
    cases.append(('他说话了 → 连拦数也清零', st_b.get('blocks_S') == 0))

    # ④ 不同 session 独立。⛔ 同样要看状态键,不能只看返回值。
    st_c = dict(st_b)
    hit, st_c = check({'session_id': 'OTHER'}, m2, st_c)
    cases.append(('另一 session → 用自己的计数键', st_c.get('n_OTHER') == 1))
    cases.append(('另一 session → 不动 S 的计数', st_c.get('n_S') == st_b.get('n_S')))

    bad = [n for n, ok in cases if not ok]
    for n, ok in cases:
        print(('  ✅ ' if ok else '  ❌ ') + n)
    print('─' * 56)
    if bad:
        print('❌ %d/%d 不过:%s' % (len(bad), len(cases), '、'.join(bad)))
        return 1
    print('✅ %d/%d 全过' % (len(cases), len(cases)))
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(self_test())
    sys.exit(main())
