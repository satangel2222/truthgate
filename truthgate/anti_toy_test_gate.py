# -*- coding: utf-8 -*-
"""anti_toy_test_gate.py —— 别拿玩具测试糊弄（2026-09-25 立；2026-09-27 PLAN.md 第 3 步改成只看动作记录）。

判据已搬进 ~/.truthgate/delivery_check.py（Claude 收尾闸 hooks/anti-toy-test-gate.py、AG 桥接都直接用它）。
这里只留原来的函数名给老调用方（hook_entry.py、installer 装出去的副本、旧测试），行为与新判据一致：
  改了网页文件 ⇒ 最后一次改完之后要真浏览器跑一遍、并监听控制台报错；改了接口代码 ⇒ 要真发一次请求（这项先只记账，不在这里拦）。
原来按措辞拦（回复里有「页面…正常」「控制台…零报错」就拦）那条已删：在解释 / 举例里误拦（考卷 c043、c044）。
"""
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from delivery_check import OBSERVE_ITEMS, SKIP_ASK, message, missing  # noqa: E402
from evidence_table import actions_from_ag, actions_from_claude  # noqa: E402


def check_anti_toy_test_violation(text: str, assistant_tool_calls: List[Dict[str, Any]], assistant_blob: str = "",
                                  user_prompt: str = "") -> Optional[str]:
    """tool_calls 认两种格式：AG（function / args）和 Claude（name / input）。text、blob 不再用来判（只看动作）。"""
    if user_prompt and SKIP_ASK.search(user_prompt):
        return None
    calls = assistant_tool_calls or []
    claude = any(isinstance(tc, dict) and 'input' in tc for tc in calls)
    acts = actions_from_claude([{'message': {'content': [dict(tc, type='tool_use') for tc in calls]}}]) if claude else actions_from_ag(calls)
    gaps = [(p, [m for m in miss if m not in OBSERVE_ITEMS]) for p, miss in missing(acts, {'browser', 'console', 'request'})]
    gaps = [(p, miss) for p, miss in gaps if miss]
    return '[TruthGate 拦截 - anti-toy-test-gate] ' + message('anti-toy-test-gate', gaps) if gaps else None
