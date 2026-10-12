#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""keep-going-gate —— 被拦之后只说话不干活就继续拦；真动手了立刻放行。

⛔ 来历（2026-08-19，Frank：「我说 nagging 不做事，或者最后所有任务还没完整做完
   就停下来，**为何不能 hook 继续做？？？？**」）：

   取证（实测，不是印象）：
     · **24 道闸**在 `stop_hook_active` 时直接 return
     · **19 道闸**用 `self_blocked_this_turn`（自己拦过就不再拦）
   ⇒ **整套 Superego 对我，每道闸一轮只有一次开火机会。**
     我被拦 → 补一句话 → 再次尝试结束 → 那道闸主动闭嘴。
     「我说要做 X 然后停下」能一路通过，机制原因就在这。

⛔ 官方文档支持「继续拦」（2026-08-19 查证 code.claude.com/docs/en/hooks）：
     "A Stop hook that exits 2 forces Claude to keep working...
      the cycle continues until tests pass"
     "Always give a blocking Stop hook a termination condition —
      **a bounded retry count, or a check of the transcript**"
   ⇒ 官方给的终止条件是【有界重试】或【查 transcript】，
     而现有 24 道闸用的是最粗暴的那种：一见 stop_hook_active 就整个放弃。

⛔ 为什么它们当初那么写（不是偷懒，是有事故的）：
   lessons 形状 AA（2026-07-29）：我给自己造的闸把我锁进死循环，
   Frank 原话「一小时的活干了七小时」。「只拦一次」是那次的止血带 ——
   治好了死循环，代价是**闸从「必须做到」降级成「提醒一次」**。

⛔ 本闸补那个代价，但必须同时满足三层：
   ① 原始真人消息明确叫我动手（问候/问答没有待执行任务）
   ② 本轮确实零工具调用
   ③ 同一任务最多连拦 MAX_BLOCKS 次；到顶后锁存放行，只有真人给新任务才重新武装
   不能只清空计数：`stop_hook_active` 仍为 True 时会立刻从 1 重数，变成 3 次一组的无限循环。

⛔ 先查现成（2026-08-19 扫六宇宙）→ 判定 **改造复用**：
   · 复用 `guard_common.turn_start_index()` 划本轮边界
   · 数 tool_use 的写法照抄 `idle-ask-gate.py`（它已在判「这轮零工具还在问」）
   · `false-done-gate` 也判「无工具调用」，但要求同时含强 claim，
     且**它自己也在 stop_hook_active 时跳过** —— 缝依旧在，故判据独立
   · GitHub `gh search repos "claude code stop hook enforcement"` **0 命中**
   · 官方文档只给模式不给实现

