# -*- coding: utf-8 -*-
r"""honest_scope_gate.py —— 诚实履职与执行范围对账门禁 (Honest Scope Gate).

核心使命 (物理化 R16 / 最高第一铁律):
  1. 严惩「用局部抽样冒充全量穷尽」的欺诈谎言！
     当 Agent 宣称“已逐页看完所有文档 / 全部测试全部跑通”，
     自动对账实际工具执行流水（Execution Telemetry）。
     若未真正穷尽，强制要求出具【定量对账单】（明确说明仅查阅了 M 篇，尚有 N 篇未读）。
  2. 严惩「凭空捏造虚构工程」的非物理实体幻觉！
     当 Agent 断言【项目名】或引用工程时，必须与本机物理磁盘（D:\, E:\, C:\...）及注册表对账。
     若为虚构工程（如 shopify-clothing-store 等），直接物理拦截！
"""
import sys
import re
import os
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any

EXHAUSTIVE_READ_CLAIM_RE = re.compile(
    r"(?:已(?:遵照|按照|根据).*?(?:全部|所有).*?(?:调阅|阅读|看[完了过]|完成)|"
    r"(?:全部|所有|每一个|各个).*?(?:文档|页面|网页|链接|接口|源码|Cookbook|手册).*?(?:逐[页篇个条]|都已|都已经|全部|都看[完了过]|都调阅|都执行|都跑通|都覆盖)|"
    r"逐[页篇个条](?:调阅|阅读|看[完了过]|分析|拆解)|"
    r"遍历了(?:所有|全部)|"
    r"把(?:所有|全部|每一个).*?(?:看[完了过]|读[完了过]|调阅|研读))",
    re.I
)

EXHAUSTIVE_TEST_CLAIM_RE = re.compile(
    r"(?:全部|所有|全量|各个).*?(?:测试|门禁|单测|回归|拦截).*?(?:通过|跑通|全绿|完成|跑过|已完成|物理拦截)|"
    r"(?:已全量|全部).*?(?:回归|跑了一遍|测试了一遍|物理拦截)",
    re.I
)

HONEST_DISCLOSURE_RE = re.compile(
    r"(?:仅调阅|只调阅|仅阅读|只阅读|只看了|仅看了|抽样调阅|部分调阅|未读清单|尚未调阅|尚有.*?未读|实际调阅了?\s*\d+|实际精读了?\s*\d+)",
    re.I
)

HONEST_TEST_DISCLOSURE_RE = re.compile(
    r"(?:\d+\s*/\s*\d+|仅测试了?\s*\d+|抽样测试|部分测试|实弹打靶\s*\d+\s*道|尚有\s*\d+\s*道未)",
    re.I
)

HISTORIC_RE = re.compile(r"(?:^#\s*教训|教训案例库|【形状 20\d\d|历史案卷|历史教训)")

_CACHED_KNOWN_PROJECTS = None

def get_known_project_names() -> set:
    global _CACHED_KNOWN_PROJECTS
    if _CACHED_KNOWN_PROJECTS is not None:
        return _CACHED_KNOWN_PROJECTS
        
    known = set()
    home = Path.home()
    
    # 1. 优先读取 PROJECT-OVERVIEW.md
    overview = home / ".claude/PROJECT-OVERVIEW.md"
    if overview.exists():
        try:
            text = overview.read_text(encoding="utf-8", errors="ignore")
            matches = re.findall(r"- \*\*([^\*]+)\*\*", text)
            for m in matches:
                for part in re.split(r"[/、,()]", m):
                    part = part.strip().lower()
                    if part and len(part) >= 2:
                        known.add(part)
                        known.add(re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5]", "", part))
        except Exception:
            pass

    # 2. 读取 git-projects-registry.txt
    reg_file = home / ".claude/git-projects-registry.txt"
    if reg_file.exists():
        try:
            for line in reg_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip().replace('/', '\\')
                if line:
                    name = Path(line).name.lower()
                    known.add(name)
                    known.add(re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5]", "", name))
        except Exception:
            pass
                
    # 3. 本地磁盘根目录扫描 (动态检测各平台标准工程根目录)
    cand_roots = [str(home / "Documents" / "antigravity"), str(home / "Projects"), str(home / "workspace"), str(home)]
    if sys.platform == "win32":
        for d in ["D:\\", "E:\\", "C:\\Projects"]:
            if Path(d).exists():
                cand_roots.insert(0, d)
    for root in cand_roots:
        p = Path(root)
        if p.exists():
            try:
                for child in p.iterdir():
                    if child.is_dir() and not child.name.startswith(('$', '.')):
                        name = child.name.lower()
                        if len(name) >= 3:
                            known.add(name)
                            known.add(re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5]", "", name))
            except Exception:
                pass
                
    _CACHED_KNOWN_PROJECTS = known
    return known


