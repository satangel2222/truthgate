#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""commitment-execution-gate — 跨 turn 验"我承诺了 X,之后真做了没"。

⛔ 缺口来历(2026-08-30,Frank 截图戳穿:「为何 superego 没拦你说开始跑、但是什么都没做」):
  promise-gate 只查【本轮内】有没有工具调用(acted=True ⇒ 放行),而我那 18 个 tool_use
  全是查 superego 自身(grep/Read/settings.json),**没一件碰他交代的活** ⇒
  promise-gate 物理上不可能拦下,合理但不够。

  修法(本闸): 在 Stop hook 拿 transcript_path → 扫本 session 的 assistant 文本 →
  抽"承诺了要做 X" → 再扫 X 时间点之后的 tool_use,看 X 真做了没。
  没做且超 30 分钟 → BLOCK,要求:「要么真做,要么把这条承诺收回」。

  fail-open: hook 自己崩了不拦(防止一道闸挂整段对话瘫)。

事件接入:仅用 UserPromptSubmit(清旧承诺) + PostToolUse(累积 tool 用) + Stop(扫描 + 判)。
不依赖 AssistantMessage 事件(那在 Claude Code 里目前未开放)。
"""
import json
import os
import re
import sys
import time
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "hooks" / ".commitment-state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG = Path.home() / ".claude" / "hooks" / ".commitment-execution-gate.log"

# 承诺词表(沿用 promise-gate 的 PROMISE,加 8-30 现场形)
# ⛔ 严格第一人称主语:「我」字必须紧贴承诺短语前面,不能隔着「他那个说」「他表示」
#    这类"引用他说"的句式(8-30 实测漏:「他那个说我开始跑 5 件事」误命中)。
PROMISE = re.compile(
    r"(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*我(接着|继续|再|下[一]?轮)(做|弄|查|修|跑|试|看|起)"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*我接着做"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*我继续做下去"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*我会继续"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*我自己(会|来)(做|弄|跑|查)"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*剩下(的)?我来"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*后面我来"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*我来接着"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*现在(就)?开始(跑|做|干|弄|处理)"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*开?始(跑|做|干)"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*我直接(做|跑|干|弄)"
    r"|(^|[\n。！？,，;；:：]|\*\*|\s|好的|嗯|行|那[么么]?|可以)\s*(接下来|下一步|等下|马上)[^\n。]{0,12}(我)?[^\n。]{0,8}(做|开始|动手|处理|跑)",
    re.I)

# ⛔ 2026-09-09:<no-target> 承诺的语义锚点(给 should_escalate 用,不是词表)
#   POS = 真的在把活推到以后;NEG = 不该拦的合法情形。
#   ⚠️ 关键在 NEG 第 3~5 条:【真需要 Frank 拍板/不可逆/要花钱】的事留给他,是铁律要求的正确行为,
#     不是"遗留" —— 拦它会把闸训练成背景音。
POS_DEFER = [
    "这个我下轮做",
    "剩下的留到下一轮再处理",
    "接下来我会把它做完",
    "这件事我下次再弄",
    "先这样,后面我来补上",
    "还差最后一步,下次补",
]
NEG_DEFER = [
    "我现在就做,马上动手",
    "已经做完了,而且验证过了",
    "这件事根本不需要做",
    "这个要等你拍板决定方向",
    "这是不可逆操作,必须先问过你",
    "这要花钱,得你同意才能买",
    # ⛔ 这条是自检抓出来的真误伤补的:第一版把「文档 18 处数字要不要缩——等你一个字」
    #   判成了该拦,而那是【把选择权交给他】,恰恰是铁律要求的正确行为,不是遗留。
    "要不要改由你决定,等你一句话我就动手",
    "这是内容取舍不是技术问题,你给个方向",
]

# 承诺里的【目标指纹】—— 抽出来去 tool_use 里找有没有动过这件事
# ⛔ 2026-08-31 扩展(本轮 5 件真做完 4 件、漏 1 件就是因为我承诺的"接 self-loop-gate"
#   在工具调用里是"settings.json",不在原词表里:5件事/数字/英文命令够用,但中文动宾结构
#   "接 self-loop-gate / 修某闸 / 写某测试"全部抽不出。补 2 处:①动词词表扩 ②目标名加闸名
TARGET_RE = re.compile(
    r"(?:跑|做|查|修|弄|碰|动|起|开|接[入上]?|写[进]?|补[上]?|清[理]?|跳|读|改|删|固[化]?|复[习]?|碰|摸|拉|过)(?:一下?)?\s*"
    r"((?:5|四|三|二|1)[ ]?件(?:事)?|"
    r"git\s+(?:log|diff|show)|"
    r"node\s+[\w./-]+|"
    r"[Mm]y\s+units?|"
    r"codex|"
    r"[Bb]aileys?|"
    r"\d{4}-\d{2}|"
    # 文件路径:含 py/js/json/csv/md/html/yaml/sh/cjs/mjs/ts/css/toml/ini/env/cfg/xml/log
    r"[\w./-]+\.(?:py|js|json|csv|md|html|ya?ml|sh|cjs|mjs|ts|css|toml|ini|env|cfg|xml|log)|"
    # ⛔ 2026-08-31:闸名当目标。「接 self-loop-gate / 修 pkg-install-guard / 跑 4 道闸的 1 道」
    # 8-31 v2 修:闸名后面【不一定跟 .py】——「接 self-loop-gate 进 settings.json」「修 pkg-install-guard」
    # 闸名即可成为目标,扩展名可选
    r"(?:self-loop|pkg-install|blame-check|commitment-execution|false-done|no-nagging|churn|"
    r"evidence|nudge|rootcause|prior-art|search-breadth|pipeline|critic|giveup|dropped|"
    r"show-open|unread|backtick|backslash|jargon|reference|coherence|cross-scope|"
    r"dbs[\w-]*|doctor|metrics|twostage)[\w-]*(?:\.py)?|"
    r"settings\.json|"
    # 「修 4 道闸的 1 道」「跑故障注入」「回归全绿」
    r"\d+\s*道\s*闸|故障注入|回归|regress|selftest|全绿)",
    re.I)


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def state_path(sid):
    return STATE_DIR / f"{sid}.json"


def load_state(sid):
    p = state_path(sid)
    if not p.exists():
        return {"promises": [], "recent_tool_uses": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"promises": [], "recent_tool_uses": []}


def save_state(sid, st):
    p = state_path(sid)
    try:
        p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        log(f"save_state err: {e}")


def extract_promises_from_text(text):
    out = []
    for m in PROMISE.finditer(text):
        snippet = text[max(0, m.start() - 20):m.end() + 80]
        targets = TARGET_RE.findall(snippet)
        if not targets:
            targets = ["<no-target>"]
        out.append({"at": time.time(), "snippet": snippet.strip()[:140], "targets": [t.strip() for t in targets]})
    return out


def collect_tool_uses(transcript_path):
    """从 transcript 现取本轮的 tool_use(名字 + 输入摘要)。

    ⛔ 2026-09-09 建:此前代码读的是 state 里的 `recent_tool_uses`,而那个字段**从没被写过**
       ⇒ 恒空 ⇒ 「这条承诺做了没」这个判断从建闸起就没真正生效过。
       transcript 是第一手、抹不掉,不需要依赖谁记得去写 state。
    """
    out = []
    try:
        # ⛔⛔ 2026-09-09 **刻意不用 `load_transcript_tail`** —— 它第 684 行有个
        #   `_turn_budget_blown()`「本轮拦截预算用尽 → 返回空」的防 loop 机制(9-06 加的)。
        #   本轮我亲身撞上:被闸拦多次后预算烧光 → 它返回 0 条消息 →
        #   **承诺来自 state(持久)、工具调用来自 transcript(被清空)** ⇒ 证据只剩一半 ⇒
        #   闸只看得见"你承诺了"、看不见"你做了" ⇒ **必然误拦**,而且越拦越拦得死。
        #   ⇒ 「做没做」是**事实证据**,不该受拦截预算影响。自己读尾部,零依赖。
        import os as _os
        raw = b""
        try:
            _sz = _os.path.getsize(transcript_path)
            with open(transcript_path, "rb") as _f:
                if _sz > 4_000_000:
                    _f.seek(_sz - 4_000_000)
                    _f.readline()
                raw = _f.read()
        except Exception:
            raw = b""
        msgs = []
        for line in raw.split(b"\n"):
            if not line.strip():
                continue
            try:
                msgs.append(json.loads(line.decode("utf-8", "replace")))
            except Exception:
                continue
        for m in msgs:
            if m.get("type") != "assistant":
                continue
            c = (m.get("message") or {}).get("content")
            if not isinstance(c, list):
                continue
            ts = None
            try:
                import datetime as _dt
                ts = _dt.datetime.fromisoformat(str(m.get("timestamp")).replace("Z", "+00:00")).timestamp()
            except Exception:
                pass
            for it in c:
                if isinstance(it, dict) and it.get("type") == "tool_use":
                    inp = it.get("input") or {}
                    s = inp.get("command") or inp.get("file_path") or inp.get("pattern") \
                        or inp.get("prompt") or json.dumps(inp, ensure_ascii=False)[:200]
                    out.append({"name": it.get("name") or "?", "input_str": str(s)[:300], "ts": ts})
    except Exception as e:
        log(f"collect_tool_uses err: {e!r}")
    return out


def semantic_tool_match(promise, recent_tool_uses, thresh=0.05):
    """⛔ 2026-09-09 补的另一半 —— `<no-target>` 承诺【怎么销账】。

    背景:同日我把 no-target 从「2 分钟后自动放行」改成「语义判是不是在推诿 → 是就拦」,
    结果**从一个极端翻到另一个极端**:那条「银行月结单…我下轮做」我当轮真做完了
    (167 笔落盘、看板转绿),闸却还在拦 —— 因为 no-target 根本没有销账路径。
    根因同一个:承诺是中文自然语言(「银行月结单」),工具调用是英文文件名
    (`m2u_stmt_to_bankmd.py` / `bank-md`),**字符串永远匹配不上**。
    ⇒ 这正是语义该上场的地方:把本轮工具调用摘成一段文本,问它和这条承诺像不像同一件事。

    fail 方向:语义服务挂 → intent_margin 返回 None → 本函数返回 True(=算做过了,放行)。
    与项目其他闸一致:**绝不因为语义层抽风而多拦**。
    """
    # ⛔ 2026-09-18:原来只看最后 25 次调用 —— 承诺当场兑现、之后又干了上百次别的活,
    #   证据就滑出窗口,同一条早已完成的承诺被连拦 4 轮(airbnb 入住页"补发链接")。
    #   ⇒ 看【承诺之后】的全部调用,按 25 次一组逐组比,任一组像就算兑现(最多 12 组)。
    since = promise.get("at", 0) - 60
    uses = [t for t in recent_tool_uses if t.get("ts") is None or t["ts"] >= since]
    if not uses:
        return False
    groups = [uses[i:i + 25] for i in range(0, len(uses), 25)]
    if len(groups) > 12:
        groups = groups[:11] + [uses[-25:]]
    try:
        from guard_common import intent_margin
    except Exception:
        return True                      # 拿不到语义层 → 不新增拦截
    for g in groups:
        blob = " ".join((t.get("input_str") or "")[:120] for t in g)[:512]
        if not blob.strip():
            continue
        try:
            mg = intent_margin(blob, [promise.get("snippet", "")[:200]],
                               ["闲聊 天气 今天心情不错 随便看看 无关的日常对话"])
        except Exception:
            return True
        if mg is None:
            return True                  # 服务挂/超时 → 同上
        if mg > thresh:
            return True
    return False


def find_matching_tool_use(targets, recent_tool_uses):
    """看最近的 tool_use 里有没有命中这个承诺的目标。"""
    targets_lower = [t.lower() for t in targets]
    if "<no-target>" in targets_lower and len(targets_lower) == 1:
        return None
    for tu in recent_tool_uses:
        cmd = (tu.get("input_str") or "").lower()
        # 至少一个 target 出现在 cmd 里就算匹配
        for t in targets_lower:
            if t and t != "<no-target>" and len(t) > 2 and t in cmd:
                return tu
    return None


def scan_transcript_for_promises(transcript_path, since_ts):
    """扫 transcript jsonl,找 since_ts 之后所有 assistant 文本里的承诺。"""
    if not transcript_path or not Path(transcript_path).exists():
        return []
    out = []
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("type") != "assistant":
                    continue
                ts = rec.get("timestamp") or ""
                if since_ts and ts and ts < since_ts:
                    continue
                msg = rec.get("message") or {}
                for c in (msg.get("content") or []):
                    if c.get("type") == "text":
                        out.extend(extract_promises_from_text(c.get("text") or ""))
    except Exception as e:
        log(f"scan_transcript err: {e}")
    return out


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        log(f"read payload err: {e}")
        print(json.dumps({"decision": "allow"}))
        return
    # 2026-09-06 防无限 loop:本轮被 Stop 闸拽回次数到上限就让开。
    #   实测 55 道 Stop 闸只有 64% 受回合预算管,自己读 transcript 的 12 道全绕过。
    #   安全类闸在 _BUDGET_NEVER 里永不熔断;逃生阀 SUPEREGO_NO_BUDGET=1。
    # ⛔ 2026-09-07 修:这一段原来在解析【之前】,而且用的变量名是 `data` ——
    #   本文件里根本没有 `data`,于是每次 NameError、被下面的 except 静默吞掉
    #   ⇒ **这道闸的熔断逃生阀从来没生效过**。同一个复制粘贴 bug 在
    #   scope-completeness-gate 里也有一份(同日一并修)。
    #   形状:护栏加了、但没接上线 —— 顺序错一行/变量名抄错一个,功能等于不存在,而且不报错。
    try:
        from guard_common import turn_budget_ok as _tbo
        _tp = payload.get("transcript_path")
        if _tp and not _tbo(_tp):
            return
    except Exception:
        pass

    sid = payload.get("session_id", "nosid")
    event = payload.get("hook_event_name", "Stop")
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    tool_input_str = json.dumps(tool_input, ensure_ascii=False) if isinstance(tool_input, (dict, list)) else str(tool_input)

    st = load_state(sid)

    if event == "UserPromptSubmit":
        st["promises"] = []
        save_state(sid, st)
        print(json.dumps({"decision": "allow"}))
        return

    if event == "AssistantMessage":
        # 防御性兼容:有些上游传这个事件(目前 Claude Code 没开放,但别让闸在那种环境里静默死)
        text = payload.get("text") or ""
        for c in (payload.get("message", {}) or {}).get("content", []) or []:
            if c.get("type") == "text":
                text += c.get("text", "")
        if text:
            for p in extract_promises_from_text(text):
                if not any(x.get("snippet") == p["snippet"] for x in st.get("promises", [])):
                    st.setdefault("promises", []).append(p)
            save_state(sid, st)
        print(json.dumps({"decision": "allow"}))
        return

    if event == "PostToolUse":
        st.setdefault("recent_tool_uses", []).append({
            "at": time.time(),
            "name": tool_name,
            "input_str": tool_input_str[:500],
        })
        cutoff = time.time() - 1800
        st["recent_tool_uses"] = [t for t in st["recent_tool_uses"] if t["at"] > cutoff]
        save_state(sid, st)
        print(json.dumps({"decision": "allow"}))
        return

    if event == "Stop":
        transcript_path = payload.get("transcript_path", "")
        # ⛔ 关键:不再用 transcript 灌承诺(transcript 是整场历史,会混进 8-30 那种
        #    "诊断/复述历史" 的旧文本当承诺)。承诺只能从 AssistantMessage 事件进入,
        #    state 在 UserPromptSubmit 时已清空 ⇒ 本轮 UPS 之后的 AssistantMessage
        #    才是真承诺。如果 AssistantMessage 事件不可用,退化为 transcript 增量,
        #    但需要推断本轮起点(取最后一条 user 消息的 timestamp)。
        recent_promises = list(st.get("promises", []))

        # 退路:AssistantMessage 没灌过(因为 Claude Code 还没开放这事件),
        # 才从 transcript 拿本轮承诺。判定:recent_promises 为空。
        if not recent_promises and transcript_path and Path(transcript_path).exists():
            # 找本轮起点:最后一条 user 消息的 timestamp
            last_user_ts = ""
            try:
                with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        if rec.get("type") == "user":
                            ts = rec.get("timestamp") or ""
                            if ts and ts > last_user_ts:
                                last_user_ts = ts
            except Exception as e:
                log(f"find user ts err: {e}")
            for p in scan_transcript_for_promises(transcript_path, last_user_ts):
                if not any(x.get("snippet") == p["snippet"] for x in recent_promises):
                    recent_promises.append(p)
            st["promises"] = recent_promises
            save_state(sid, st)

        all_promises = recent_promises
        # ⛔⛔ 2026-09-09 根因修复 —— `st["recent_tool_uses"]` 由 **PostToolUse 事件**填充,
        #   但本闸在 settings.json 里**只注册了 Stop**、没注册 PostToolUse ⇒ 真实会话里它恒空
        #   (回归测试之所以是绿的:测试自己用合成的 PostToolUse 事件把它喂满了 ——
        #    **测试造出了生产没有的前提**,于是这个洞被绿灯盖了 10 天)。
        #   后果比看起来严重:不只 <no-target> 销不掉,**有 target 的路径也是死的**
        #   (find_matching_tool_use 拿空列表 → 恒 None → 每条承诺都判"没做")。
        #   那条「<no-target> 2 分钟后自动放行」的兜底,实际就是在盖这个洞。
        # ⇒ 修法:**两个源取并集** —— state(接了 PostToolUse 时有、测试也靠它)
        #   ＋ transcript 现取(第一手,不依赖接线)。任一有货都算数。
        recent_tu = list(st.get("recent_tool_uses", [])) + collect_tool_uses(transcript_path)
        now = time.time()
        unfulfilled = []
        for p in all_promises:
            if p.get("done"):
                continue
            age_min = (now - p["at"]) / 60
            targets = p["targets"]
            is_no_target = (targets == ["<no-target>"])

            # 汇报已完成(有"已修/已写/已发"或"已经") → 不是承诺,跳过
            snippet_lower = p["snippet"].lower()
            if re.search(r"(已[经修发写读跑查做完]|已经|已\s|已。)", snippet_lower):
                continue
            # 结果报告(4/4 PASS / ok / 跑过 且 transcript 时间晚于承诺) → 闸时间窗内已完成
            if re.search(r"(\d+/\d+\s*PASS|ok\s+\[\d|ok\s+\d+|跑过|跑了一[轮次]|回归\s*\d|selftest\s*\d|测试绿|全绿|已在|已完成)", snippet_lower):
                continue
            # 测试样本/诊断目标("看它是否能识别 X" / "测它是不是 Y") — 不是真承诺
            if re.search(r"(看它是否|看它能|看它会不会|测[一试]它|看.*能识别|识别.*这种|试[一试看]它)", snippet_lower):
                continue
            # 汇报"我正在等/还在跑"等卡点 → 不是承诺,跳过
            if re.search(r"(还在跑|还在[等做查]|等[一它]下|稍后|先[看看])", snippet_lower):
                continue
            # 事后分析/归因/叙述已有现象 → 不是新承诺,跳过
            # 特征:动词后面跟的是「根因/原因/那刀/这一刀」这类名词短语
            # 例子:"为何...没拦...的根因是 promise-gate"、"穿透到对话末...因为"
            if re.search(r"(没拦|没匹[配中]?|穿透|根因|发生在这 session|发生在这对话|当时就|因为\s*(?:promise|commitment|gate|他那个))", snippet_lower):
                continue
            # 叙述"然后我跑了..."型 — 描述当时行为/现象,不是新承诺
            if re.search(r"(然后我跑了|然后跑了\d+|当时跑了|那是跑|跑了\s*(?:18|20|个)\s*(?:Read|Grep|tool))", snippet_lower):
                continue
            # 描述闸自身的修复/装配/状态 — 不是对用户做承诺
            if re.search(r"(今天只承诺了|只承诺了\s*\d+\s*条|还不到\s*THRESHOLD|不?到阈值|不拦\s*。|新闸\s*\*\*?\w+-?\w+\.py|怎么修的|已装新闸|故障注入\s*\d)", snippet_lower):
                continue
            # 事后解释现象:"这就是我说 X 后停在那里的原因"、"这就是为什么...的原因"
            if re.search(r"(这就是(说|为什么|为什么)|这就是.*的原因|这就是.*的结果)", snippet_lower):
                continue
            # "存进去" / "记下来" 这类**记笔记**指令 → 不是去查目标本身
            if re.search(r"(存进去|记[一下录]|写进[笔记]|归[档类]到|收[到入]这[里次轮])", snippet_lower):
                continue

            # 刚说(< 1 分钟):不拦,给时间落地
            if age_min < 1:
                continue

            # <no-target> 承诺:2 分钟以上自动放(无法比对,要么已做要么没目标)
            if is_no_target:
                if age_min > 2:
                    # ⛔⛔ 2026-09-09 Frank「为何每轮你都要遗留东西下轮做,而我 superego 没有拦?」
                    #   查出来这一行就是【自我豁免后门】,而且方向正好反了:
                    #   TARGET_RE 抽的是文件名/英文命令这类【指纹】,所以
                    #     · 「我下轮跑 booking_waf.py」→ 抽得出 target → 会被查
                    #     · 「银行月结单落后 2 个月…我下轮做」→ <no-target> → **2 分钟后自动放行**
                    #   ⇒ 越是用自然语言说的真承诺,越抽不出目标,越被放过。
                    #   实证(本会话 649:1212 真实数据):PROMISE 命中 2 条,两条 targets 全是
                    #   ['<no-target>'],于是整轮 allow —— 我那条「银行月结单我下轮做」就这么穿过去了。
                    # ⇒ 修法不补词表(Frank 2026-07-27 已否掉那条路),改用 should_escalate 语义补位:
                    #   关键字抽不出目标时,问语义「这是不是在把活推到以后」。
                    #   fail-open:语义服务挂 → 返回 False → 行为与改动前完全一致。
                    try:
                        from guard_common import should_escalate as _esc
                        if _esc(p["snippet"], POS_DEFER, NEG_DEFER):
                            # ⛔ 两步都要过才拦:①这话确实是在推诿 ②本轮工具调用里【也确实没做】。
                            #   少了第②步就会从「永远放行」翻成「永远拦」——2026-09-09 我先犯了一次:
                            #   那条承诺当轮真做完了(167 笔落盘、看板转绿),闸照样拦,因为
                            #   no-target 压根没有销账路径。
                            if semantic_tool_match(p, recent_tu):
                                p["done"] = True     # 销账后不再复查(证据以后可能滑出尾部读取范围)
                                save_state(sid, st)
                                log(f"no-target 承诺语义上已被本轮工具调用覆盖,销账: {p['snippet'][:50]}")
                            else:
                                unfulfilled.append(p)
                                log(f"no-target 承诺:语义判为推到以后且工具调用里没做 ⇒ 拦: {p['snippet'][:50]}")
                    except Exception as _e:
                        log(f"no-target 语义补位失败(fail-open): {_e!r}")
                    continue
                # 1~2 分钟的 <no-target>:降级警告而非 BLOCK
                msg = (
                    "⚠️ 承诺执行闸(<no-target>澄清):你说「"
                    + p["snippet"][:60]
                    + "」,2 分钟内没看到工具调用,请确认具体要做哪件事,或回复『下轮再说』取消。"
                )
                print(json.dumps({"decision": "allow", "warning": msg, "reason": msg}, ensure_ascii=False))
                return

            # 60 分钟以上:自动放(要么已做要么失效)
            if age_min > 60:
                continue

            if not find_matching_tool_use(targets, recent_tu):
                unfulfilled.append(p)

        if unfulfilled:
            msg = (
                "⛔ 承诺执行闸: 本 session 说了要做以下事,但 30 分钟内没看到对应工具调用 ——\n"
                + "\n".join(f"  · 「{p['snippet']}」 (目标: {', '.join(p['targets'])})" for p in unfulfilled[:3])
                + "\n→ 选一个: (1) 现在真去做; (2) 把这条承诺收回改说『下轮再说』; (3) 解释为什么根本不用做。"
                + "\n→ 跑过的 tool: " + ", ".join(sorted(set(t["name"] for t in recent_tu[-10:])))
            )
            log(f"BLOCK sid={sid} unfulfilled={len(unfulfilled)} targets={[t for p in unfulfilled[:3] for t in p['targets']]}")
            print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
            return

        print(json.dumps({"decision": "allow"}))
        return

    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"main crash: {e}")
        print(json.dumps({"decision": "allow"}))
