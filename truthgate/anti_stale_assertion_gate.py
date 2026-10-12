# -*- coding: utf-8 -*-
"""anti_stale_assertion_gate.py —— 反过时权重妄断与多源检索自证门禁 (Anti-Stale Weights & Multi-Source Research Gate)

核心使命:
  彻底根除「模型仅凭内部过时知识盲目下结论、不查外部最新开源/大厂进展、闭门造车自建轮子」的恶疾。
  凡做出技术排他性断言（如“目前没有现成”、“业界无法实现”、“只能自建/重构”、“某某工具不支持”）：
  必须在工具历史中出具真实的外部多源检索凭据（WebSearch、GitHub 调研、arXiv、本地逆向工具库或本地脑库查阅）。
"""
import re
import json
from typing import Dict, Any, List, Optional

# 触发审查的排他性/技术断言模式
STALE_ASSERTION_PATTERN = re.compile(
    r"(?:全网没有|没有现成|业界没有|开源社区没有|目前无法实现|只能由我们自建|只能自建|只能重构|找不到现成|没有公开接口|"
    r"不可能实现|目前唯一解法|闭源无法获取|目前官方不支持|市面上没有|完全没有现成方案)",
    re.I
)

# 历史教训与复盘豁免
_QUOTING_HISTORIC = re.compile(r"(?:^#\s*教训|教训案例库|形状\s*20\d\d|历史案卷|历史教训|复盘)")

# 合法外部查证工具清单 (多源检索、脑库、逆向、外部探针)
VALID_RESEARCH_TOOLS = (
    "search_web",
    "read_url_content",
    "deep_research",
    "ag_archive",
    "truth",
    "multi_source_research",
    "scrapling",
    "revtools",
    "github",
    "arxiv"
)


def check_anti_stale_assertion_violation(
    text: str,
    tool_history: Optional[List[Dict[str, Any]]] = None,
    user_prompt: str = ""
) -> Optional[str]:
    """审查是否存在凭借过时权重擅下技术排他性断言的行为"""
    if not text or len(text.strip()) < 15:
        return None

    # 1. 结构性豁免：复盘与教训引用
    if _QUOTING_HISTORIC.search(text):
        return None

    # 用户明确指示不要搜索时放行
    if user_prompt and re.search(r"(?:不用搜|不要搜索|无需查网|别查了)", user_prompt, re.I):
        return None

    # 2. 检查是否命中了排他性/技术可行性妄断
    m = STALE_ASSERTION_PATTERN.search(text)
    if not m:
        return None

    culprit_phrase = m.group(0)

    # 3. 检查本轮工具调用中是否有真实的外部检索或本地逆向工具查阅
    has_valid_research = False
    if tool_history:
        for t in tool_history:
            t_name = str(t.get("name") or "").lower()
            t_args = str(t.get("args") or t.get("input") or "").lower()

            # 工具名包含合法检索或逆向工具
            if any(vt in t_name for vt in VALID_RESEARCH_TOOLS):
                has_valid_research = True
                break

            # 命令行调用包含 deep_research / gh search / ag_archive / curl / scrapling
            if "run_command" in t_name or "bash" in t_name or "powershell" in t_name:
                if any(kw in t_args for kw in ("deep_research", "ag_archive", "gh search", "scrapling", "revtools", "q.js")):
                    has_valid_research = True
                    break

    if not has_valid_research:
        return (
            f"[TruthGate 物理拦截 - anti-stale-assertion-gate] 🚨 触发『反过时权重妄断与零检索断言』硬红线！\n"
            f"嫌疑断言: 「{culprit_phrase}」\n"
            f"物理依据: 你的模型知识停留在很久以前，但全世界每天都有大佬开源新工具、大厂每天在迭代新接口，很多闭源能力也可以通过免费白嫖、逆向包壳或现成轮子实现。\n"
            f"严禁在零检索、零查证的情况下仅凭老旧权重断言『没有现成/只能自建/无法实现』！\n"
            f"自愈指引: 请立即调用外部多源检索（如 search_web、GitHub 检索、py -3 ~/.gemini/antigravity/scripts/deep_research.py 或查阅本地逆向工具库），客观对比最新现成方案后再做技术决策！"
        )

    return None