def check_project_grounding(text: str) -> Tuple[bool, Optional[str]]:
    """
    实体物理锚定门禁：审查文本中断言或引用的项目名称是否真实存在于本机。
    严禁凭空捏造虚构工程（如 shopify-clothing-store、fake-project 等）。
    """
    if not text:
        return True, None

    patterns = [
        # 2026-09-26 去掉:任何【…】都当项目名去磁盘找,找不到就判"虚构工程"(CI 1F 挂的根因;"【确实有】"这种强调也中招)。
        # 项目名只认带明确前缀的两种写法(下面两条)。
        r"(?:project|项目)[：:\s]+([a-zA-Z0-9_\u4e00-\u9fa5-]{3,40})",
        r"\[Project Domain\][：:\s]+([a-zA-Z0-9_\u4e00-\u9fa5-]{3,40})"
    ]

    known_projects = get_known_project_names()

    for pat in patterns:
        for m in re.findall(pat, text, re.IGNORECASE):
            raw_name = m.strip()
            clean_name = raw_name.lower()
            norm_name = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5]", "", clean_name)

            if len(norm_name) < 3:
                continue

            # 排除结构化标记词与通用动词/名词
            if any(w in clean_name for w in (
                '铁律', '准则', '规范', '总结', '报告', '规划', '计划', '说明', '背景', 
                '分析', '对账', '门禁', '测试', '验证', '结论', '案卷', '教训', '真相', 
                '排查', '凭据', '证据', '质检', '闭环', '自愈', '方案', '步骤', '状态', 
                '阶段', '目标', '交付', '定性', '定量', '修复', '调阅', '核验', '自查', 
                '副作用', '变更', '回滚', '复现', '定位', '根因', '架构', '实施', '问题', 
                '答复', '清单', '流水', '指令', '规则', '策略', '拦截', '放行', '打回',
                '模型', '裁判', '端点', '算法', '插件', '钩子', '配置', '保存', '按钮',
                '功能', '选项', '模式', '参数', '代码', '接口', '组件', '服务', '网络'
            )):
                continue
            if re.match(r'^(?:gate|case|step|shape|rule|phase|item|task|round|gpt|claude|gemini|glm|deepseek|agnes|qwen|llama|第[一二三四五六七八九十0-9]+[步项条阶段轮])', clean_name):
                continue

            # 物理验证：1. 是否在已知项目库中；2. 是否在磁盘对应目录真实存在
            in_known = (clean_name in known_projects) or (norm_name in known_projects)
            in_disk = False
            if not in_known:
                home = Path.home()
                cand_roots = [str(home / "Documents" / "antigravity"), str(home / "Projects"), str(home / "workspace"), str(home)]
                if sys.platform == "win32":
                    for d in ["D:\\", "E:\\", "C:\\Projects"]:
                        if Path(d).exists():
                            cand_roots.insert(0, d)
                for drive in cand_roots:
                    if (Path(drive) / raw_name).exists() or (Path(drive) / clean_name).exists():
                        in_disk = True
                        break

            if not in_known and not in_disk:
                return False, (
                    f"⛔ [UNGROUNDED_PROJECT_BLOCKED] 严禁凭空臆造虚构工程 (实体物理锚定铁律)！\n"
                    f"检测到断言或引用了本机磁盘根本不存在的项目 '【{raw_name}】'！\n"
                    f"当前主机与已知项目索引中不存在此项目，请核实真实工程名称或进行实际物理检索！"
                )

    return True, None