自测：python keep-going-gate.py --self-test
"""
import contextlib
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

# 记账：不 import guard_common 就不会进 hook-stats（2026-08-19 实测四道新闸全漏记）
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import guard_common  # noqa: F401
except Exception:
    pass

STATE = Path(os.environ.get('KEEP_GOING_STATE') or
             (Path.home() / '.claude' / 'hooks' / '.keep-going.json'))
LOCK = STATE.with_name(STATE.name + '.lock')
MAX_BLOCKS = 3          # 连拦上限，超过放行 —— 绝不锁死（形状 AA 的教训）


def _load():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save(d):
    """同目录临时文件原子替换；进程被中断也不会留下半截 JSON。"""
    tmp = STATE.with_name('%s.%d.tmp' % (STATE.name, os.getpid()))
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, STATE)
        return True
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass
        return False


@contextlib.contextmanager
def _state_lock(timeout=5.0):
    """跨进程锁住完整的 load → check → save，避免多个会话互相覆盖。"""
    f = None
    locked = False
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        f = open(LOCK, 'a+b')
        if os.name == 'nt':
            import msvcrt
            if os.path.getsize(LOCK) == 0:
                f.write(b'0')
                f.flush()
            end = time.time() + timeout
            while time.time() < end:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    time.sleep(0.01)
        else:
            import fcntl
            end = time.time() + timeout
            while time.time() < end:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except BlockingIOError:
                    time.sleep(0.01)
    except Exception:
        locked = False
    try:
        yield locked
    finally:
        if locked and f:
            try:
                f.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        if f:
            f.close()


def count_tools_this_turn(msgs):
    """本轮（最后一条真实用户消息之后）调用了几次工具。"""
    start = 0
    try:
        from guard_common import turn_start_index
        start = turn_start_index(msgs)
    except Exception:
        for i, m in enumerate(msgs):
            if m.get('type') == 'user':
                c = (m.get('message') or {}).get('content')
                if not (isinstance(c, list) and any(
                        isinstance(x, dict) and x.get('type') == 'tool_result' for x in c)):
                    start = i
    n = 0
    for m in msgs[start:]:
        c = (m.get('message') or {}).get('content')
        if isinstance(c, list):
            for x in c:
                if isinstance(x, dict) and x.get('type') == 'tool_use':
                    n += 1
    return n


# 本闸只负责“我明确说马上动手，却只说不做”。它不猜用户意图；普通问答、问候、
# 能力询问都交给原本负责它们的闸，避免一套硬拦截靠无限扩词表维持。
_PENDING_VERBS = (
    r"查|读取|读|打开|修改|改|修复|修|运行|跑|测试|验证|检查|排查|调查|搜索|抓取|下载|上传|"
    r"安装|卸载|配置|部署|启动|重启|停止|创建|新建|实现|开发|迁移|合并|提交|推送|回滚|"
    r"生成|制作|写|做"
)
_IMMEDIATE_SEGMENT_RE = re.compile(
    r"^\s*(?:(?:好的|明白|收到)[，,\s]*)?"
    r"(?:(?:我(?:现在|马上|立刻|直接|先|继续|接着|准备)(?:先|去|继续|接着)?|"
    r"接下来(?:我(?:会|先|去)?)?|先|继续|接着)\s*(?:" + _PENDING_VERBS + r"))",
    re.I,
)
_BARE_WILL_RE = re.compile(
    r"^\s*(?:(?:好的|明白|收到)[，,\s]*)?我会(?:先|去|继续|接着)?\s*(?:" + _PENDING_VERBS + r")",
    re.I,
)
_CAPABILITY_QUERY_RE = re.compile(
    r"你(?:会|能|可以|能够).{0,12}(?:什么|哪些|吗|嘛)[？?]?$|你是谁|介绍.{0,8}(?:你自己|你的能力)|"
    r"\bwhat can you do\b|\bwho are you\b",
    re.I,
)


def last_real_user(msgs):
    """返回最后一条真人输入的 (文本, 稳定回合身份)。"""
    text = ""
    identity = ""
    try:
        from guard_common import is_real_user_msg, _text_of
        for i, m in enumerate(msgs or []):
            if is_real_user_msg(m):
                text = _text_of((m.get('message') or {}).get('content')).strip()
                identity = str(m.get('uuid') or m.get('timestamp') or '%d:%s' % (i, text))
    except Exception:
        pass
    return text, identity


def has_pending_action(msgs):
    """当前真人回合里，助手有没有明确承诺马上执行一个工具型动作。"""
    try:
        from guard_common import turn_start_index, _text_of, strip_doc
        start = turn_start_index(msgs or [])
        prompt, _ = last_real_user(msgs)
        capability_answer = bool(_CAPABILITY_QUERY_RE.search(prompt))
        for m in (msgs or [])[start + 1:]:
            if m.get('type') != 'assistant':
                continue
            text = strip_doc(_text_of((m.get('message') or {}).get('content')))
            for segment in re.split(r"[。！？!?\n]+", text):
                if _IMMEDIATE_SEGMENT_RE.search(segment):
                    return True
                if not capability_answer and _BARE_WILL_RE.search(segment):
                    return True
    except Exception:
        return False
    return False


def action_fingerprint(identity):
    return hashlib.sha256((identity or '').encode('utf-8')).hexdigest()[:16]


MSG = """⛔ 继续做闸：你被拦过了，然后**这一轮一个工具都没调**就想再次收工。

⛔ 2026-08-19 Frank 原话：「我说 nagging 不做事，或者最后所有任务还没完整做完
   就停下来，**为何不能 hook 继续做？？？？**」
   取证：**24 道闸**在 stop_hook_active 时直接放行、**19 道**拦过一次就闭嘴 ——
   我只要熬过第一次拦截，说句话就能收工。本闸补的就是这条缝。

