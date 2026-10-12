#!/usr/bin/env python3
"""Stop hook: 抓「同一操作反复失败、还在换理论没去 diff 现成/造参照物」(形状:先测/先diff现成 · lessons 已第 15 次)。

2026-07-22 血泪:myTNB 账单 PDF 逆向,`PrintPDF('370030..')` 那串 hex 我判定「没成功流可比」→
一路瞎猜解码、换 5 个理论(token编码/客户端AES/服务端上下文)猜 20+ 轮全 500,却不肯用 Playwright
把浏览器成功下载跑一次 diff。Frank 逼我跑一次真实成功流 → 3 秒破案(hex 原样发、不解码)。
全局铁律「有参照物就 diff,没参照物才猜」早写着,照犯 → 判断类软规则拦不住,上一个抓【行为痕迹】的闸。

这不是"读心"(判不了'我此刻在猜')——是抓可计算的粗症状:近窗口里同一签名失败 ≥3 次(或总失败 ≥6 且零成功)
且本轮没成功收尾 → 捅一下「别换理论,去跑一次能成功的路径造参照物再 diff」。backstop,不是解药。

安全设计(照 giveup-guard / false-done-gate):
- fail-open:任何异常一律放行。
- 每 session 只捅一次(marker 文件按 session_id),避免长调试里每轮唠叨。
- 只拦一次:【我自己】拦过才不再拦(per-gate 标记,见 guard_common.self_blocked_this_turn);别的闸拦过不影响我,避免死循环。
- 只读 transcript + 打印决策,从不碰代码/文件。
- 本轮已成功收尾(final text 有 ✅/成功/200/%PDF/通过) → 免拦(刚修好别捅)。
- 每次留一行日志到 reference-diff-guard.log(可核验在跑)。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:            # ⛔ 必须带兜底:原来是裸 import —— guard_common 一坏,这道闸第一行就炸,
    from guard_common import hook_log, is_real_user_msg# 下面精心写的 fail-open 降级桩全成了到不了的死代码(外部critic抓到)
except Exception:
    def is_real_user_msg(m):            # guard_common 挂了时的保守桩:只排 tool_result
        c = (m.get('message') or {}).get('content')
        return m.get('type') == 'user' and not (isinstance(c, list) and any(
            isinstance(x, dict) and x.get('type') == 'tool_result' for x in c))
    def hook_log(*a, **k):
        pass
import sys, json, re, os, time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import strip_doc, SUCCESS_RE as DELIVER_RE
except Exception:
    import re as _re
    def strip_doc(t):
        return t or ""
    DELIVER_RE = _re.compile(r"(?!x)x")   # never matches

HERE = os.path.dirname(os.path.abspath(__file__))
# (原来这里有个 LOG 常量 —— 全文件零引用的死代码,早就改用 hook_log 了。2026-09-07 删)

# 窗口:只看最近这么多个工具结果(thrash 是近期行为,别翻整场)
WINDOW = 16
SAME_SIG_FAILS = 3     # 同一签名失败 ≥ 这个数(高精度路径)
TOTAL_FAILS = 6        # 或 窗口内总失败 ≥ 这个数 且 零成功(粗 thrash 路径)

# 工具结果里的失败/成功标记(成功优先:同时出现算成功,避免把"200 但附带 error 字样"误判失败)
FAIL_RE = re.compile(
    r"Internal Server|Traceback|Exception"
    r"|(?<![A-Za-z])[Ee]rror(?![A-Za-z])|(?<!0 )(?<!no )(?<!zero )\bfail(?:ed|s|ing|ure)\b|\bFAIL\b|❌|not found|拒绝?|报错|(?<!无)失败|超时|无权"
    # 2026-07-25 审计(finding: 空搜索/裸数字误判):裸 40x/50x 会误伤良性日志('processed 507 files'),
    # 只在紧邻 HTTP/status/状态码/箭头等状态上下文时才算 HTTP 错误;强错误词(Internal Server/Exception…)照旧独立命中。
    r"|(?:HTTP|status(?:[_ -]?code)?|状态码?|响应码?|返回码?|→|->)\W{0,4}(?:50[0-9]|40[13])\b",
    re.I)
# regex-sanity: ok — 本职就是找『成功/passed』字样
SUCCESS_RE = re.compile(
    r"%PDF|\b200\b|✅|✓|成功|通过|\"ok\"\s*:\s*true|application/pdf|已.*(通|成功)"
    r"|Research complete|Found \d+ (stories|repos|issues|items|videos)|拿到|返回真"
    # 2026-07-25 审计(finding: 无英文成功词):TDD/构建 red→red→red→green('1 passed'/'tests pass'/'build succeeded')
    # 那一轮绿灯要算成功,才能把该签名移出 max_same、不再把已解决当瞎试。
    r"|\b\d+\s+passed\b|\bpass(ed|es)\b|\btests?\s+pass(ed|es)?\b|\bsucce(ss|ed)\w*", re.I)
# 2026-07-24 审计 finding#10:否定盲——"未成功/no repos found/0 results" 里的 成功/repos 被当成功,
# 失败被记成成功 → 同签名连败永不累积、thrash 永不触发。加否定守卫剔除。(并已去掉裸 repos\b)
NEG_SUCCESS = re.compile(
    r"未成功|没(有)?成功|不成功|未通过|没通过|失败|no\s+(repos|results|matches|items)|0\s+(repos|results|matches)"
    r"|not\s+found|无(结果|匹配|数据)|没(有)?(结果|找到|匹配)|empty|零(结果|命中)"
    # 2026-07-25 R2审计(finding: 英文失败+成功词共存被判成功):修法#1 给 SUCCESS_RE 加了英文成功词后,
    # 'N failed, M passed'/'was not successful'/'build failed but ... passed' 因『成功优先』被当 success,
    # 同签名连败永不累积 → pytest 反复失败这个旗舰 thrash 场景失守。补对应英文失败 veto。
    # ⚠️外科纪律:只 veto【非零】failed(`[1-9]\d*\s+failed`)与失败动词短语,放过 '0 failed'/'2 passed, 0 failed'
    #   这类纯绿(否则会把通过的测试误当 thrash = 第三个洞)。
    r"|[1-9]\d*\s+failed|failed\s+(?:to|but|because|with|due|when|:)|\bnot\s+success\w*", re.I)
# 2026-07-24:工具正常日志(过滤/去重/富集)不是"失败",别当 thrash 的失败计数
NOISE_RE = re.compile(r"filtered|removed|low-engagement|prefix filter|Enriching|backfilled|scored cards|Relevance floor|listing discovery", re.I)
# 本轮最终文本里的"我已经搞定了"信号 → 免拦
DONE_TEXT_RE = re.compile(r"✅|成功|端到端(通|跑通)|全.*200|%PDF|已.*(打通|修好|跑通|通了|全通)", re.I)


try:
    from guard_common import trig   # 2026-07-28 C3:BLOCK 日志要记【惹祸的原句】
except Exception:
    def trig(s, n=120): return (s or "")[:n]

def _log(msg, ctx=""):
    # 2026-07-28 C3:加 ctx 透传【惹祸的原句】。此前 BLOCK 只记判据类别
    #   (如 "BLOCK(claimed+code+no-critic)"),事后无法判断是真拦还是误伤 ——
    #   要复算就得回去翻 transcript。trig() 早就在 guard_common 里,只是没接上。
    # 2026-07-25:改用 guard_common.hook_log —— 单行追加(并发安全)+ 记项目/会话 + 大小轮转。
    # 原实现是「读最近300行→整个文件重写」,读写非原子,多项目并发收尾实测丢 74% 的行。
    hook_log("reference-diff-guard", msg, ctx)
def _result_text(content):
    """把一个 tool_result 的 content 抠成一段文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict):
                out.append(c.get("text", "") if c.get("type") == "text" else json.dumps(c, ensure_ascii=False))
            else:
                out.append(str(c))
        return "\n".join(out)
    return json.dumps(content, ensure_ascii=False) if content is not None else ""


