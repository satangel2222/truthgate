#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""model-authenticity-gate — 严禁凭空捏造公版模型，必须以 CC Switch 本地 5 万条记录为唯一基准。

Frank 2026-09-14 痛斥（2026-09-14-C / 2026-09-14-D）：
  「凭空捏造是大罪，为何superego没有拦你或开火？深入审查，直到彻底修复根因和防止以后永远不会从犯！」
  病根：守着本地真实权威账本（~/.cc-switch/cc-switch.db 50,321 条记录）不查，
        凭大脑预训练刻板印象盲目脑补 gpt-4o, claude-3-5-sonnet, gemini-2.5-pro 等不存在的模型。

判据：
  ① 出现公版刻板印象模型名（gpt-4o, claude-3-5-sonnet, gemini-2.5-pro 等）且未进行错误复盘或引用说明；
  ② 或用户询问/讨论涉及本机 IDE 与模型分布，但整轮未曾查询过 ~/.cc-switch/cc-switch.db；
  ⇒ 满足其一立即拦停（decision: block）。

fail-open: 内部异常放行，绝不阻死交互。
"""
import sys
import os
import re
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_common  # noqa: F401  导入即记账(2026-09-16 前这道闸开没开火,统计里看不到)
except Exception:
    pass

CC_SWITCH_DB = Path.home() / ".cc-switch" / "cc-switch.db"


def _is_real_user(obj):
    """transcript 里 tool_result 也记成 type=user;只有带文字的才是 Frank 打的字。"""
    if obj.get("type") != "user":
        return False
    c = (obj.get("message") or {}).get("content", "")
    if isinstance(c, str):
        return bool(c.strip())
    return isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "text" for x in c)

# 边界不用 \b:中文紧贴时(「用gpt-4o」)\b 不成立 ⇒ 原写法会漏(2026-09-16 外审)
CLICHE_FAKE_MODELS = re.compile(
    r"(?<![A-Za-z0-9.-])(gpt-4o|gpt-4-turbo|gemini-2\.5-pro|gemini-1\.5-pro|claude-3-5-sonnet|claude-3-opus|claude-2)(?![A-Za-z0-9-])",
    re.I
)
# 这道闸防的是「编造【本机】在用某模型」,不是「提到公开模型」。
# 2026-09-16 外审:比价/选型里提 gpt-4o、问「Bot 用的是什么模型」都被硬拦(8 条里 4 条误伤)
#   ⇒ 两条判据都要求同时出现【说本机情况】的词。
LOCAL_CTX = r"(?:本机|本地|cc-switch|代理|路由|IDE|我们(?:在)?用|你(?:在|平时|一直|现在)?用|我(?:在|平时|一直|现在)?用|主力|默认模型|切换到)"
CLICHE_LOCAL = re.compile(
    LOCAL_CTX + r".{0,20}?" + CLICHE_FAKE_MODELS.pattern + r"|" + CLICHE_FAKE_MODELS.pattern + r".{0,20}?" + LOCAL_CTX,
    re.I | re.DOTALL
)

MODEL_TOPIC_RE = re.compile(
    r"(?:哪个|什么|底层|主力|实际|部署|使用|切换|调用|记录|案卷|历史|教训).*?(?:模型|IDE|cc-switch|代理)|"
    r"(?:模型|IDE).*?(?:列表|分布|统计|清单|名单|表现|走过|弯路|挨过|防范|细则)",
    re.I
)

_REFUTE = r"(?:幻觉|编造|错误|并非|不是|修正|废弃|收回|复盘|严禁|教训|所谓|阻断|门禁|拦截|非本机模型|假模型|虚假|本机没有)"
_CLICHE = r"(?:gpt-4o|claude-3-5-sonnet|gemini-2\.5-pro|3\.7|4o)"
# 2026-09-16:两种语序都认 —— 原来只认「编造……gpt-4o」,「gpt-4o 是编造的」会被误拦。
#   后置只认强词:「gpt-4o 不是很贵,推荐用它」里的"不是"不能当成纠正(那是真在推荐)。
_REFUTE_AFTER = r"(?:编造|幻觉|假模型|虚假|本机没有|不存在)"
QUOTING_HISTORIC_OR_REFUTING = re.compile(
    _REFUTE + r".*?" + _CLICHE + r"|" + _CLICHE + r".{0,30}?" + _REFUTE_AFTER,
    re.I | re.DOTALL
)

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        print(json.dumps({}))
        return

    # 防死循环:上一次收尾已经被(任何闸)拦过、这是被拦后的重答 ⇒ 不再拦(2026-09-16 前没有这道保险)
    if data.get("stop_hook_active"):
        print(json.dumps({}))
        return

    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        print(json.dumps({}))
        return

    try:
        with open(tp, "r", encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception:
        print(json.dumps({}))
        return

    user_prompt = ""
    assistant_texts = []
    assistant_blob = []

    last_user_idx = -1
    for i, l in enumerate(lines):
        try:
            obj = json.loads(l)
            if _is_real_user(obj) or '"type":"USER_INPUT"' in l:
                last_user_idx = i
                msg = obj.get("message") or {}
                c = msg.get("content", "")
                if isinstance(c, str):
                    user_prompt = c
                elif isinstance(c, list):
                    user_prompt = " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
        except Exception:
            pass

    post_lines = lines[last_user_idx + 1:] if last_user_idx >= 0 else lines[-30:]
    for l in post_lines:
        assistant_blob.append(l)
        try:
            obj = json.loads(l)
            if obj.get("type") == "assistant" or obj.get("source") == "MODEL":
                msg = obj.get("message") or {}
                content = msg.get("content") or obj.get("content")
                if isinstance(content, str):
                    assistant_texts.append(content)
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            assistant_texts.append(b.get("text", ""))
        except Exception:
            pass

    text = "\n".join(assistant_texts)
    blob_str = "\n".join(assistant_blob)

    cliche_m = CLICHE_LOCAL.search(text)
    if cliche_m:
        bad_model = next(g for g in cliche_m.groups() if g)
        if not QUOTING_HISTORIC_OR_REFUTING.search(text):
            print(json.dumps({
                "decision": "block",
                "reason": (
                    f"⛔ [model-authenticity-gate] 检测到在输出或代码中出现了公版刻板印象模型名【{bad_model}】！\n"
                    f"本机运行着 CC Switch 代理并存储有真实账本（~/.cc-switch/cc-switch.db 50,321 条记录）。\n"
                    f"铁律 2026-09-14-C 规定「严禁凭空捏造公版模型，必须以本地数据库 5 万条记录为唯一基准」。\n"
                    f"请先查询本地真实数据库（`~/.cc-switch/cc-switch.db`），根据真实调用模型进行交付！"
                )
            }, ensure_ascii=False))
            return

    is_model_topic = False
    if user_prompt and MODEL_TOPIC_RE.search(user_prompt):
        is_model_topic = True
    elif MODEL_TOPIC_RE.search(text):
        is_model_topic = True

    # 物理真实性核验: 是否真正查询了本机 OmniRoute / cc-switch 账本，或执行了联网搜索
    blob_lower = blob_str.lower()
    has_queried = bool(
        "cc-switch.db" in blob_lower or "cc_switch" in blob_lower or "cc-switch" in blob_lower or
        "20128" in blob_lower or "omniroute" in blob_lower or
        "search_web" in blob_lower or "web_search" in blob_lower
    )

    # 判据 1.1: 即使未显式提及“本机”，但涉及模型推荐/选型，且输出了公版刻板印象模型，且未查验真实源
    if CLICHE_FAKE_MODELS.search(text) and not has_queried and not QUOTING_HISTORIC_OR_REFUTING.search(text):
        if user_prompt and re.search(r"(?:推荐|什么|哪个|选型|配什么|需要|最佳|好).*?模型", user_prompt):
            bad_model = CLICHE_FAKE_MODELS.search(text).group(1)
            print(json.dumps({
                "decision": "block",
                "reason": (
                    f"⛔ [model-authenticity-gate] 严禁凭旧预训练记忆口嗨推荐公版刻板模型【{bad_model}】！\n"
                    "铁律规定：涉及模型推荐与选型，必须先查询本机总入口 OmniRoute (127.0.0.1:20128) / cc-switch 账本，或执行联网多源交叉核验！"
                )
            }, ensure_ascii=False))
            return

    if is_model_topic:
        if not has_queried and user_prompt and re.search(r"(?:哪个模型|什么模型|ide和模型|全部模型|主力模型|模型列表)", user_prompt) \
                and re.search(LOCAL_CTX, user_prompt, re.I):
            print(json.dumps({
                "decision": "block",
                "reason": (
                    "⛔ [model-authenticity-gate] 用户询问了模型/IDE相关账本，"
                    "但本轮交互中未曾查验 CC Switch 真实调用数据库（~/.cc-switch/cc-switch.db）。\n"
                    "铁律规定：涉及本机模型与路由，必须先查询真实数据库，严禁凭印象脑补！"
                )
            }, ensure_ascii=False))
            return

    print(json.dumps({}))

if __name__ == "__main__":
    main()
