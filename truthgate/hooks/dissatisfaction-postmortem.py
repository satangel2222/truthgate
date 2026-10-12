#!/usr/bin/env python3
"""UserPromptSubmit hook: Frank 不满 → postmortem-to-guard。语义分级版(2026-07-23 重构)。

演进:
 2026-07-19 v1: 纯关键字。2026-07-22: Frank 骂人8条漏7条,扩关键字→10/10(但关键字对subtle天生瞎)。
 2026-07-23 v2(本版): Frank 要「98%召回·语义不是关键字」→ 建语义分类服务(127.0.0.1:8911):
   bge-small-zh嵌入+logreg(从本地LLM给1900条真实消息打标蒸馏、cleanlab清、196条我亲手gold测)。
   实测: 组合(关键字OR语义)召回98.6%(196gold漏1)、强制档精度83%、延迟36ms/CPU/零显存。
   为何不用LLM当分类器: qwen3-1.7B/4B实测都2.4-2.7秒/条,太慢+抢GPU;嵌入蒸馏了LLM标、11ms。

分级(降低低精度的代价):
 - strong(关键字命中 或 语义分≥0.69,精度83%) → 强制走 postmortem。
 - soft (0.27≤分<0.69) → 软提示:我自己判断是不是真不满,是则postmortem,中性则放行(误报只花我一次判断)。
 - 服务不可达 → fail-open 退回关键字正则(绝不比 v1 差)。

安全: fail-open(任何异常放行/退关键字)、只读、留日志。"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:            # ⛔ 必须带兜底:原来是裸 import —— guard_common 一坏,这道闸第一行就炸,
    from guard_common import hook_log      # 下面精心写的 fail-open 降级桩全成了到不了的死代码(外部critic抓到)
except Exception:
    def hook_log(*a, **k):
        pass
import sys, json, re, os, time, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8"); sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dissatisfaction-postmortem.log")
# ⛔ 2026-09-05: 原来硬编 8911 —— 那是【早已废弃】的端口(真端口见 superego-port.txt, 现 17911),
#   于是这道闸一直在敲没人听的端口 = 语义分类永远失败、静默退回关键字兜底。
#   端口只有一个真相来源(superego_port), 谁要用谁来读, 不许再出现第二处硬编。
try:
    _sys.path.insert(0, _os.path.join(_os.path.expanduser("~"), ".claude"))
    from superego_port import BASE as _SEM_BASE
    SVC = _SEM_BASE.rstrip("/") + "/classify"
except Exception:
    _p = "17911"
    try:
        _p = open(_os.path.join(_os.path.expanduser("~"), ".claude", "superego-port.txt"),
                  encoding="utf-8").read().strip() or "17911"
    except Exception:
        pass
    SVC = "http://127.0.0.1:%s/classify" % _p

# fail-open 关键字(服务挂了用它 = v2 之前那套已测10/10的正则)
DISSAT = re.compile(
    r"你又错|又错了|你错了|这不对|不对吧|不对啊|你确定吗|确定吗\?|真的查过|你.{0,6}真的吗"
    r"|你在骗我|你骗我|骗人|你没验证|没验证吧|没测吧|又幻觉|幻觉了|脑袋有水|脑袋进水"
    r"|白干|(?<!明)白做|白忙|为何.{0,6}笨|怎么.{0,6}笨|那么笨|这么笨|太笨|是什么鬼|什么鬼|搞什么"
    r"|没搞懂|还没搞懂|没懂|懂不懂|垃圾|无语|敷衍|糊弄|忽悠|你怎么又|你又来|又来了|(?:又|还).{0,3}重来"
    r"|根本没(?!问题|错|事)|明明|说了多少次|讲了多少次|又没做"
    r"|干你?妈|你他?妈|他妈的|妈的|操你|草你|卧槽|我靠|个屁|什么屁|放屁"
    r"|又失忆|失忆了|你不记得|不记得了|你忘了|你又忘|脑子有"
    r"|还(要劳烦|要麻烦|得|还得|要)(我)?(自己|亲自|动手|来做|来弄|来搞)"
    r"|劳烦我|麻烦我自己|得我自己|我自己动手|还得我"
    r"|反复.{0,5}(骂|错|说|提|试)|我骂你|骂你|又骂"
    r"|居然(没|还|不|又)|竟然(没|还|不)|到现在(还|居然|没|都)"
    r"|你是不是又|说过多少次|根本不|又没(做|查|测|验|搞|弄|上网|去)|你又(没|错|忘|来)"
    r"|你自己觉得|你觉得.{0,8}(有逻辑|合理|说得通|对吗|对不对|正常吗)|有逻辑吗"
    r"|你搞懂.{0,6}(嘛|吗|没|了没|了嘛)|你懂.{0,3}吗|你以为"
    r"|你确定.{0,6}(查过|做过|对吗|测过|真)"
    r"|为何.{0,8}(还没|还不|又|居然|不做|没做|停下|这么|那么)"
    r"|为什么.{0,8}(还没|还不|又|居然|不做|没做|停下|这么笨|那么笨)")

STRONG = ("⛔[自动进化·机器强制] Frank 这条消息带明确不满/质疑信号 —— 按历史统计他质疑时我几乎必错。"
          "本轮【先】invoke skill `postmortem-to-guard`,走完 5 步:①先认别辩解 ②归错误的【形状】"
          "③grep 查它复发过几次 ④判机器能不能防 ⑤能防的当场落成 hook/代码、不能防的记进 ~/.claude/lessons.md。"
          "⛔ 禁止先解释『其实是因为…』;禁止跳过复盘直接改。复盘落地后再回应他的具体诉求。")
SOFT = ("⚠️[语义提示] Frank 这条消息【可能】带不满(语义分落在中间带、关键字未命中,不够强判)——"
        "若你读着是针对你工作的批评/不耐烦/挖苦/失望/质疑,先 invoke skill `postmortem-to-guard` 再回应;"
        "若确是中性任务/提问/提议/给信息,正常处理即可。⛔ 别不假思索地忽略——先判一下是不是真不满。")


def _log(msg):
    # 2026-07-25:改用 guard_common.hook_log —— 单行追加(并发安全)+ 记项目/会话 + 大小轮转。
    # 原实现是「读最近300行→整个文件重写」,读写非原子,多项目并发收尾实测丢 74% 的行。
    hook_log("dissatisfaction-postmortem", msg)
def inject(ctx):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}, ensure_ascii=False))


def ledger(prompt, score, how):
    """2026-09-25 Frank:「识别不满不是核心…收益太差」⇒ 不再注入强制复盘,只把这句话记进考卷账本当考题。
    (事后识别他骂了没有,永远晚于事实闸;这个信号唯一还值钱的用途是给考卷出题。)"""
    try:
        import time as _t
        d = os.path.expanduser("~/.claude/truthgate-exam")
        os.makedirs(d, exist_ok=True)
        rec = {"ts": _t.strftime("%Y-%m-%d %H:%M:%S"), "proj": os.path.basename(os.getcwd()),
               "sid": (os.environ.get("CLAUDE_SESSION_ID") or "")[:8], "score": score, "how": how, "text": prompt[:400]}
        with open(os.path.join(d, "dissat-ledger.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    data = json.loads(sys.stdin.read())
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        _log("pass(empty)"); return
    # 语义服务(主路)
    try:
        body = json.dumps({"text": prompt}).encode()
        req = urllib.request.Request(SVC, body, {"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=1.5).read())
        # 2026-07-23 Frank 裁决:只留强制档,关掉软提示(打扰66%→30%消息,防污染各项目/防我变笨)。
        # soft 仍由服务算出、只记日志不注入;要恢复"软提示兜subtle"把下面 elif 放开即可。
        if r.get("strong"):
            _log(f"STRONG(score={r.get('score')},kw={r.get('keyword')}) :: {prompt[:50]}"); ledger(prompt, r.get("score"), "svc")
        # elif r.get("soft"):
        #     _log(f"SOFT(score={r.get('score')}) :: {prompt[:50]}"); inject(SOFT)
        else:
            _log(f"pass(soft={r.get('soft')},score={r.get('score')})")
        return
    except Exception as e:
        # fail-open: 服务不可达 → 关键字正则(退回 v2-前行为,绝不更差)
        if DISSAT.search(prompt):
            _log(f"STRONG(failopen-kw): {e}"); ledger(prompt, None, "kw")
        else:
            _log(f"pass(failopen): {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")