#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""纸老虎看门 —— 每天把 `audit_paper_tigers.py` 真的跑一次,只在【变坏】时出声。

⛔ 先查现成(2026-08-26,六宇宙):
   ① 本机:`audit_paper_tigers.py`(五维判据完整、4 秒、已有 `--json`)+ `superego-health.py`
      ⇒ **复用它们的判据;本文件只做"定时跑 + 只报恶化"的壳,不重写任何判据**。
   ② GitHub:`gh search repos "hook health monitor regression alert"` + topic:observability+regression
      → 同类只有 ★0 个人项目(evaltrack / sornaris),对象是 LLM eval 不是 hook 接线。
   ⑤ WebSearch「detect dead or unwired hooks / drift detection 2026」→ 全是 IaC/API schema/ML 漂移,
      **没有一个查「hook 写了没挂上」** —— 那是 Claude Code harness 特有的问题。
   ⇒ 判「**改造复用**」。

⛔ 存在的理由(2026-08-26,Frank 问「superego 是不是没有记录轨迹的功能」顺藤摸出来的更糟的事):
   `audit_paper_tigers.py` 判据完全正确、docstring 里明写「--json 可挂 doctor / CI」,
   **但 settings.json 和 Windows 计划任务里都搜不到它** —— 它一次都没被自动调用过。
   ⇒ **审计纸老虎的工具,自己就是纸老虎。** 代价:`concise-answer-gate.py` 从 08-21 建成起
   **5 天没接线、零开火**,而那正是 A 类判据(未接线)一秒就能抓到的。

⛔ 为什么不是"每轮跑":4 秒 × 每轮 = 白烧他的机器;闸的接线状态按天变化足够。
⛔ 为什么"只在变坏时出声":每次都报 77 行 = 我必然略读(狼来了,同日教训)。
   只报**比上次差**的:新出现的未接线 / 新的判据恒假 / 新的无回归。