⇒ 本闸不看「你被拦过没有」，只看「**你这一轮有没有真的动手**」：
   · 调了任何工具（读文件 / 跑脚本 / 改代码 / 查证）→ **立刻放行**
   · 一个都没调 → 继续拦（第 {n}/{max} 次）

⇒ 现在二选一，别再解释：
   ① **把该做的做掉** —— 能 revert 的直接干
   ② 真做不了：说清**为什么只有他能做**（密码/扫码/花钱/对外发布/不可逆）

（同一项明确任务最多连拦 {max} 次；到顶后持续放行，
  只有你本人给出新任务才会重新计数。普通问候和问答不归本闸管。）"""


def check(data, msgs=None, state=None):
    """返回 (提示语 or None, 新状态)。"""
    st = state if state is not None else _load()
    sid = str(data.get('session_id') or 'default')
    # 只管【被别的闸拦过之后的重试】；第一次结束由别的闸负责
    if not data.get('stop_hook_active'):
        st.pop(sid, None)
        return None, st

    messages = msgs or []
    _prompt, turn_id = last_real_user(messages)
    if not has_pending_action(messages):               # 没承诺马上动手，就没有“说了却没做”
        st.pop(sid, None)
        return None, st
    if count_tools_this_turn(messages) > 0:             # 真动手了 -> 放行并清零
        st.pop(sid, None)
        return None, st

    fp = action_fingerprint(turn_id)
    raw = st.get(sid, {})
    if isinstance(raw, dict) and raw.get('prompt') == fp:
        cnt = int(raw.get('count', 0))
    else:
        cnt = int(raw) if isinstance(raw, int) else 0   # 兼容旧状态文件

    cnt += 1
    if cnt > MAX_BLOCKS:
        st[sid] = {'prompt': fp, 'count': MAX_BLOCKS}   # 锁存到真人给出新任务
        return None, st
    st[sid] = {'prompt': fp, 'count': cnt}
    return MSG.format(n=cnt, max=MAX_BLOCKS), st


def _mk(tools=0):
    msgs = [
        {'type': 'user', 'message': {'content': '做这个'}},
        {'type': 'assistant',
         'message': {'content': [{'type': 'text', 'text': '我现在去做'}]}},
    ]
    for _ in range(tools):
        msgs.append({'type': 'assistant',
                     'message': {'content': [{'type': 'tool_use', 'name': 'Bash'}]}})
    return msgs


SELF_TESTS = [
    # (stop_hook_active, 本轮工具数, 起始连拦数, 该不该拦)
    (False, 0, 0, False),   # 第一次结束 -> 不归本闸管
    (True,  0, 0, True),    # 被拦过 + 零工具 -> 拦
    (True,  3, 0, False),   # 被拦过 + 真动手 -> 放行
    (True,  0, 3, False),   # 已连拦 3 次 -> 上限放行，不锁死
    (True,  0, 1, True),    # 第 2 次 -> 继续拦
    (True,  1, 2, False),   # 拦了两次后终于动手 -> 放行
]


def self_test():
    bad = 0
    for active, ntools, pre, want in SELF_TESTS:
        st = {'S': pre} if pre else {}
        hit, _ = check({'stop_hook_active': active, 'session_id': 'S'},
                       _mk(ntools), st)
        got = hit is not None
        if got != want:
            bad += 1
        print('%s active=%-5s 工具=%d 连拦=%d 应拦=%-5s 实拦=%-5s'
              % ('OK ' if got == want else 'XX ', active, ntools, pre, want, got))
    print('\n%d/%d 通过' % (len(SELF_TESTS) - bad, len(SELF_TESTS)))
    return 1 if bad else 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    if '--clear' in sys.argv:
        _save({})
        print('已清零')
        return 0
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    msgs = []
    tp = data.get('transcript_path')
    if tp:
        try:
            from guard_common import load_transcript_tail
            msgs = load_transcript_tail(tp)
        except Exception:
            try:
                for ln in Path(tp).read_text(encoding='utf-8').splitlines():
                    try:
                        msgs.append(json.loads(ln))
                    except Exception:
                        continue
            except Exception:
                return 0        # fail-open：读不到 transcript 就别拦
    with _state_lock() as locked:
        if not locked:                              # 状态不可信时放行，不能冒险制造循环
            return 0
        hit, st = check(data, msgs, _load())
        if not _save(st):                            # 没记住次数就不能安全拦
            return 0
    if hit:
        print(hit, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
