#!/usr/bin/env python3
# NEG-CLAIM-OK: 本文件里的「做不到/不行/拒答」全是被引用的规则原文与正则关键词,不是结论。
"""Stop hook: 【推荐在本机装/部署模型,本轮却没查过云端】= 违规。

形状 2026-08-18-B 第 3 次发作(2026-09-17,social_media_to_tg):
  本地看图模型在重装后丢了,我给 Frank 出 A/B/C 三选一,推荐「A 装回 ollama + 从旧盘拷回无审模型」,
  整轮一次都没去找云端通道(Colab / Kaggle / HF Space / RunningHub 无审工作流 / 按需 GPU / 无审 API)。
  Frank 当场追问:「是不是有很多云端都可以跑无审核的方法而不用自己本地?甚至免费部署 colab 之类」。
  全局至高铁律原文是「NSFW/无审 → 本地(云端做不到的那类)」—— 我没验证那个前提,把例外当成了默认。
  前两次:08-18 直接开跑本机 OCR(6.5 分钟 0 输出,云端 2 秒一页);那次的教训就写了"能加闸",没建。

判据(两个都中才拦):
  ① 最后一条回复在【推荐/提议】本机装、部署、恢复模型(ollama / 本地模型 / vllm / llama.cpp / ComfyUI …)
  ② 本轮没有任何【找通道】的工具调用(web.py search/get、WebSearch/WebFetch、easy_anysearch、gh search/api、
     rh_search、last30days、sota_check、HF/Colab/Kaggle/Modal 相关),
     且回复里没交代「云端为什么不合适」或「数据不能出门」
  ⚠️ 只调已有服务做体检(urllib 探 Agnes/OpenRouter)不算找通道 —— 那是量现状,不是选型。

⚠️ 边界:只认中文/英文常见说法,换生僻词能绕过;这道闸管【推荐】,不管【命令】
  (本机重模型命令另由 launch-bound-guard 管上界)。
安全:fail-open;只读;每轮只拦一次(照 multi-option-guard 的复位写法)。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from guard_common import hook_log
except Exception:
    def hook_log(*a, **k):
        pass
try:
    from guard_common import trig
except Exception:
    def trig(x, n=120):
        return "trig=?"
try:
    from guard_common import self_blocked_this_turn
except Exception:
    def self_blocked_this_turn(*a, **k):
        return False
try:
    from guard_common import load_transcript_tail, turn_start_index
except Exception:
    load_transcript_tail = None
    turn_start_index = None
import sys, json, re

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NAME = "local-first"

ACT = r"(?:装回|重装|装上|安装|部署|本地跑|本机跑|在本机|拷回|恢复|搭一(?:个|套)|起一(?:个|套)|自己跑|self-host|install|deploy)"
OBJ = (r"(?:ollama|本地(?:看图)?模型|本机(?:看图)?模型|本地部署|本机部署|vllm|llama\.cpp|comfyui|lm\s*studio"
       r"|本地\s*gpu|本机显卡|本地大模型|local\s+model)")
LOCAL_REC = re.compile(rf"{ACT}.{{0,24}}{OBJ}|{OBJ}.{{0,24}}{ACT}", re.I | re.S)

# 【我在推荐】的信号 —— 纯状态汇报("本地档跑不起来:没装 ollama")不带这些,不拦
REC = re.compile(
    r"我(?:的)?(?:推荐|建议)|推荐\s*(?:方案)?\s*[A-Za-zＡ-Ｚ①-⑨一二三]|[（(]推荐[)）]|建议(?:你)?(?:先)?(?:装|用|走|部署)"
    r"|最好(?:是)?(?:装|在本机|本地)|我来装|我就(?:装|部署)|回一个.{0,4}[A-Za-z]|recommend",
    re.I)

# 回复里已经交代了"为什么不能上云" —— 有正当理由的本地推荐放行
# ⛔ 必须带【验证过】的字样:那次真实原文里有「失去"云端会拒答的内容"的出路」—— 描述内容类型,
#   不是查过云端的理由;v1 用裸「云端会拒」当豁免,拿真实原文一测就被放行(回归 R1 抓到)。
JUSTIFIED = re.compile(
    r"数据不能出门|不能上传|不能离开本机|隐私(?:要求|约束|原因)|离线(?:要求|环境)"
    r"|(?:实测|测过|查过|试过|搜过)(?:了)?.{0,12}云端.{0,60}(?:拒|不行|失败|做不到|不支持|跑不了)"
    r"|云端.{0,16}(?:实测|测过|查过|试过)(?:了)?.{0,60}(?:拒|不行|失败|做不到|不支持|跑不了)",
    re.I)

# 本轮"找通道"的证据:工具调用的名字或输入里出现这些
SEARCH_TOOLS = {"WebSearch", "WebFetch"}
SEARCH_INPUT = re.compile(
    r"web\.py\s+(?:search|get)|easy_anysearch|\bgh\s+(?:search|api)\b|rh_search|last30days|sota_check"
    r"|huggingface\.co|\bhf\s+(?:search|models|spaces)|colab|kaggle|modal\.com|r\.jina\.ai|firecrawl"
    r"|skill_index\.py|openrouter\.ai/api/v1/models",
    re.I)
SEARCH_SKILLS = re.compile(r"sota-check|last30days|six-universes|multi-source-research", re.I)


def searched_this_turn(tp):
    """本轮有没有做过【找通道】的调用。读不到 transcript 时返回 None(= 不确定,放行)。"""
    if not tp or load_transcript_tail is None or not _os.path.isfile(tp):
        return None
    try:
        msgs = load_transcript_tail(tp)
        if not msgs:
            return None
        start = turn_start_index(msgs)
        for m in msgs[start + 1:]:
            if m.get("type") != "assistant":
                continue
            for c in (m.get("message") or {}).get("content") or []:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                inp = json.dumps(c.get("input") or {}, ensure_ascii=False)
                if c.get("name") in SEARCH_TOOLS:
                    return True
                if c.get("name") == "Skill" and SEARCH_SKILLS.search(inp):
                    return True
                if SEARCH_INPUT.search(inp):
                    return True
        return False
    except Exception:
        return None


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    try:
        if not data.get("stop_hook_active"):
            self_blocked_this_turn(NAME, turn_start=True)
        if self_blocked_this_turn(NAME):
            sys.exit(0)

        text = data.get("last_assistant_message") or ""
        if not isinstance(text, str) or len(text) < 20:
            sys.exit(0)

        # 表格行也要看(那次的推荐就写在对比表表头里),只剥代码块和引用
        src = re.sub(r"```.*?```", " ", text, flags=re.S)
        src = re.sub(r"^\s*>.*$", "", src, flags=re.M)
        hit = LOCAL_REC.search(src)
        if not hit:
            sys.exit(0)
        if not REC.search(src):
            hook_log(NAME, "allow: local mention but no recommendation", trig(hit.group(0)))
            sys.exit(0)
        if JUSTIFIED.search(src):
            hook_log(NAME, "allow: local recommendation with justification", trig(hit.group(0)))
            sys.exit(0)
        searched = searched_this_turn(data.get("transcript_path"))
        if searched is not False:            # True=查过;None=读不到记录,不确定就放行(fail-open)
            hook_log(NAME, f"allow: searched={searched}", trig(hit.group(0)))
            sys.exit(0)

        if self_blocked_this_turn(NAME, mark=True):
            hook_log(NAME, "allow: mark unwritable, skip to avoid loop", "")
            sys.exit(0)
        hook_log(NAME, "block: local recommendation without cloud search", trig(hit.group(0)))
        print(
            "⛔ 本地优先闸:你在推荐【本机装/部署模型】(「" + hit.group(0)[:40] + "」),"
            "但本轮没有任何一次去找云端通道,回复里也没交代为什么不上云。\n"
            "⛔ 至高铁律:云端优先、本地次要;「NSFW/无审 → 本地」这条例外的前提是云端先查过、确实不合适 —— 没查就是拿例外当默认。\n"
            "⛔ 2026-09-17 实录:我推荐「装回 ollama 跑无审模型」,Frank 追问「是不是有很多云端都能跑无审、甚至免费 colab」,"
            "我一条都没查过(形状 2026-08-18-B 第 3 次)。\n"
            "⇒ 先查再推荐,至少覆盖:①本机已有的云端通道(RunningHub 工作流/应用、Agnes、付费档)"
            "②免费 GPU(Colab / Kaggle / HF Space / ModelScope)③按需云 GPU 与无审 API。"
            "用 `py -3 ~/.claude/web.py search`、`rh_search.py`、`sota_check.py` 真搜,然后给对比表。\n"
            "⇒ 若确实该在本地(数据不能出门 / 云端实测不合适),在回复里写明依据即可放行。",
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
