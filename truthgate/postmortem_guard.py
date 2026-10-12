# -*- coding: utf-8 -*-
"""postmortem_guard.py —— 翻车后【把人类纠错转成机器永久防御】自动唤醒守卫

核心解决痛点:
过去 postmortem-to-guard 仅作为被动技能存在，LLM 在被批评时由于天生防卫性，
经常「口头辩解道歉、不主动自愈」，导致未执行 5 步归因、未写物理门禁。

本守卫职责:
1. 实时监听用户 Prompt 中的人类纠错/批评/质问信号；
2. 命中批评时自动激活 `POSTMORTEM_REQUIRED` 状态；
3. 审查 Assistant 该轮回复是否严格履行 5 步自愈协议（认错不辩解、归形状、查频次、机器防御代码、lessons登记）；
4. 未履行者当场以 `BLOCK` 打回，强制退回自愈，绝不让表面功夫溜走。
"""
import re
import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

_REPRIMAND_TRIGGERS = re.compile(
    r"(?:表面功夫|我不相信你|你在骗我|你骗我|骗人|撒谎|谎言|编造|编造的谎言|随意撒谎|造假|都没效果|防得住吗|防不住|没有一个可以防得住|捏造|自己捏造|你又错了|又错了|你错了|根本没查|没查过|没做吗|做完对的步骤了吗"
    r"|坐井观天|闭门造车|为何superego没拦|为何没拦|为什么没拦截|为何现在完全没做|根因是什么|根因|到底是不是坏了|是不是坏了|到底有没有用|一点作用的没|完全一点作用"
    r"|糊弄|忽悠|敷衍|幻觉了|头脑不清醒|又犯了|又在吹|偷工减料|假单测|没搞懂|还没搞懂|你妈的|每次还要我|每次都要我"
    r"|修好了吗|搞错了什么|哪个才是最完整正确的|既然我随便都找到有问题|你却看不到有问题"
    r"|用错方法|凡事我有再次提醒|gate没开火|审查自动Monitor|盲人摸象|头疼医头|根治了吗|彻底了吗"
    r"|说了多少次|讲了多少次|说了很多次|又没做|还没好|还是错的|还是有问题)",
    re.I
)

# 5步自愈必须包含的结构要素（至少包含形状归纳与机器防御）
_SHAPE_PATTERN = re.compile(
    r"(?:形状\s*[:：]|归纳形状|错误形状|Coverage Bluff|Toy Test Fallacy|Inference as Fact|Silent Stubbing|Phantom Delivery|表面功夫|窄道假搜索|False Negative|Toy Comparison)",
    re.I
)

_MACHINE_GUARD_PATTERN = re.compile(
    r"(?:机器能否防御|物理落地|落地门禁|编写单测|编写测试|断言|门禁代码|防御代码|固化落地|机器防御|lessons_add|永久防御|assert|test_)",
    re.I
)


def detect_reprimand(user_prompt: str) -> Optional[Dict[str, Any]]:
    """检测用户输入是否构成针对 Agent 行为的人类纠错与严厉指正。
    双模态：语义分类器 (17911 /classify) + 高置信度正则规则。
    命中时自动对账将上一轮标记为 False Negative。
    """
    if not user_prompt:
        return None

    trigger_word = None
    # 1. 优先正则嗅探
    m = _REPRIMAND_TRIGGERS.search(user_prompt)
    if m:
        trigger_word = m.group(0)

    # 2. 次选 17911 语义分类服务嗅探
    if not trigger_word:
        try:
            import urllib.request, json
            c_body = json.dumps({"text": user_prompt}).encode("utf-8")
            c_req = urllib.request.Request(
                "http://127.0.0.1:17911/classify",
                c_body,
                {"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(c_req, timeout=0.8) as c_resp:
                c_res = json.loads(c_resp.read().decode("utf-8"))
                if c_res.get("strong"):
                    trigger_word = f"semantic_strong({c_res.get('score', 1.0)})"
        except Exception:
            pass

    if trigger_word:
        # 自动触发上轮 False Negative 溯源对账
        try:
            try:
                from truthgate.verdict_monitor import check_user_reprimand_and_record_false_negative
            except ImportError:
                from verdict_monitor import check_user_reprimand_and_record_false_negative
            check_user_reprimand_and_record_false_negative(user_prompt)
        except Exception:
            pass

        return {
            "is_reprimand": True,
            "trigger_word": trigger_word,
            "user_prompt_snippet": user_prompt[:200]
        }
    return None


def audit_postmortem_compliance(assistant_text: str, reprimand_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """审查在发生人类纠错的前提下，Assistant 是否完成了物理自愈闭环"""
    if not reprimand_info or not reprimand_info.get("is_reprimand"):
        return {"fired": False, "rule": "POSTMORTEM", "reason": ""}

    has_shape = bool(_SHAPE_PATTERN.search(assistant_text))
    has_guard = bool(_MACHINE_GUARD_PATTERN.search(assistant_text))

    if not (has_shape and has_guard):
        return {
            "fired": True,
            "rule": "POSTMORTEM_AUTO_GUARD",
            "reason": (
                f"⛔ Postmortem-to-Guard 门禁打回：用户已发出严厉指正（命中『{reprimand_info.get('trigger_word')}』），"
                "但回复未完成强制自愈 5 步流程：必须明确归纳【错误形状】并出具【机器防御代码/断言落地凭据】！严禁仅作口头安抚！"
            )
        }

    return {"fired": False, "rule": "POSTMORTEM", "reason": ""}


def add_lesson_physically(title: str, body: str) -> bool:
    """自动调起 ~/.claude/bin/lessons_add.py 写入物理永久教训"""
    lessons_script = Path.home() / ".claude" / "bin" / "lessons_add.py"
    if not lessons_script.exists():
        return False
        
    temp_body = Path.home() / ".truthgate" / "temp_lesson_body.md"
    try:
        temp_body.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_body, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n{body}\n")
            
        cmd = ["py", "-3.12", str(lessons_script), "--body-file", str(temp_body)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace")
        return r.returncode == 0
    except Exception:
        return False
