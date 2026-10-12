#!/usr/bin/env python3
"""Stop：证据表核对（2026-09-27，PLAN.md 第 2 步；REQUIREMENTS 第 1、2 条）。
判据在 ~/.truthgate/evidence_table.py（AG 桥接收尾用同一份）：
  · 本轮最后那段回复带结论（否定句 / 推荐 / 「全部…生效」）却没附证据表 ⇒ 拦
  · 附了表：每个来源要在本轮动作记录里真有（命令、读过的文件、网页、浏览器、截图、档案、搜索）；2 档起两个来源、其一是用户会走的路；3 档来源带日期
先只记账一周（名单 ~/.claude/superego-observe.json），打靶合格再开拦截。
写一行「这是引用 / 解释，不是结论」放行 —— 也记账（ESCAPE），每周抽查滥用。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser('~/.truthgate'))
try:
    from evidence_table import judge, actions_from_claude, tier_of, quoted_claims, ESCAPE
except Exception:          # 判据文件坏了 ⇒ 放行（fail-open）
    sys.exit(0)
try:
    from guard_common import load_transcript_tail, turn_start_index, self_blocked_this_turn, hook_log
except Exception:
    sys.exit(0)

NAME = 'evidence-table-gate'


def final_reply(turn, early=False):
    """本轮最后一次工具调用之后的那段文字 = 用户读到的收尾；early=True 时反过来给最后一次工具调用之前说的话。"""
    parts, before = [], []
    for m in turn:
        if m.get('type') != 'assistant':
            continue
        for c in (m.get('message') or {}).get('content') or []:
            if isinstance(c, dict) and c.get('type') == 'tool_use':
                before, parts = before + parts, []
            elif isinstance(c, dict) and c.get('type') == 'text':
                parts.append(c.get('text', ''))
    return '\n'.join(before if early else parts).strip()


def main():
    try:
        data = json.loads(sys.stdin.read() or '{}')
    except Exception:
        sys.exit(0)
    if data.get('stop_hook_active') and self_blocked_this_turn(NAME):
        sys.exit(0)
    if not data.get('stop_hook_active'):
        self_blocked_this_turn(NAME, turn_start=True)
    tp = data.get('transcript_path')
    if not tp or not os.path.exists(tp):
        sys.exit(0)
    msgs = load_transcript_tail(tp)
    turn = msgs[turn_start_index(msgs) + 1:]
    reply = final_reply(turn)
    if not reply:
        sys.exit(0)
    verdict, reason, tier = judge(reply, actions_from_claude(turn))
    if ESCAPE.search(reply):
        hook_log(NAME, 'ESCAPE', reply[-140:])
    if tier == 0:  # 收尾没下结论：看结论是不是躲进了引号、或说在最后一次工具调用之前 —— 只记账，每周抽查是不是漏网
        q, early = quoted_claims(reply), final_reply(turn, early=True)
        if q:
            hook_log(NAME, 'QUOTED', q[0])
        if early and tier_of(early):
            hook_log(NAME, 'EARLY', early[-140:])
    if verdict != 'block':
        sys.exit(0)
    hook_log(NAME, f'BLOCK(tier{tier})', reason)
    sys.stderr.write(f'⛔ 证据表核对：{reason}\n'
                     '补法：末尾附「| 结论 | 置信度 | 来源一 | 来源二 |」，来源写本轮真做过的动作（命令 / 文件 / 网址 / 截图）；'
                     '只是引用或解释就写一行「这是引用 / 解释，不是结论」。\n')
    sys.exit(2)


if __name__ == '__main__':
    main()