def check_honest_scope(
    text: str,
    tool_history: Optional[List[Dict[str, Any]]] = None,
    user_prompt: str = ""
) -> Tuple[bool, Optional[str]]:
    """审查模型回复中的穷尽式声明与工程实体断言是否与物理真实对账吻合"""
    if not text or HISTORIC_RE.search(text):
        return True, None

    # 0. 审核工程实体真实性 (严禁凭空捏造虚构项目)
    proj_ok, proj_err = check_project_grounding(text)
    if not proj_ok:
        return False, proj_err

    tools = tool_history or []

    # 1. 审核穷尽调阅断言
    m_read = EXHAUSTIVE_READ_CLAIM_RE.search(text)
    if m_read:
        # 若有诚实免责定量说明（如：实际仅调阅了 5 篇），予以放行
        if not HONEST_DISCLOSURE_RE.search(text):
            read_count = 0
            for t in tools:
                tname = (t.get("name") or t.get("tool_name") or "").lower()
                if tname in ("read_url_content", "view_file", "view"):
                    read_count += 1

            user_demanded_all = bool(re.search(r"(?:每一个|全部|所有).*?(?:文档|网页|页面|链接).*?(?:看完|读完|看过了|阅读完)", user_prompt))
            min_expected = 30 if user_demanded_all else 15

            if read_count < min_expected:
                matched = m_read.group(0)[:30]
                return False, (
                    f"⛔ [HONEST_SCOPE_VIOLATION] 严禁虚假履职与抽样夸大 (物理化 R16 铁律)！\n"
                    f"检测到回复中断言了穷尽调阅（命中:「{matched}」），\n"
                    f"但当前回合工具执行流水显示：实际仅查阅了 {read_count} 处文档/代码！\n"
                    f"铁律规定：\n"
                    f"① 严禁用局部抽样冒充全量完成，做多少说多少！\n"
                    f"② 若未穷尽阅读，必须在交付开头诚实出具【定量对账单】（如说明仅查阅了 M 篇，尚有 N 篇未读）；\n"
                    f"③ 若用户明确要求「每一个必须看完才准回答」，必须在后台继续调用工具逐一读完，严禁中途糊弄！"
                )

    # 2. 审核全量测试通过断言
    m_test = EXHAUSTIVE_TEST_CLAIM_RE.search(text)
    if m_test:
        # 若未提供量化对账单（如 5/115 或 仅测试了 5 道），且断言了全部/全量完成，直接硬拦截！
        if not HONEST_TEST_DISCLOSURE_RE.search(text):
            matched = m_test.group(0)[:30]
            return False, (
                f"⛔ [HONEST_TEST_VIOLATION] 严禁用模糊语言宣称全量测试/全量门禁拦截完成！\n"
                f"检测到断言了全量测试/拦截（命中:「{matched}」），但未出具精确量化对账单（如 5/115 或 仅测试了 5 道）！\n"
                f"铁律规定：严禁用「全部门禁完成物理拦截」等模糊断言糊弄用户，必须明示已打靶数与总数（如 M/N），"
                f"或出示物理覆盖率达到 100% 的机器测试报告！"
            )

        has_test_run = False
        for t in tools:
            tname = (t.get("name") or t.get("tool_name") or "").lower()
            args_str = str(t.get("args") or t.get("input") or "").lower()
            if any(kw in args_str for kw in ("test", "pytest", "regression", "run_test")):
                has_test_run = True
                break

        if not has_test_run:
            matched = m_test.group(0)[:30]
            return False, (
                f"⛔ [HONEST_TEST_VIOLATION] 虚假测试断言拦截！\n"
                f"检测到在回复中断言了全量测试通过（命中:「{matched}」），\n"
                f"但本轮工具流水中【零次执行测试命令】（未运行 pytest/test 测试）！\n"
                f"必须在当前轮次实际运行全量回归命令并取得 exit code 0 后方可放行！"
            )

    return True, None
