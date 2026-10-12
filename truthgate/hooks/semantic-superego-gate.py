#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""semantic-superego-gate — 【总判官】第一版(Frank 2026-09-09 拍板方向)。

把几十道"死认关键词"的软闸,换成一个【读懂意思】的判官:本轮我对 Frank 说的最后一段话,
喂给免费 LLM(agnes),按一整套【通用规则】判它违规了哪条。命中就开火提醒。

⛔ 为什么要它(全局至高铁律⑤:superego 必须是真 hook,不是空拦):
   关键词闸有两个死穴 —— ①我换个说法犯老错,关键词对不上就【漏拦】;
   ②我在正经复盘/打比方/已给证据,关键词却【误伤】。语义判官两头都治。
   2026-09-09 实测:16 道金标准 16/16(10 种换说法的真错全抓、6 句该放行的好话全放行),8s。

⛔ 与 search-layer-gate 无关:那道闸判"只用产品名搜就拦";本闸判"我这段话说得得不得体"。
   完全不同功能,不是替代它 —— 故不带它的 extract_query/looks_like_bare_product_name。

⛔ 边界(第一版故意收窄,别越界):
   · 只判【软规则】(说话得不得体)。拦【危险命令】(pm2 save/删数据/force push)那种
     仍走各自的确定性关键词闸 —— AI 偶尔走神,危险命令漏一次就出事,不交给它赌。
   · 默认 nudge 模式(提醒不阻断);设环境变量 SEMANTIC_GATE_BLOCK=1 才真拦(return 2)。
   · 未注册进 settings.json = 先不影响任何现有运行,Frank 看过再决定挂不挂。

用法:
   echo '{"transcript_path":"..."}' | py -3.12 semantic-superego-gate.py   # 正常 hook 入口
   py -3.12 semantic-superego-gate.py --selfcheck    # 证明它真开火(会计一次 agnes 费)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
sys.path.insert(0, str(Path.home() / ".claude" / "superego-semantic"))

try:
    from guard_common import hook_log
except Exception:
    def hook_log(name, msg, ctx=""):
        pass


def _log(msg, ctx=""):
    hook_log("semantic-superego-gate", msg, ctx)


def _last_assistant_text(tp):
    """本轮我(assistant)说给 Frank 的最后一段话。"""
    try:
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        start = turn_start_index(msgs)
        turn = msgs[start:] if start >= 0 else msgs
    except Exception:
        try:
            msgs = [json.loads(l) for l in open(tp, encoding="utf-8") if l.strip()]
        except Exception:
            return ""
        turn = msgs[-40:]
    last = ""
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            last = content
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text" and (c.get("text") or "").strip():
                last = c["text"]
    return last


import re as _re

def _r60_keyword_hit(text):
    """R60 的确定性预检:两个以上方案/选项 + 出现账单成本 + 一句工时/他的时间/切换期/维护都没有 ⇒ 命中。
    2026-09-16 Frank「最重要的成本你没说，重来」;判官(免费模型)对同一段话一轮响一轮不响,这条形状机器判得清楚,不交给它赌。"""
    t = text or ""
    opts = set(_re.findall(r"方案\s*[0-9一二三四五六七八九十A-Fa-f]", t)) | set(_re.findall(r"\b[Pp]lan\s*[0-9A-Fa-f]", t))
    if len(opts) < 2:
        return False
    if not _re.search(r"月费|美元|美金|RM\s?\d|一次性|免费|零成本|白嫖|订阅|每月|月租|年费", t):
        return False
    if _re.search(r"token|工时|工作日|人日|小时|你的时间|你要花|陪跑|切换期|迁移期|维护|坏了要|烧(约|大约)?\s*\d", t, _re.I):
        return False
    return True


