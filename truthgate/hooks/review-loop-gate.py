"""外审循环闸（PLAN 第 5 步）：发起下一轮外审之前，按 ~/.truthgate/review_loop.py 的停止条件判（两端共用判据）：
同一个任务（Frank 上一句真话以来）连两轮外审不通过 / 轮数 / token / 时长到上限 ⇒ 拦下，让我停下来问他。
重放 9/26~27 airbnb 那次循环：12:27 那个任务在 16:09 就会被拦下（实际一路发到 00:03，共 13 轮、8 小时）。
只在「发起外审」那一刻才读会话记录；别的工具调用一进来就放行。fail-open：自己出错一律放行。"""
import json, os, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path.home() / '.truthgate'))
try:
    from guard_common import hook_log, turn_start_index, _parse_jsonl
except Exception:            # guard_common 坏了也别把这道闸一起带崩(main 见 hook_log 为 None 就放行,下面两个桩用不到)
    hook_log = None

    def turn_start_index(msgs):
        return -1

    def _parse_jsonl(data):
        return []
import review_loop as rl

GATE = 'review-loop-gate'


def main():
    data = json.loads(sys.stdin.read() or '{}')
    if not rl.is_review_call(data.get('tool_name'), data.get('tool_input')):
        return 0
    if hook_log is None:
        return 0
    tp = data.get('transcript_path') or ''
    try:
        msgs = _parse_jsonl(Path(tp).read_bytes())
    except Exception:
        hook_log(GATE, 'allow(no-transcript)')
        return 0
    s = turn_start_index(msgs)
    rounds = rl.rounds_from_claude(msgs[s + 1:], exclude_input=data.get('tool_input'))
    why = rl.judge(rounds, float(os.environ.get('REVIEW_LOOP_NOW') or time.time()))   # 重放旧记录时把「现在」设成当时
    if not why:
        hook_log(GATE, f'allow(第 {len(rounds) + 1} 轮)')
        return 0
    hook_log(GATE, f'BLOCK({why[0]})', why[1])
    print(rl.message(why), file=sys.stderr)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
