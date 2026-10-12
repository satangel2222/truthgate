#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简洁闸 —— 两条【互相独立】的判据。
判据A(2026-08-21 建):工具少却话多  —— tools<=2 AND chars>500
判据B(2026-08-25 补):**他问判断/原因题,我却回长篇** —— 与工具数【无关】

⛔ 为什么补 B(形状 2026-08-25-T):
   A 是 AND 条件,只覆盖"工具少+话多"。2026-08-25 我每轮跑十几个工具、每轮回两三千字,
   连着四轮答非所问,**A 一次都没开火** —— 正好从判据的缝里漏过去。
   Frank 连问两次「你有回答我的问题吗」「以后还会和现在一样吗」。
   而 08-21 那条 lessons 里【写了】"回答长度÷问题长度>10 触发",**代码里从没实现**。
   ⇒ 教训:写在 lessons 里的判据 ≠ 落成代码的判据。本次把它真正实现。

⛔ B 只抓【判断题/原因题】(短 + 带疑问词),放过【清单题】(什么/哪些/所有/列举)——
   后者本来就该长答。误拦成本高于漏拦,故留 MAX_BLOCKS 上限自动放行。
"""
import json, re, sys
from pathlib import Path

HOME = Path.home()
STATE = HOME / '.claude' / 'hooks' / '.concise-answer.json'
MAX_BLOCKS = 1   # 2026-09-09 Frank「为何收工重复两次,有Bug」:本闸判据=「已输出字数太多」,而这是【回话改不了的】
                 # (回一句只会加字)⇒ 拦多次纯属逼我重复回复(他看到连着几个「收工」)。改成【拦一次就放】=北极星铁律②
                 # (同轮拦一次就闭嘴,别造 loop)。一次 nudge 足够,已送出的字撤不回,多拦无意义。

# 判据A
TOOL_THRESHOLD = 2
CHAR_THRESHOLD = 500

# 判据B
Q_MAX_CHARS = 40        # 他的问题多短才算"判断/原因题"
A_MIN_CHARS = 1500      # 我的回复超过这个才算"长篇"
YES_NO_MARKS = ('吗', '嘛', '是不是', '有没有', '会不会', '对不对', '能不能', '为何', '为什么', '怎么会')
LIST_MARKS = ('什么', '哪些', '哪几', '列', '所有', '全部', '清单', '有多少', '总结', '汇报', '报告')

HOOK_LINE_MARKS = ('⛔', '⛱', '[强制自检', '⚠️', '🔴', '📎')
# ⛔ 2026-08-26:同 answer-relevancy-gate —— skill 正文(/renhua 等)会作为 user 消息注入,
#    不滤掉就会被当成「他的问题」。2026-08-21 实测池子里 8.7% 属于这一类。
HOOK_BLOB_MARKS = ('Stop hook feedback', 'hook additional context', 'system-reminder',
                   'Stop hook blocking error', 'tool_result', '<command-name>',
                   '<command-message>', 'Base directory for this skill', '触发词:')


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


def last_turn(msgs):
    """⛔ 只取【最后一轮】。2026-08-25 实测:原来这里遍历整个 transcript ⇒ 工具数是
    【全会话累计】(长对话里上百个)⇒ 判据A 的 `tools <= 2` **永远不成立** ⇒ 那条判据是死的。
    这是本闸「零开火」的第二层真因(第一层是它根本没注册进 settings.json)。"""
    msgs = msgs or []
    for i in range(len(msgs) - 1, -1, -1):
        m = msgs[i]
        if m.get('type') != 'user':
            continue
        c = (m.get('message') or {}).get('content')
        if isinstance(c, list):
            txt = ''.join(x.get('text', '') for x in c
                          if isinstance(x, dict) and x.get('type') == 'text')
        else:
            txt = str(c or '')
        if any(mk in txt for mk in HOOK_BLOB_MARKS):
            txt = re.sub(r'<system-reminder>.*?</system-reminder>', '', txt, flags=re.S)
        lines = [l for l in txt.split('\n')
                 if l.strip() and not l.strip().startswith(HOOK_LINE_MARKS)]
        txt = '\n'.join(lines).strip()
        if txt and not any(mk in txt for mk in HOOK_BLOB_MARKS):
            return msgs[i:]
    return msgs


def count_tools_and_chars(msgs):
    """tools = 本轮累计(该累计);chars = **最后一段连续的 assistant 文本**(= 交给他的那条回复)。

    ⛔ 2026-08-25 实测:原本 chars 也按整轮累计 ⇒ 一个跨几十次工具调用的长任务里,
       每次调用之间的说明文字全被加进去,累计上万字是【必然】的 ⇒ **判据B 恒真、每轮都拦**。
       当晚它连拦 3 次报「你回了 10,708 字」,而我最后那条回复只有几百字、第一段就是直接回答。
       ⇒ 和同一天发现的「判据A 恒假」(tools 按全会话累计,<=2 永不成立)是一对:
       **一个恒假=从不响,一个恒真=一直响 —— 而「永远亮的红灯 = 没有红灯」。**
    ⇒ 判他【最终交出去的那条】说了多久,才是这道闸的本意。
    """
    turn = last_turn(msgs)
    tools = 0
    for m in turn:
        if m.get('type') != 'assistant':
            continue
        for item in (m.get('message') or {}).get('content') or []:
            if isinstance(item, dict) and item.get('type') == 'tool_use':
                tools += 1

    # 从尾部往回收集,遇到 tool_use(说明后面还有动作)就停 ⇒ 只留最后那段纯文本回复
    chunks = []
    for m in reversed(turn):
        if m.get('type') != 'assistant':
            continue
        content = (m.get('message') or {}).get('content') or []
        if any(isinstance(i, dict) and i.get('type') == 'tool_use' for i in content):
            break
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text':
                chunks.append(item.get('text', ''))
    return tools, sum(len(c) for c in chunks)


def last_human_question(msgs):
    """取最后一条【真人打的】user 消息,剥掉 hook 注入与 system-reminder。"""
    for m in reversed(msgs or []):
        if m.get('type') != 'user':
            continue
        c = (m.get('message') or {}).get('content')
        if isinstance(c, list):
            txt = ''.join(i.get('text', '') for i in c
                          if isinstance(i, dict) and i.get('type') == 'text')
        else:
            txt = str(c or '')
        if any(mk in txt for mk in HOOK_BLOB_MARKS):
            txt = re.sub(r'<system-reminder>.*?</system-reminder>', '', txt, flags=re.S)
        lines = [l for l in txt.split('\n')
                 if l.strip() and not l.strip().startswith(HOOK_LINE_MARKS)]
        txt = '\n'.join(lines).strip()
        if not txt or any(mk in txt for mk in HOOK_BLOB_MARKS):
            continue
        return txt
    return ''


def judge(tools, chars, question):
    """返回 (是否该拦, 原因文案)。两条判据互相独立,任一命中即拦。"""
    if tools <= TOOL_THRESHOLD and chars > CHAR_THRESHOLD:
        return True, ('⛔ 简洁闸·判据A：本轮只用了 %d 个工具却输出 %d 字，删到必要长度。' % (tools, chars))

    q = (question or '').strip()
    if q and len(q) <= Q_MAX_CHARS and chars > A_MIN_CHARS:
        if any(mk in q for mk in YES_NO_MARKS) and not any(mk in q for mk in LIST_MARKS):
            return True, (
                '⛔ 简洁闸·判据B：他问的是【判断/原因题】(%d 字：「%s」)，你却回了 %d 字。\n'
                '   ⇒ **第一段必须直接回答那一句**(是/不是 + 一句为什么)，复盘和收尾报告放后面或不写。\n'
                '   ⛔ 闸绿 ≠ 答了：所有 Stop 闸只验「我做了什么」，没有一道验「他的问题答了没」。\n'
                '   自检：读一遍自己的第一段 + 他这句话，对不上就重写。→ lessons 形状 2026-08-25-T'
                % (len(q), q[:40], chars))
    return False, ''


def check(data, msgs=None, state=None):
    st = state if state is not None else _load()
    sid = str(data.get('session_id') or 'default')
    if not data.get('stop_hook_active'):
        st.pop(sid, None)
        return None, st
    tools, chars = count_tools_and_chars(msgs or [])
    hit, msg = judge(tools, chars, last_human_question(msgs))
    if hit:
        cnt = int(st.get(sid, 0)) + 1
        if cnt > MAX_BLOCKS:
            st.pop(sid, None)
            return None, st
        st[sid] = cnt
        return msg + ('（连拦 %d/%d 次后放行）' % (cnt, MAX_BLOCKS)), st
    st.pop(sid, None)
    return None, st


def main():
    try:
        data = json.load(sys.stdin)
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
            for ln in Path(tp).read_text(encoding='utf-8').splitlines():
                try:
                    msgs.append(json.loads(ln))
                except Exception:
                    continue
        except Exception:
            return 0
    hit, st = check(data, msgs)
    _save(st)
    if hit:
        print(hit, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