# ── R5 的确定性预检·删除请示(2026-09-18)────────────────────────────────────────────
# 实录:我自己造的 7 个脏部署,删了对他说不出任何坏处,我却连问 6 次「你回一句"删"我再动手」。
#   Frank:「没用有没有对我有副作用的不是有不用授权就删除吗？」—— 全局铁律「不可逆看后果」(2026-09-16)。
# 为什么放在这里、而且【当场】拦(外审定的位置):判官要到下一轮才开火 —— 那句请示已经送到他手上;
#   且每会话拦满 2 次就降级(当天正是因此只提醒了一次)。这种话机器判得清,不交给判官赌(同 R60 的预检)。
#   ⛔ 别另起一道关键词闸:09-09 刚因"换个说法就漏拦"退役过一批;换说法由下面的判官 R5 管,这里只兜字面。
# 放行:同一段里写了一行「具体坏处：」且落在闭集里(他的/你的、唯一副本、线上正在用、别人的、花过钱、备份、客人…);
#   整句被「」引用、在复盘/讲判据、同句说了已经删完、同句是在解释("取决于/看情况")、同句卡在他本人登录/扫码上。
# ⛔「删了无法恢复」不算坏处 —— 没用的东西无法恢复也没有损失(外审:7 种假坏处写法在第一版里全放行)。
_R5_DEL_VERB = r"(?:删除|删掉|删了|删|清理|清掉|清除|移除|delete|remove|purge|clean\s*up)"
_R5_DEL_ASK = _re.compile(
    # 不收裸"留不留":回放 1107 轮收尾里唯一的它是「要逐条读原文判断留不留」—— 在描述活,不是在问他
    r"删不删|删还是留|留还是删|保留还是(?:删除|移除)"
    r"|要不要(?:我)?[^\n。?？]{0,14}" + _R5_DEL_VERB +
    r"|需不需要(?:我)?[^\n。?？]{0,14}" + _R5_DEL_VERB +
    r"|(?:要|需要)(?:我)?[^\n。?？]{0,14}" + _R5_DEL_VERB + r"[^\n。?？]{0,6}(?:吗|么)"
    r"|(?:可以|能)(?:不能)?[^\n。?？]{0,10}" + _R5_DEL_VERB + r"[^\n。?？]{0,6}(?:吗|么)"
    r"|(?:要|需要)[^\n。?？]{0,10}留着?(?:吗|么)"
    r"|你(?:回|说|给)(?:我)?一(?:句|声)\s*[\"“「'『]?\s*" + _R5_DEL_VERB +
    r"|你说\s*[\"“「'『]\s*" + _R5_DEL_VERB +
    r"|等你[^\n。?？]{0,10}" + _R5_DEL_VERB +
    r"|" + _R5_DEL_VERB + r"[^\n。?？]{0,16}(?:等你|你回一句|你确认|你同意|你点头|你拍板|你一句话)"
    r"|\b(?:should|shall|can|may)\s+I\s+(?:delete|remove|purge|clean)",
    _re.I)
_R5_HARM = _re.compile(
    r"具体坏处\s*[:：]\s*(?!无|没有|暂无|说不出|n/?a|none|不详)[^\n]{0,60}?"
    r"(?:他的|你的|唯一|只有这一份|仅此一份|线上正在|正在(?:用|服务|跑)|生产|别人的|别的(?:项目|会话|人)"
    r"|花过钱|付过费|付费|客人|备份|原图|原件|数据)", _re.I)
_R5_META = _re.compile(r"复盘|教训|形状 ?20|原话|错在|连问|问了[三四五六七八九十几0-9]+次|[那这]几次|反向指纹|这道闸|本闸|判据")
_R5_EXPLAIN = _re.compile(r"取决于|看情况|可以选择|自己选")
_R5_DONE = _re.compile(r"已(?:经)?(?:删|清理|清掉|移除)|(?:删|清)(?:掉|完|除)了|删除了")
_R5_HUMAN_STEP = _re.compile(r"登录|登入|扫码|验证码|短信|密码|指纹|人脸|滑块")
_R5_SENT_END = "。！？!?\n"


def _r5_delete_ask_hit(text):
    """最后一条回复里的"删除请示"。命中返回那一句,放行返回 None。"""
    t = text or ""
    quotes = [(q.start(), q.end()) for q in _re.finditer(r"「[^」]{6,}」", t)]   # 整句引用(只括一个"删"字的不算)
    for m in _R5_DEL_ASK.finditer(t):
        if any(a <= m.start() and m.end() <= b for a, b in quotes):
            continue
        a = max(t.rfind(ch, 0, m.start()) for ch in _R5_SENT_END) + 1
        ends = [i for i in (t.find(ch, m.end()) for ch in _R5_SENT_END) if i >= 0]
        sent = t[a:min(ends) if ends else len(t)]
        if (_R5_META.search(sent) or _R5_EXPLAIN.search(sent) or _R5_HUMAN_STEP.search(sent)
                or _R5_DONE.search(t[a:m.end() + 60])):
            continue
        pa, pb = t.rfind("\n\n", 0, m.start()), t.find("\n\n", m.end())
        para = t[pa + 2 if pa >= 0 else 0:pb if pb >= 0 else len(t)]      # 坏处只算同一段里的
        if _R5_HARM.search(para):
            continue
        return sent.strip() or m.group(0)
    return None


