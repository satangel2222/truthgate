#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""答复相关性闸 —— 用【会读语义的 LLM】判「我到底有没有正面回答他」。

⛔ 它补的是 concise-answer-gate 补不了的那一半:
   那道闸量的是【长度比】(他问得短、我答得长)。**长度比是统计特征,判不了"答没答"** ——
   我完全可以写 300 字漂亮废话,长度不超标,照样答非所问。2026-08-25 我自己说过这句话,
   Frank 追问「完全防的彻底方案是什么」⇒ 就是这道闸。

先查现成(2026-08-25 六宇宙):
  · 业界这件事叫 **Answer Relevancy**(DeepEval / RAGAS 都有,LLM-as-judge)。
    官方判据:先让 LLM **抽出回复里的每条陈述**,再**逐条判它与问题是否相关**,算比例;
    低分正好对应「跑题 / 回避 / 答了另一个问题」。
  · 不装 DeepEval/RAGAS:它们面向 RAG 批量评测(pip 依赖重、要配 LLM、按数据集跑),
    塞不进每轮都要跑的 Stop hook。⇒ **改造复用它的判据**,用本机已通的免费通道(Agnes)实现。
  · 本机复用:`~/.claude/superego-critic/second-opinion.py` 的 `ask_agnes()`(免费、约 1 秒)。
  · 嵌入服务 7911 做不了这件事:相似度高 ≠ 回答了(废话可以与问题高度相似)。

⛔ 绝不把自己卡死(这道闸拦的是我自己,坏了代价很大):
   LLM 超时/不可用/返回不可解析 ⇒ **一律放行**;连拦上限 2 次;只在他那句【确实是个问题】时才跑。
"""
import json, os, re, sys
from pathlib import Path

HOME = Path.home()
STATE = HOME / '.claude' / 'hooks' / '.answer-relevancy.json'
MAX_BLOCKS = 2
TIMEOUT_S = 20
# ⛔ 2026-08-25 端到端实测把这个数改了:原本 400。我自己说过「我可以写 300 字废话照样答非所问」,
#    而 400 的门槛【正好放过那个攻击场景】—— 实测一段 388 字的纯汇报废话直接短路放行,
#    LLM 明明判对了(0/4 相关)却根本没被用上。⇒ 降到 150。
#    ⛔ 再一次:降到 150 后,实测一段 149 字的废话【又差一个字躲过去】。
#    ⇒ 领悟:**用长度做前置过滤,就永远留着一条"刚好躲过"的缝**。这个门槛的唯一正当理由是
#    「省一次调用」,不该承担判别职责 —— 判别交给 LLM(它对短回复也判得准:一句"修好了"
#    会被判 first_para_answers=True 而放行)。⇒ 压到只挡住真正的一句话回复。
MIN_REPLY_CHARS = 80         # 仅为省调用;判别一律交给 LLM,不靠长度
RELEVANT_FLOOR = 0.34        # 相关陈述占比低于它 = 跑题(RAGAS 式判据)

QUESTION_MARKS = ('?', '？', '吗', '嘛', '是不是', '有没有', '会不会', '为何', '为什么',
                  '怎么', '哪些', '什么', '多少', '能不能', '对不对')
HOOK_LINE_MARKS = ('⛔', '⛱', '[强制自检', '⚠️', '🔴', '📎')
# ⛔ 2026-08-26 实测:Frank 按 /renhua 时,skill 正文作为 user 消息注入,本闸把
#    「Base directory for this skill: ...」当成了【他的问题】,于是判「他问怎么装 skill,你却在讲
#    bug 修复,完全跑题」—— 而他根本没问那个。2026-08-21 的池子实测早写着 **8.7% 是 skill 正文**,
#    我只滤了 hook 反馈那 29.4%,漏了这一类。⇒ 补上 skill/slash 的特征串。
HOOK_BLOB_MARKS = ('Stop hook feedback', 'hook additional context', 'system-reminder',
                   'Stop hook blocking error', '<command-name>', '<command-message>',
                   'Base directory for this skill', 'Skill 优先', '触发词:')

SYSTEM = (
    "你是回答相关性评审。判据来自 DeepEval/RAGAS 的 Answer Relevancy:"
    "先抽出回复中的主要陈述,再逐条判断它是否在回答用户那个问题。"
    "跑题、回避、答了另一个问题、只汇报自己做了什么而没回答所问 —— 都算不相关。"
    "只输出 JSON,不要任何别的字。"
)

PROMPT = """用户的问题：
{q}

助手的回复：
{a}