"""
import json
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
AUDIT = HOME / '.claude' / 'hooks' / 'audit_paper_tigers.py'
STATE = HOME / '.claude' / 'hooks' / '.paper-tiger-watch.json'
EVERY_HOURS = 20          # 每天一次;20 小时留出时区/作息漂移


def _load():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save(d):
    try:
        STATE.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def run_audit():
    """跑审计器 → (未接线, 判据恒假, 无回归, 总数);跑不动返回 None(放行,绝不卡死)。"""
    try:
        r = subprocess.run([sys.executable, str(AUDIT), '--json'],
                           capture_output=True, text=True, timeout=120,
                           encoding='utf-8', errors='replace')
        out = (r.stdout or '').strip()
        if not out:
            return None
        d = json.loads(out)
    except Exception:
        return None
    gates = d.get('gates') if isinstance(d, dict) else (d if isinstance(d, list) else None)
    if isinstance(gates, list) and gates:
        def issues(g):
            # 2026-09-16 外审:审计器真实字段是 flags(列表,如 ["B:...", "D:..."]);原来只读 issues/problem
            #   ⇒ 「判据恒假」计数恒为 0 —— 盯纸老虎的这道闸自己就是纸老虎。
            fl = g.get('flags')
            if isinstance(fl, list) and fl:
                return '; '.join(str(x) for x in fl)
            return str(g.get('issues') or g.get('problem') or g.get('problems') or '')
        unwired = sum(1 for g in gates if g.get('wired') is False)
        always = sum(1 for g in gates if issues(g).startswith('B:') or '; B:' in issues(g))
        notest = sum(1 for g in gates if g.get('has_test') is False or 'C:' in issues(g))
        return unwired, always, notest, len(gates)
    s = (d.get('summary') or d) if isinstance(d, dict) else {}
    try:
        return (int(s.get('unwired', 0)), int(s.get('never_fired', 0)),
                int(s.get('no_test', 0)), int(s.get('total', 0)))
    except Exception:
        return None


def scan_mutbak(root=None):
    """扫【故障注入/变异测试中断留下的孤儿备份】。返回 (还留着毒药的, 只是垃圾的)。

    ⛔ 2026-08-26 发现:`institutionalize-guard.mutbak.py` 在 hooks 里躺了 **12 天**,
       没有任何东西在看它。这次比对下来主文件是干净的(纯运气),但**下一次未必**——
       变异测试崩在半路时,留下的可能是【还插着毒药的闸】,而它照样每轮被 harness 加载、
       静默地什么都不拦。
    ⛔ 同族事故有前科(airbnb 项目 2026-08-25):`test_stale_asks_mutation.py` 跑到 572 秒崩了,
       把变异 `return []` 留在生产 doctor.py 里 ⇒ 整条闸被硬关掉,还被 auto-commit 提交进 git。
       那次的抗体(`scripts/test_mutation_restore.py`)覆盖了①锁 ②崩在半路 ③还原失败,
       **唯独没人扫"事后有没有孤儿留下"** —— 这里补的就是第四面。
    ⛔ 只读:比对内容、报告,绝不自动删(不是我这轮生成的东西不动)。
    """
    root = Path(root) if root else (HOME / '.claude' / 'hooks')
    poisoned, junk = [], []
    try:
        for bak in list(root.rglob('*.mutbak.*')) + list(root.rglob('*.mutbak')):
            # foo.mutbak.py -> foo.py ;  foo.py.mutbak -> foo.py
            name = bak.name
            main = (bak.with_name(name.replace('.mutbak', '', 1))
                    if '.mutbak' in name else None)
            if main is None or not main.exists():
                junk.append(bak.name)
                continue
            try:
                same = bak.read_bytes() == main.read_bytes()
            except Exception:
                continue                      # 读不出来(磁盘/权限)⇒ 不猜,跳过
            (junk if same else poisoned).append(main.name)
    except Exception:
        pass                                  # 看门狗自己绝不许炸
    return poisoned, junk


def check(now=None, state=None, audit=None):
    """纯判据(可注入 audit 以便离线测试)。返回 (提示文案或 None, 新 state)。"""
    st = dict(state if state is not None else _load())
    now = now if now is not None else time.time()
    # ⛔⛔ 这一段必须在【时间早退之前】——「闸里还插着毒药」是**活故障**,不是趋势指标:
    #   那道闸此刻正被 harness 加载、正在静默地什么都不拦。让它等 20 小时 = 判据恒不执行
    #   (launch-bound-guard 栽过同一跤:shell 扇出判据放错位置,整条路径永远到不了)。
    _poisoned, _junk = scan_mutbak()
    if _poisoned:
        return ('⛔ 变异测试留下的【毒药还插在闸里】:%s\n'
                '   这些闸此刻正被加载、可能正静默地什么都不拦。\n'
                '   ⇒ 先 `diff <闸>.mutbak.py <闸>.py` 看差在哪,确认是变异残留就用 .mutbak 覆盖回去,'
                '再重跑那道闸的回归。' % '、'.join(sorted(set(_poisoned)))), st
    if now - float(st.get('at') or 0) < EVERY_HOURS * 3600:
        return None, st                        # 还没到点 ⇒ 静默
    cur = (audit or run_audit)()
    if not cur:
        return None, st                        # 跑不动 ⇒ 放行,绝不卡死
    unwired, always, notest, total = cur
    prev = st.get('last') or {}
    first = not prev
    msgs = []
    if unwired and (first or unwired > int(prev.get('unwired', 0))):
        msgs.append('🔴 有 **%d 道闸未接线** —— 写了没挂上 = 等于没建'
                    '(2026-08-26 实录:concise-answer-gate 这样躺了 5 天零开火)' % unwired)
    if not first and always > int(prev.get('always', 0)):
        msgs.append('🟡 判据可能恒假的从 %s 变成 %s(新闸可能从不开火)'
                    % (prev.get('always'), always))
    if not first and notest > int(prev.get('notest', 0)):
        msgs.append('🟡 无回归测试的从 %s 变成 %s' % (prev.get('notest'), notest))
    st['at'] = now
    st['last'] = {'unwired': unwired, 'always': always, 'notest': notest, 'total': total}
    if not msgs:
        return None, st                        # 没变坏 ⇒ 一个字都不说
    return ('⛔ 纸老虎看门(每 %dh 一次,共 %d 道闸):\n   ' % (EVERY_HOURS, total)
            + '\n   '.join(msgs)
            + '\n   ⇒ 细节跑 `py -3.12 ~/.claude/hooks/audit_paper_tigers.py`'), st


def main():
    try:
        json.load(sys.stdin)                   # 消费 hook 输入,不用其内容
    except Exception:
        pass
    try:
        msg, st = check()
        _save(st)
        if msg:
            print(msg, file=sys.stderr)
            return 2
    except Exception:
        pass                                   # 看门狗自己绝不许拦死我
    return 0


if __name__ == '__main__':
    sys.exit(main())