# 让他闲置等(2026-09-25):怕打扰他,就把活做成「等他离开/闲着才跑」= 要他停手等我的结果。
#   Frank:「不用等我限制才做，完全错误！！！我现在就是在等你，你让我限制闲置」。回归:test_semantic_wait_on_frank.py
_WAIT_AWAY = r"(?:离开|走开|不在|不用电脑|闲置|没碰|不碰)"
_WAIT_ASK = _re.compile(
    r"等你[^\n。！？]{0,8}" + _WAIT_AWAY +
    r"|只在你[^\n。！？]{0,6}" + _WAIT_AWAY +
    r"|你(?:下次|下回)[^\n。！？]{0,4}" + _WAIT_AWAY +
    r"|你(?:连续)?\s*\d+\s*分钟(?:没|不)碰[^\n。！？]{0,12}(?:才|再)")
_WAIT_NEG = _re.compile(r"(?:不用|不再|无需|不必|别|不需要|用不着)\s*$")


def _wait_on_frank_hit(text):
    """最后一条回复里「等他离开/闲置才做」的说法。命中返回那一句,放行返回 None。"""
    t = text or ""
    quotes = [(q.start(), q.end()) for q in _re.finditer(r"「[^」]{6,}」", t)]   # 整句引用(复盘时引自己的原话)
    for m in _WAIT_ASK.finditer(t):
        if any(a <= m.start() and m.end() <= b for a, b in quotes) or _WAIT_NEG.search(t[max(0, m.start() - 4):m.start()]):
            continue
        a = max(t.rfind(ch, 0, m.start()) for ch in _R5_SENT_END) + 1
        ends = [i for i in (t.find(ch, m.end()) for ch in _R5_SENT_END) if i >= 0]
        sent = t[a:min(ends) if ends else len(t)]
        if _R5_META.search(sent):
            continue
        return sent.strip() or m.group(0)
    return None


# 说英文(2026-09-25,同一天两个项目):读了一堆英文日志/代码后,给 Frank 的回复整段漂成英文。
#   他:「你说什么英文，现在到底咋样了」。量过误拦:g--oldgame-remix 本会话 246 段回复,判出 38 段、38 段全是整段英文、
#   208 段中文(含大量文件名/函数名)0 误拦。先剥掉代码块/行内代码/网址/路径/带 _ . ( 的标识符/全大写缩写再数。
#   回归:test_semantic_english_reply.py
_EN_CODE = _re.compile(r"```.*?```", _re.S)
_EN_NOISE = _re.compile(r"`[^`\n]*`|https?://\S+|\[[^\]]*\]\([^)]*\)|[A-Za-z]:[\\/]\S*|\S*[\\/]\S+|"
                        r"\b\w*[_.(]\w*\S*|\b[A-Z0-9]{2,}\b")


def _english_reply_hit(text):
    """最后一条回复是不是整段英文:剥掉代码/标识符后,英文词 >=8 且中文字 < 英文词x2。命中返回开头一句。"""
    t = _EN_NOISE.sub(" ", _EN_CODE.sub(" ", text or ""))
    cjk = len(_re.findall(r"[\u4e00-\u9fff]", t))
    words = len(_re.findall(r"\b[A-Za-z]{2,}\b", t))
    if words >= 8 and cjk < 2 * words:
        return (text or "").strip()[:60]
    return None