请输出 JSON（不要 markdown 代码块）：
{{"statements": <回复里主要陈述的条数,整数>,
 "relevant": <其中【在回答上面那个问题】的条数,整数>,
 "first_para_answers": <回复的第一段是否直接回答了那个问题,true/false>,
 "why": "<一句话理由,20字内>"}}"""


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


def last_human_question(msgs):
    """最后一条【真人打的】user 消息(剥掉 hook 注入)。与 concise-answer-gate 同法。"""
    msgs = msgs or []
    for _i in range(len(msgs) - 1, -1, -1):
        m = msgs[_i]
        if m.get('type') != 'user' or m.get('isCompactSummary'):
            continue   # 2026-09-25:压缩接续的摘要也是 type=user,但不是他说的话(见 human_text)
        # ⛔ 2026-09-07:skill 正文也是以 user 消息注入的,且【每个 skill 长得都不一样】,
        #   靠 HOOK_BLOB_MARKS 枚举必然漏(artifact-design 一个标记都没有,当天误伤两次)。
        #   ⇒ 用结构判据:紧跟在 Skill 工具调用后面的 user 消息一律不是"他问的话"。
        if is_skill_injection(msgs, _i):
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


def human_text(m):
    """这条 user 消息里【真人打的字】;是 hook 注入/工具结果则返回 ''。"""
    # ⛔ 2026-09-25 实测:对话压缩接续后系统插入的摘要(isCompactSummary)被当成了他的问题,
    #   「他问的是:This session is being continued…」⇒ 误判「0/9 条在回答他」。结构标记判,不靠文字。
    if m.get('isCompactSummary') or m.get('type') != 'user':
        return ''
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
        return ''
    return txt


def is_skill_injection(msgs, i):
    """第 i 条 user 消息是不是【skill 正文注入】—— 看它前面最近那条助手消息有没有调 Skill。

    ⛔ 2026-09-07 实测:本闸连着误伤两次,把 `artifact-design` skill 的正文
      「Approach this as the design lead at a small studio…」当成了 Frank 的提问,
      于是判「他问设计,你却在讲测试,完全跑题」—— **他根本没问那个**。
    ⛔ 根因不是"名单少一条",是**判据方式错了**:HOOK_BLOB_MARKS 靠枚举特征串,
      而每个 skill 的正文长得都不一样(renhua 里有「Base directory for this skill」,
      artifact-design 一个标记都没有)⇒ **靠枚举必然漏,漏一个就误伤一次**。
    ⇒ 改成结构判据:skill 正文一定紧跟在一次 `Skill` 工具调用之后 —— 这个关系与正文内容无关,
      任何 skill 都成立,不用维护名单。(名单保留作兜底,它治的是 hook 注入那一类。)
    """
    for j in range(i - 1, max(-1, i - 4), -1):
        m = msgs[j]
        if m.get('type') != 'assistant':
            continue
        for item in (m.get('message') or {}).get('content') or []:
            if isinstance(item, dict) and item.get('type') == 'tool_use' \
                    and item.get('name') == 'Skill':
                return True
        return False          # 最近的那条助手消息没调 Skill ⇒ 这条不是 skill 注入
    return False


def last_turn(msgs):
    """⛔ 只取【最后一轮】:最后一条真人消息之后的部分。
    2026-08-25 实测踩坑:原来遍历整个 transcript ⇒ 拿到 24,895 字(今晚从第一句起的全部),
    LLM 当然判成「工作汇报」。同一个 bug 在 concise-answer-gate 里更致命 ——
    工具数变成【全会话累计】⇒ `tools <= 2` 在任何长对话里永远不成立 ⇒ 那条判据是死的。
    """
    msgs = msgs or []
    for i in range(len(msgs) - 1, -1, -1):
        if human_text(msgs[i]) and not is_skill_injection(msgs, i):
            return msgs[i:]
    return msgs


def assistant_text(msgs):
    out = []
    for m in last_turn(msgs):
        if m.get('type') != 'assistant':
            continue
        for item in (m.get('message') or {}).get('content') or []:
            if isinstance(item, dict) and item.get('type') == 'text':
                out.append(item.get('text', ''))
    return '\n'.join(out).strip()


def is_question(q):
    return bool(q) and any(mk in q for mk in QUESTION_MARKS)


def parse_verdict(raw):
    """从 LLM 回复里抠 JSON。抠不出返回 None ⇒ 调用方放行。"""
    if not raw:
        return None
    m = re.search(r'\{.*\}', raw, flags=re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    try:
        st = int(d.get('statements') or 0)
        rel = int(d.get('relevant') or 0)
    except Exception:
        return None
    if st <= 0:
        return None
    return {'statements': st, 'relevant': rel,
            'ratio': rel / st,
            'first': bool(d.get('first_para_answers')),
            'why': str(d.get('why') or '')[:60]}


def judge(question, reply, verdict):
    """纯判据(不联网),便于测试。返回 (是否该拦, 文案)。"""
    if not is_question(question):
        return False, ''
    if len(reply) < MIN_REPLY_CHARS:
        return False, ''
    if not verdict:                      # LLM 挂了/答得没法解析 ⇒ 放行,绝不卡死
        return False, ''
    bad_ratio = verdict['ratio'] < RELEVANT_FLOOR
    if bad_ratio or not verdict['first']:
        why = []
        if bad_ratio:
            why.append('只有 %d/%d 条陈述在回答他' % (verdict['relevant'], verdict['statements']))
        if not verdict['first']:
            why.append('第一段没有直接回答')
        return True, (
            '⛔ 答复相关性闸：%s。评审说：%s\n'
            '   他问的是：「%s」\n'
            '   ⇒ 把【直接回答那一句】提到第一段；复盘/收尾/验证过程放后面或删掉。\n'
            '   ⛔ 长度不是问题，**答没答**才是（这道闸判语义，不判长短）。'
            % ('；'.join(why), verdict['why'], question[:60]))
    return False, ''


_SO = [None]          # second-opinion 模块只加载一次(重复 exec_module 实测会偶发失败)
FAILLOG = HOME / '.claude' / 'hooks' / '.answer-relevancy-fail.log'


def _log_fail(why):
    """⛔ 静默降级 = 坏了没人知道(2026-08-25 当天的教训,我在这个新闸里差点又犯一遍)。
    LLM 这条路失败时必须留痕,否则这道闸会安静地变成纸老虎 —— 而我会以为它在守着。"""
    try:
        import datetime
        with io_open(FAILLOG, 'a') as f:
            f.write('%s\t%s\n' % (datetime.datetime.now().isoformat(timespec='seconds'),
                                  str(why)[:300]))
    except Exception:
        pass


def io_open(p, mode='a'):
    return open(str(p), mode, encoding='utf-8')


def _load_so():
    if _SO[0] is None:
        import importlib.util
        p = HOME / '.claude' / 'superego-critic' / 'second-opinion.py'
        spec = importlib.util.spec_from_file_location('so_relevancy', str(p))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SO[0] = mod
    return _SO[0]


def ask_llm(question, reply, tries=2, _ask=None):
    """复用 second-opinion 的免费通道。失败 ⇒ None ⇒ 放行,但【必须留痕 + 先重试】。

    ⛔ 2026-08-25 实测:免费通道会偶发「返回空」(日志实录 ask_agnes ok=False: 返回空)。
       不重试的话,通道每抖一次这道闸就静默漏过一次 —— 那正是今天刚学的【纸老虎】成因:
       闸还在,但它不响,而我以为它守着。重试免费、约 1 秒,成本远低于漏判。
    """
    prompt = PROMPT.format(q=question[:600], a=reply[:6000])
    # _ask 只为测试注入(默认走真实免费通道);不注入就没法验"重试到底有没有真的发生"。
    ask = _ask or (lambda p: _load_so().ask_agnes(p, SYSTEM,
                                                  timeout=TIMEOUT_S, max_tokens=400))
    for i in range(max(1, tries)):
        try:
            ok, raw = ask(prompt)
            if ok and parse_verdict(raw):
                return raw
            _log_fail('try%d ok=%s raw=%r' % (i + 1, ok, str(raw)[:120]))
        except Exception as e:
            _log_fail('try%d %s: %s' % (i + 1, type(e).__name__, e))
    return None


def check(data, msgs, verdict=None, llm=None):
    st = _load()
    sid = str(data.get('session_id') or 'default')
    if not data.get('stop_hook_active'):
        st.pop(sid, None)
        _save(st)
        return None
    q, a = last_human_question(msgs), assistant_text(msgs)
    if not is_question(q) or len(a) < MIN_REPLY_CHARS:
        st.pop(sid, None)
        _save(st)
        return None
    if verdict is None:
        verdict = parse_verdict((llm or ask_llm)(q, a))
    hit, msg = judge(q, a, verdict)
    if not hit:
        st.pop(sid, None)
        _save(st)
        return None
    cnt = int(st.get(sid, 0)) + 1
    if cnt > MAX_BLOCKS:
        st.pop(sid, None)
        _save(st)
        return None
    st[sid] = cnt
    _save(st)
    return msg + ('（连拦 %d/%d 次后放行）' % (cnt, MAX_BLOCKS))


def main():
    if os.environ.get('ANSWER_RELEVANCY_GATE') == 'off':
        return 0
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
    hit = check(data, msgs)
    if hit:
        print(hit, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