def _sig_from_tooluse(name, inp):
    inp = inp or {}
    cmd = inp.get("command") or inp.get("query") or inp.get("url") or inp.get("file_path") or ""
    if not cmd:
        cmd = json.dumps(inp, ensure_ascii=False)
    return f"{name}:{str(cmd)[:60]}"


def analyze(msgs):
    """回放 transcript,建 tool_use_id→签名,再收集(按时间序)工具结果的(签名,失败,成功)。"""
    id2sig = {}
    for m in msgs:
        if m.get("type") != "assistant":
            continue
        for c in (m.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                id2sig[c.get("id")] = _sig_from_tooluse(str(c.get("name", "")), c.get("input"))
    results = []
    for m in msgs:
        if m.get("type") != "user":
            continue
        for c in (m.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_result":
                txt = _result_text(c.get("content"))
                neg = bool(NEG_SUCCESS.search(txt))
                success = bool(SUCCESS_RE.search(txt)) and not neg          # 否定盲:未成功/no repos 不算成功(finding#10)
                noise = bool(NOISE_RE.search(txt))
                # 硬失败 = 真错误信号(HTTP 5xx/Exception/报错/失败…)。
                # 软失败 = 空/无命中的探索结果(neg-only,没有硬错误):换 pattern 找不到是正常探索,不是 thrash——
                #   只在【同一签名重复】时才累积(见 decide),不进"总体 thrash"计数(finding: 空搜索被当失败)。
                hard = (not success) and bool(FAIL_RE.search(txt)) and not noise
                soft = (not success) and (not hard) and neg and not noise
                results.append((id2sig.get(c.get("tool_use_id"), "?"), hard, soft, success))
    return results


def final_text(msgs):
    # 最后一个真实 user(非 tool_result)之后的 assistant 文本
    last_user = -1
    for i, m in enumerate(msgs):
        if m.get("type") != "user":
            continue
        content = (m.get("message") or {}).get("content")
        # is_real_user_msg 同时排除 tool_result 和【系统注入的伪 user 消息】(后台 Agent 完成通知)。
        # 原来只排 tool_result ⇒ 通知被当成新一轮开始 ⇒ 本轮已做的事全失效 ⇒ 反复开火。
        if is_real_user_msg(m):
            last_user = i
    parts = []
    for m in msgs[last_user + 1:]:
        if m.get("type") != "assistant":
            continue
        for c in (m.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
    return "\n".join(parts)


def decide(results, ftext):
    if DONE_TEXT_RE.search(ftext or "") or DELIVER_RE.search(ftext or ""):
        return False, "final-text-done"      # 本轮已成功收尾/已交付,别捅
    win = results[-WINDOW:]
    if not win:
        return False, "empty-window"
    hard_fail = sum(1 for _, h, _, _ in win if h)     # 只有硬错误才进"总体 thrash"路径(空搜索不算)
    total_ok = sum(1 for _, _, _, s in win if s)
    # 同签名失败(且该签名窗口内无成功):硬失败与软失败(同一 query 重复找不到)都累积——重复同一操作 = thrash
    sig_fail = {}
    sig_ok = set()
    for sig, h, sf, s in win:
        if s:
            sig_ok.add(sig)
        elif h or sf:
            sig_fail[sig] = sig_fail.get(sig, 0) + 1
    max_same = max((n for sig, n in sig_fail.items() if sig not in sig_ok), default=0)
    if max_same >= SAME_SIG_FAILS:
        return True, f"same-sig-fail={max_same}"
    if hard_fail >= TOTAL_FAILS and total_ok == 0:
        return True, f"thrash hard_fail={hard_fail},ok=0"
    return False, f"ok(hard_fail={hard_fail},ok={total_ok},max_same={max_same})"


# per-gate 防死循环(见 guard_common.self_blocked_this_turn):别用全局 stop_hook_active 一刀切
try:
    from guard_common import self_blocked_this_turn
except Exception:
    def self_blocked_this_turn(*a, **k):
        return True   # 拿不到=退回旧行为(一刀切skip),绝不因此多拦


def main():
    data = json.loads(sys.stdin.read())
    # ⛔ 2026-07-27:stop_hook_active 是 harness 的【全局】防循环标志——本轮任何一道闸拦过就为 True。
    #   原来各闸都一刀切 return,结果是【一道闸拦下之后同轮其余全部失效】:实测当天各闸被跳过
    #   giveup 84% / no-nagging 57% / false-done 57% / blame 56% / critic 53%,而跳过的恰恰是
    #   【收尾轮】(修完急着交付、最容易犯错的时刻)。防死循环只需要"我自己别连拦两次",与别的闸无关。
    if not data.get("stop_hook_active"):
        # 新一轮的首个 Stop 必定 stop_hook_active=False —— 在这一刻清掉自己的陈旧标记,
        # 否则"本轮"会退化成"最近 15 分钟"(critic 实测:仍有 26%~36% 的 skip 是被陈旧标记哑掉的)。
        self_blocked_this_turn("reference-diff-guard", turn_start=True)
    elif self_blocked_this_turn("reference-diff-guard"):
        _log("skip(self-blocked-this-turn)"); return
    sid = str(data.get("session_id", "")).replace("/", "_").replace("\\", "_")
    marker = os.path.join(HERE, f".refdiff.{sid}.fired") if sid else None
    if marker and os.path.exists(marker):
        _log("skip(already fired this session)"); return
    # ⛔ 2026-07-26:每个 session 留一个 marker 且【从不清理】—— 实测已攒 6 个,每天开新会话就多一个。
    #   7 天前的 session 早已结束,它的 marker 再也不会被任何人读到,可以安全删。
    #   只按 mtime 判过期:当前会话刚写的那个动不了(条件不成立就不删)。
    try:
        import glob as _glob
        cutoff = time.time() - 7 * 86400
        for _old in _glob.glob(os.path.join(HERE, ".refdiff.*.fired")):
            if os.path.getmtime(_old) < cutoff:
                os.remove(_old)
    except OSError:
        pass
    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        _log("skip(no transcript)"); return
    try:
        from guard_common import load_transcript_tail
        msgs = load_transcript_tail(tp)   # 只读尾部,别每回合重读整份历史(Frank卡顿真凶,实测省5.5s→<0.1s)
    except Exception:
        msgs = []
        for ln in open(tp, encoding="utf-8").read().splitlines():
            try:
                msgs.append(json.loads(ln))
            except Exception:
                continue
    trigger, why = decide(analyze(msgs), final_text(msgs))
    if trigger:
        if marker:
            try: open(marker, "w").write(time.strftime("%Y-%m-%d %H:%M:%S"))
            except Exception: pass
        _log(f"BLOCK({why})", trig(str(why), 160))
        reason = (
            "⛔ 参照-diff 闸:你近几轮在同一操作上反复失败、还没成功,却像在不停换理论/换参数瞎试"
            f"({why})。按全局铁律「有参照物就 diff;没参照物就【去造一个】再 diff」——停止换理论,"
            "先跑一次【能成功的路径】拿 ground-truth:浏览器把成功流走一遍(Playwright)、或跑现成能通的"
            "工具/旧版本/线上服务,再把它和你失败的请求逐字段 diff,差异即答案(myTNB PDF 就是这样 3 秒破案)。"
            "若你确在正常迭代、下一步本就要这么做(或这些失败是预期的探测),忽略本闸。"
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    else:
        _log(f"allow({why})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")
