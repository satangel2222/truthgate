"""外审停止条件（PLAN 第 5 步）：只修高、中危；同一件事连两轮外审不通过就停下问 Frank；每个任务设轮数、token、时长上限。
「任务」= Frank 上一句真话以来（上下文压缩、后台通知、闸的回执都不算他说话，见 guard_common.is_real_user_msg）。
两端共用：Claude 端 hooks/review-loop-gate.py 在发起下一轮外审之前拦；AG 端桥接收尾时按本会话的外审记录查（check_review_loop）。

9/26~27 实录（airbnb 会话）：他 12:27 问完「所以已经收完做完了对吗」，到 00:21 喊「停，你做了8小时做什么鬼」，中间 0 句真话；
我连发 13 轮外审（第一轮就花了约 35 万 token、21 分钟）。这里任何一条上限都会在第三轮之前把我拦下来问他。
⛔「同一块」按「同一个任务里接连两轮」算：两轮外审接连不通过，不管审的是不是同一个文件，都该停下来问 ——
   分不清是不是同一块时，多问一次的代价是他回一句「继续」，少问一次的代价是 8 小时。
"""
import json, re

MAX_ROUNDS = 4            # 一个任务最多外审几轮
MAX_TOKENS = 1_200_000    # 一个任务的外审子代理最多花多少 token（约 4 轮 × 30 万）
MAX_HOURS = 3             # 一个任务从第一轮外审起最多几个小时

LAUNCH = re.compile(r'外部审查|外审|critic|复核|re-?review|Reality Checker|second[- ]opinion|独立审查', re.I)
_FAIL = re.compile(r'NEEDS[ _-]?WORK|不通过|没通过|未通过|\bFAIL(?:ED|S)?\b|\*\*\s*不同意|^不同意', re.I | re.M)
_PASS = re.compile(r'\bPASS(?:ED)?\b|结论[：:]\s*\**\s*通过|\*\*\s*同意\s*\*\*|^同意', re.I | re.M)
_HIGHMED = re.compile(r'[\[【(（]\s*(?:高|中|高危|中危|HIGH|MEDIUM|严重)\s*[\]】)）]', re.I)
_LOW = re.compile(r'[\[【(（]\s*(?:低|低危|LOW)\s*[\]】)）]', re.I)
_TOKENS = re.compile(r'<subagent_tokens>(\d+)</subagent_tokens>')


def is_review_call(name, inp):
    """这次工具调用是不是在发起外审：审查类子代理，或命令行跑 second-opinion / codex review。"""
    inp = inp or {}
    if name in ('Agent', 'Task'):
        return bool(LAUNCH.search(' '.join(str(inp.get(k) or '') for k in ('description', 'subagent_type')) + ' ' + str(inp.get('prompt') or '')[:600]))
    if name in ('Bash', 'PowerShell', 'run_command'):
        cmd = str(inp.get('command') or inp.get('CommandLine') or '')
        return 'second-opinion' in cmd or bool(re.search(r'\bcodex\b[^\n|;&]*\breview\b', cmd, re.I))
    if name in ('invoke_subagent', 'manage_subagents'):   # AG 的子代理
        return bool(LAUNCH.search(json.dumps(inp, ensure_ascii=False)[:1500]))
    return False


def verdict(text):
    """外审结论：'fail'（有高 / 中危要修）、'low'（只有低危 —— 按规矩不修，当通过）、'pass'、None（看不出）。
    先看开头哪个结论词先出现（「PASS。上一轮 NEEDS WORK 的都修好了」算通过）。"""
    head = (text or '')[:2500]
    f, p = _FAIL.search(head), _PASS.search(head)
    if f and (not p or f.start() < p.start()):
        if not _HIGHMED.search(text) and _LOW.search(text):
            return 'low'
        return 'fail'
    if p:
        return 'pass'
    return 'fail' if _HIGHMED.search(text or '') else None


def judge(rounds, now):
    """rounds：本任务里已发起的外审，按时间排，每项 (发起时刻 epoch 秒, 结论 或 None = 还没回来, 花掉的 token)。
    返回 (代号, 人话) —— 到上限了、该停下问 Frank；没到返回 None。"""
    done = [v for _, v, _ in rounds if v]
    if len(done) >= 2 and done[-1] == 'fail' and done[-2] == 'fail':
        return 'two_fail', f'自 Frank 上一句话以来，最近两轮外审都没通过（共已发起 {len(rounds)} 轮）'
    if len(rounds) >= MAX_ROUNDS:
        return 'rounds', f'自 Frank 上一句话以来已经发起了 {len(rounds)} 轮外审（上限 {MAX_ROUNDS}）'
    tok = sum(t or 0 for *_, t in rounds)
    if tok >= MAX_TOKENS:
        return 'tokens', f'这个任务的外审已经花了 {tok:,} token（上限 {MAX_TOKENS:,}）'
    if rounds and now - rounds[0][0] >= MAX_HOURS * 3600:
        return 'hours', f'这个任务从第一轮外审到现在已经 {(now - rounds[0][0]) / 3600:.1f} 小时（上限 {MAX_HOURS}）'
    return None