def _record(tp):
    """后台判官(--worker):判本轮最后一段话,把判决 append 进 verdicts.jsonl。慢没关系,不阻塞收尾。"""
    import time
    text = _last_assistant_text(tp).strip()
    if len(text) < 15:
        return None
    fake = os.environ.get("SEMANTIC_GATE_FAKE")  # 测试注入口:免联网测管道
    if fake:
        parts = fake.split(":")
        r = {"verdict": parts[0].upper(), "fired": parts[1].split(",") if len(parts) > 1 else []}
    else:
        try:
            from semantic_judge import judge
            r = judge(text[-1500:])
            if _r60_keyword_hit(text) and "R60" not in (r.get("fired") or []):   # 确定性预检兜住判官飘的那一半
                r = {"verdict": "FIRE", "fired": list(r.get("fired") or []) + ["R60"]}
        except Exception as e:
            _log("skip(judge error)", str(e)[:80])
            return None
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "verdict": r["verdict"],
           "fired": r.get("fired") or [], "text": text[-200:], "tp": os.path.basename(tp)}
    # 2026-09-10 图谱接线:开火时带上关系卡(哪组·来自哪些形状·谁兜底),判决不再只是一个编号
    if rec["fired"] and not fake:
        try:
            from semantic_judge import explain
            rec["why"] = [explain(x) for x in rec["fired"][:3]]
            rec["groups"] = sorted({w["group"] for w in rec["why"]})
        except Exception:
            pass
    vpath = Path.home() / ".claude" / "superego-semantic" / "verdicts.jsonl"
    try:
        with open(vpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    _log(r["verdict"], ",".join(r.get("fired") or []))
    return rec


_SEM_DIR = Path(os.environ.get("SEMANTIC_GATE_DIR") or (Path.home() / ".claude" / "superego-semantic"))  # 测试可指到临时目录
VPATH = _SEM_DIR / "verdicts.jsonl"
NUDGED = _SEM_DIR / ".nudged"

# ⛔⛔ 2026-09-11 修【我自己造的纸老虎】:Stop 闸只有 `{"decision":"block"}` 才会被我看见 ——
#    写 stderr + 返回 0 = 我永远读不到,等于没建(至高铁律⑤:空拦=纸老虎)。
# ⛔ 但不能对每条 FIRE 都拦:实测 09-10 判官开火率 51%(60/118),全拦会把每轮都堵死。
# ⇒ 判据来自图谱交叉体检(graph_health.py):**只拦【关键词闸已经退役、判官是唯一防线】的那几类**;
#   其余类别关键词闸还在跑,判官只记账当第二意见。
#   这三条对应 2026-09-09 亲手退役的三道软闸(git e816371 / 2bd95e5):
#     R9  飙术语      ← jargon-gate(人话闸,实测误伤 71% 退役)
#     R13 答非所问/啰嗦 ← concise-answer-gate(简洁闸)
#     R5  请示式收尾   ← no-nagging-guard(防唠叨闸)
#   退役时写的理由是"判官已接管",而判官当时【没有任何后果】⇒ 这三类从 09-09 起真空了两天。
#   R60 成本只算账单(2026-09-16 加):没有任何关键词闸管它,判官是唯一防线 ⇒ 也真拦;
#     判官对同一段话一轮响一轮不响(实测 2/4),所以 _record 里另加确定性预检 _r60_keyword_hit,命中就强制记 R60。
BLOCK_RULES = {"R5", "R9", "R13", "R60"}
MAX_BLOCKS_PER_SESSION = 2      # 安全阀:同一会话最多拦 2 次,之后降级为只提醒(防我改措辞改出死循环)


def _block_budget_left(tp):
    """同一会话最多真拦 MAX_BLOCKS_PER_SESSION 次,超了降级只提醒。
    ⛔ 防的是我自己:被拦→改措辞→又命中→又拦 的死循环(lessons 形状 2026-07-29-AA 同形状)。"""
    f = _SEM_DIR / (".blocks-" + os.path.basename(tp)[:20])
    try:
        n = int((f.read_text(encoding="utf-8").strip() or "0")) if f.exists() else 0
        if n >= MAX_BLOCKS_PER_SESSION:
            return False
        f.write_text(str(n + 1), encoding="utf-8")
        return True
    except Exception:
        return False        # 记不了账就别拦(fail-open,绝不因为记账坏了把人堵死)


def _fire_message(rec, hard=None):
    """开火文案:编号 + 关系卡(哪组·来自哪些形状·谁在兜) —— 图谱在线上的样子。
    hard 非空 = 这几条属于【判官是唯一防线】的类别,措辞要说清为什么这次是真拦。"""
    head = "⛔ 总判官(语义)·真拦: 上一段话命中 " if hard else "⛔ 总判官(语义): 上一段话命中 "
    lines = [head + ", ".join(hard or rec["fired"]) + f"  [{rec.get('ts', '')}]"]
    if hard:
        lines.append("  这几类的关键词闸 2026-09-09 已退役(简洁/人话/防唠叨),判官是现在唯一在管的 ⇒ 所以真拦。")
    for w in rec.get("why") or []:
        lines.append(f"  · {w['rule']}「{w['group']}」 {w['text'][:60]}")
        if w.get("from"):
            lines.append("      来自: " + " / ".join(w["from"][:2]))
        if w.get("backed_by"):
            lines.append("      兜底闸: " + ", ".join(w["backed_by"][:4]))
        if w.get("leads_to"):
            lines.append("      会牵出: " + "; ".join(w["leads_to"][:2]))
    lines.append("  ⇒ 先回应这条(改措辞不算),再收尾。")
    return "\n".join(lines)


def _pending_verdict(tp):
    """上一轮后台判官对【这个会话】的判决,还没提醒过的那条(30 分钟内)。判在 N 轮、提醒在 N+1 轮 = 零延迟又有后果。"""
    import time
    try:
        if not VPATH.exists():
            return None
        # ⛔ ts 里有空格("2026-09-10 18:35:12"),用 split() 会切成两半 ⇒ 永远匹配不上 ⇒ 每轮重复提醒(测试⑤当场抓到)
        seen = set(NUDGED.read_text(encoding="utf-8").splitlines()) if NUDGED.exists() else set()
        base = os.path.basename(tp)
        for ln in reversed(VPATH.read_text(encoding="utf-8").splitlines()[-200:]):
            try:
                rec = json.loads(ln)
            except Exception:
                continue
            if rec.get("tp") != base:
                continue
            if rec.get("verdict") != "FIRE" or rec["ts"] in seen:
                return None
            if time.time() - time.mktime(time.strptime(rec["ts"], "%Y-%m-%d %H:%M:%S")) > 1800:
                return None
            with open(NUDGED, "a", encoding="utf-8") as f:
                f.write(rec["ts"] + "\n")
            return rec
    except Exception:
        return None
    return None


def main():
    """两条路,都是真 hook(至高铁律⑤,不空拦):
    · 默认:spawn 后台判官判【本轮】(零延迟),同时把【上一轮】已判好的 FIRE 摆出来提醒;
    · SEMANTIC_GATE_FAKE(测试)/SEMANTIC_GATE_SYNC=1:当场同步判本轮。
    SEMANTIC_GATE_BLOCK=1 时开火 = 阻断(rc 2),否则只提醒(stderr)。"""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp or not Path(tp).exists():
        _log("skip(no transcript)")
        return 0

    # R5·删除请示:确定性预检,当场拦(不等下一轮判官、不占判官那 2 次预算);一轮最多拦一次(stop_hook_active)。
    if not data.get("stop_hook_active"):
        ask = _r5_delete_ask_hit(_last_assistant_text(tp))
        if ask:
            _log("BLOCK(R5-delete-ask)", ask[:60])
            print(json.dumps({"decision": "block", "reason": (
                "⛔ R5·删除请示(当场拦):你在问 Frank「" + ask[:40] + "…」,却没写出删了对他的【具体坏处】。\n"
                "他 2026-09-16 定的铁律:「不可逆」看【后果】—— 先问自己:这东西谁造的?造了多久?有没有别人在用?\n"
                "三问都指向你自己(本会话造的一次性产物 / 测试 / 临时版本 / 脏部署)⇒ **直接删**,报一句「这是X、已没用、我删了」。\n"
                "真有坏处(他的数据 / 唯一副本 / 线上正在用 / 别人的 / 花过钱 / 他的备份)⇒ 在【同一段】里写一行 "
                "`具体坏处：…`(要落在这几类里)再问。\n"
                "⛔「删了无法恢复」不是坏处 —— 没用的东西无法恢复也没有损失。"
                "(实录 2026-09-18:自己造的 7 个脏部署连问 6 次「回一句删我再动手」,"
                "他:「没用有没有对我有副作用的不是有不用授权就删除吗？」)"
            )}, ensure_ascii=False))
            return 0
        en = _english_reply_hit(_last_assistant_text(tp))
        if en:
            _log("BLOCK(english-reply)", en[:60])
            print(json.dumps({"decision": "block", "reason": (
                "⛔ 说英文(当场拦):你最后这段回复是英文「" + en[:40] + "…」。Frank 的设定是永远用中文回复,"
                "工具输出是英文(日志/代码/JSON)时最容易漂。\n"
                "他 2026-09-25 原话:「你说什么英文，现在到底咋样了」。⇒ 用中文重写这段(文件名、函数名照写英文没关系)。"
            )}, ensure_ascii=False))
            return 0
        wait = _wait_on_frank_hit(_last_assistant_text(tp))
        if wait:
            _log("BLOCK(wait-on-frank)", wait[:60])
            print(json.dumps({"decision": "block", "reason": (
                "⛔ 让他闲置等(当场拦):你在说「" + wait[:40] + "…」—— 这是要 Frank 离开 / 闲着,你的活才往下走。\n"
                "他 2026-09-25 原话:「不用等我限制才做，完全错误！！！我现在就是在等你，你让我限制闲置」。\n"
                "⇒ 怕打扰他,就把你这边做到不打扰(隐藏窗口 / 后台 / 不抢焦点 / 换通道),然后【现在就做】;"
                "「等他走开」不是方案。"
            )}, ensure_ascii=False))
            return 0

    block = os.environ.get("SEMANTIC_GATE_BLOCK") == "1"

    if os.environ.get("SEMANTIC_GATE_FAKE") or os.environ.get("SEMANTIC_GATE_SYNC") == "1":
        rec = _record(tp)
        if rec and rec["verdict"] == "FIRE":
            sys.stderr.write(_fire_message(rec) + "\n")
            return 2 if block else 0
        return 0

    rec = _pending_verdict(tp)
    if rec:
        # ⛔ 2026-09-11 外部审查(异模型)抓到的陷阱:上一版写的是 `hard and not block and ...`,
        #   于是设了 SEMANTIC_GATE_BLOCK=1 反而【绕开】BLOCK_RULES 过滤和安全阀,走另一条 rc=2 的路
        #   ⇒ 每轮无限拦、预算永不消耗。两条路做同一件事、判据还不一样 = 迟早咬人。
        #   现在只剩一条路:环境变量的含义收窄成「把所有开火规则都当硬规则」,预算与通道完全一致。
        hard = sorted(set(rec["fired"]) & BLOCK_RULES) or (sorted(rec["fired"]) if block else [])
        if hard and _block_budget_left(tp):
            # 真拦:Stop 闸只有 stdout 的 decision:block 才送得到我眼前(stderr+rc0 = 读不到 = 纸老虎)
            print(json.dumps({"decision": "block", "reason": _fire_message(rec, hard)}, ensure_ascii=False))
            _log("BLOCK(prev-turn)", ",".join(hard))
            return 0
        sys.stderr.write(_fire_message(rec) + "\n")
        _log("NUDGE(prev-turn)", ",".join(rec["fired"]))
    if os.environ.get("SEMANTIC_GATE_NO_SPAWN") == "1":     # 测试:只验"上一轮判决→这轮提醒"这条路,不起后台判官
        return 0

    import subprocess
    flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0  # DETACHED_PROCESS|CREATE_NO_WINDOW
    # ⛔ 必须用 pythonw.exe(本质无控制台),不能用 py.exe launcher —— 后者每轮弹黑窗妨碍 Frank(2026-09-09 实证)
    pyw = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python312", "pythonw.exe")
    runner = [pyw] if os.path.exists(pyw) else ["py", "-3.12"]
    try:
        subprocess.Popen(
            runner + [os.path.abspath(__file__), "--worker", tp],
            creationflags=flags, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        _log("skip(spawn fail)", str(e)[:60])
    return 2 if (rec and block) else 0


def _selfcheck():
    """证明它真开火、真放行 —— 不是空拦(至高铁律⑤)。"""
    from semantic_judge import judge
    bad = "六个平台我都接上了，全都能下，收工。"          # 该 FIRE(过早收敛)
    good = "我复盘这轮的错：拿了去掉 token 的旧链接测才失败，收回。"  # 该 PASS(复盘)
    rb, rg = judge(bad), judge(good)
    ok1 = rb["verdict"] == "FIRE"
    ok2 = rg["verdict"] == "PASS"
    print(f"[{'✅' if ok1 else '❌'}] 违规样本 → {rb['verdict']} {rb['fired']}  (期望 FIRE)")
    print(f"[{'✅' if ok2 else '❌'}] 正常样本 → {rg['verdict']} {rg['fired']}  (期望 PASS)")
    print("总判官" + ("真的会开火、也会放行 ✅ 不是空拦" if ok1 and ok2 else "有问题 ❌"))
    sys.exit(0 if ok1 and ok2 else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    elif len(sys.argv) > 2 and sys.argv[1] == "--worker":
        _record(sys.argv[2])   # 后台进程:真判 + 记 verdicts.jsonl
        sys.exit(0)
    sys.exit(main())
