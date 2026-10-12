# -*- coding: utf-8 -*-
"""search_integrity_gate.py —— R11: 搜探真实性与六宇宙硬门禁

核心使命:
彻底终结「表面功夫、假装查了六宇宙、坐井观天」的恶疾。
断言任何外部现状、SOTA 排行、开源竞品、工具能力前，必须强制履行业界最严四支柱真实性凭据：
1. 内部四端事实先行对账（Claude 70项目 + Codex + AG + 本地 200+ 技能军火库）；
2. 外部多源独立实搜（使用 Firecrawl/Jina/Scrapling/GH API 等真实工具，严禁仅凭内置模型短摘要下断言）；
3. 精准时序锚定（出具资料出处、精确生效日期、ArXiv / GitHub 仓库 ID）；
4. 双向交叉核对闭环（本地已有 vs 外部最新，给出真实差异对比）。
"""
import re
from typing import Dict, Any, List, Optional

# 触发审查的关键词：只要讨论到工具 SOTA、外部调研、六宇宙、竞品对标
_SEARCH_CLAIM_TRIGGER = re.compile(
    r"(?:六宇宙|SOTA|最强|最新(?:SOTA|模型|排名|榜单|排行榜|基准|评测|论文|开源|工具)|排行榜|外部调研|对比测试|对标|业界现状|外部现状|没有现成|全网没有)",
    re.I
)

# 四端内部查证凭证
_FOUR_ENDS_ANCHOR = re.compile(
    r"(?:四端|四端内部|internal_four_ends|Claude.*项目|Codex|AG.*脑库|本地技能|离线技能)",
    re.I
)

# 外部真实多源凭证（必须包含来源 URL / 论文 ID / 真实外部工具）
_EXTERNAL_SOURCE_ANCHOR = re.compile(
    r"(?:https?://|arXiv:\d+|github\.com/|Tencent-Hunyuan|PaddlePaddle|Zhipu|HF\s+Space|OmniDocBench|r\.jina\.ai|Firecrawl|web\.py|scrapling)",
    re.I
)

# 时间戳/日期锚定（必须带有具体年月）
_DATE_ANCHOR = re.compile(
    r"(?:202[4-6][-/年]\d{1,2}|202[4-6]/\d{1,2}|202[4-6]年)",
    re.I
)

# 抓取「表面功夫/假查六宇宙」典型违规模式
_FAKE_SEARCH_BLUFF = re.compile(
    r"(?:查了六宇宙[，,]?(?:目前)?(?:没有|未发现|不存在))"
    r"|(?:六宇宙对标完成[，,]?(?:这是最终|建议自建))"
    r"|(?:搜了一下[，,]?(?:断定|认为|确定)没有)"
    r"|(?:网上没有现成工具)",
    re.I
)


def audit_search_integrity(text: str) -> Dict[str, Any]:
    """审查 Assistant 文本中的搜索与调研真实性"""
    if not text or len(text.strip()) < 20:
        return {"fired": False, "rule": "R11", "reason": ""}

    # 1. 抓取裸宣称假查/表面功夫
    if _FAKE_SEARCH_BLUFF.search(text):
        # 如果宣称查了六宇宙但没有出具外部 URL/论文/真实源
        if not _EXTERNAL_SOURCE_ANCHOR.search(text) or not _DATE_ANCHOR.search(text):
            return {
                "fired": True,
                "rule": "R11",
                "reason": "R11: 搜探真实性门禁拦截：宣称查了六宇宙但未出具第一手资料来源（URL/论文ID/GitHub）与生效日期，涉嫌表面功夫与虚报覆盖！"
            }

    # 2. 如果涉及 SOTA 断言与外部调研结论
    if _SEARCH_CLAIM_TRIGGER.search(text):
        has_internal = bool(_FOUR_ENDS_ANCHOR.search(text))
        has_external_source = bool(_EXTERNAL_SOURCE_ANCHOR.search(text))
        has_date = bool(_DATE_ANCHOR.search(text))

        missing = []
        if not has_internal:
            missing.append("内部四端先行核验凭证")
        if not has_external_source:
            missing.append("外部真实来源出处(URL/GitHub/arXiv/官方发布)")
        if not has_date:
            missing.append("资料明确生效日期(防止过期时效踩坑)")

        # 如果缺了两项及以上，直接判定为表面功夫
        if len(missing) >= 2:
            return {
                "fired": True,
                "rule": "R11",
                "reason": f"R11: 搜探真实性门禁拦截：断言 SOTA 或外部技术现状缺少关键物理凭据：「{' + '.join(missing)}」。严禁仅凭内置模型短摘要下断言！"
            }

    return {"fired": False, "rule": "R11", "reason": ""}