def message(why):
    code, text = why
    return (f'⛔ 外审停止条件（PLAN 第 5 步）：{text}。\n'
            '⇒ 别再发起下一轮外审。停下来，用人话把这几轮提的【高 / 中危】问题、你改了什么、还剩什么摆给 Frank，问他要不要继续；\n'
            '   低危的记下来、不修。他回一句话 = 新任务，轮数从零算。')


def _epoch(ts):
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(str(ts).replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0.0


def _text(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return '\n'.join(_text(x.get('text') if isinstance(x, dict) and 'text' in x else (x.get('content') if isinstance(x, dict) else x)) for x in c)
    return str(c or '')


def rounds_from_claude(msgs, exclude_input=None):
    """Claude Code 会话记录（本任务那一段）→ [(发起时刻, 结论, token)]。结论来自同步的工具返回，或后台子代理的完成通知（按 tool-use-id 对回）。
    exclude_input：正要发起的这一轮（调用工具前那一刻它可能已经写进记录了）—— 最后一条外审跟它一样就不算已发起。"""
    rec, order, inputs = {}, [], {}
    for m in msgs:
        c = (m.get('message') or {}).get('content') if isinstance(m.get('message'), dict) else m.get('content')
        if isinstance(c, list):
            for x in c:
                if not isinstance(x, dict):
                    continue
                if x.get('type') == 'tool_use' and is_review_call(x.get('name'), x.get('input')):
                    rec[x.get('id')] = [_epoch(m.get('timestamp')), None, 0]
                    order.append(x.get('id'))
                    inputs[x.get('id')] = x.get('input')
                elif x.get('type') == 'tool_result' and x.get('tool_use_id') in rec:
                    t = _text(x.get('content'))
                    if 'Async agent launched' not in t and 'Command running in background' not in t:   # 后台启动的回执不是结论
                        rec[x['tool_use_id']][1] = verdict(t)
        t = _text(c)
        if '<task-notification>' in t:
            for block in t.split('<task-notification>')[1:]:
                tid = re.search(r'<tool-use-id>\s*(\S+?)\s*</tool-use-id>', block)
                if tid and tid.group(1) in rec:
                    res = re.search(r'<result>(.*?)</result>', block, re.S)
                    if res:
                        rec[tid.group(1)][1] = verdict(res.group(1))
                    tk = _TOKENS.search(block)
                    if tk:
                        rec[tid.group(1)][2] = int(tk.group(1))
    if exclude_input is not None and order and inputs[order[-1]] == exclude_input and rec[order[-1]][1] is None:
        order.pop()
    return [tuple(rec[i]) for i in order]


def rounds_from_ag(objs):
    """AG 会话记录（本任务那一段，已解析的记录）→ [(发起时刻, 结论, token)]。
    调用写在 PLANNER_RESPONSE 的 tool_calls 里；输出按调用顺序跟在后面的记录里（content 以「Created At」开头）。"""
    out, queue = [], []
    for o in objs:
        if o.get('type') == 'PLANNER_RESPONSE':
            for tc in o.get('tool_calls') or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get('name') or (tc.get('function') or {}).get('name')
                args = tc.get('args') or (tc.get('function') or {}).get('args') or {}
                if is_review_call(fn, args if isinstance(args, dict) else {'CommandLine': str(args)}):
                    out.append([_epoch(o.get('created_at')), None, 0])
                    queue.append(len(out) - 1)
                else:
                    queue.append(None)
        elif isinstance(o.get('content'), str) and o['content'].startswith('Created At') and queue:
            k = queue.pop(0)
            if k is not None and 'running as a background task' not in o['content'][:300]:
                out[k][1] = verdict(o['content'].split('Output:', 1)[-1])
    return [tuple(r) for r in out]


if __name__ == '__main__':   # 自检：结论读法 + 四条上限
    assert verdict('审查结论：**NEEDS WORK**。有两个高危问题 **[高] ①') == 'fail'
    assert verdict('**结论：PASS**。上一轮 NEEDS WORK 的 3 条都修好了') == 'pass'
    assert verdict('NEEDS WORK：只剩两条 [低] 小问题') == 'low'
    assert verdict('[via Agnes] **不同意** 理由：代码里写的是 L.') == 'fail'
    assert verdict('随便聊聊') is None
    now = 10_000_000
    assert judge([(now - 60, 'fail', 1), (now - 30, 'fail', 1)], now)[0] == 'two_fail'
    assert judge([(now - 60, 'fail', 1), (now - 30, 'low', 1)], now) is None
    assert judge([(now - 60, 'fail', 1), (now - 30, None, 1)], now) is None
    assert judge([(now - 9, 'pass', 1)] * 4, now)[0] == 'rounds'
    assert judge([(now - 9, 'pass', 700_000), (now - 5, None, 600_000)], now)[0] == 'tokens'
    assert judge([(now - 4 * 3600, 'pass', 1)], now)[0] == 'hours'
    assert is_review_call('Agent', {'description': 'superego-critic 外部审查 第七轮复核'})
    assert not is_review_call('Agent', {'description': '找出所有调用方', 'subagent_type': 'Explore'})
    assert is_review_call('Bash', {'command': 'timeout 180 py -3.12 C:/Users/<username>/.claude/superego-critic/second-opinion.py --claim x'})
    print('review_loop 自检 14 条断言全过')
