#!/usr/bin/env python3
r"""authority-source-gate —— 问某个系统/工具前，先逼我读权威源。

治的病：凭记忆碎片答、忽略本机已有权威文档。
例：问 Superego 是什么 -> 应 Read SUPEREGO.md，但我答了碎片不读原文。

机制：
  1. 从 TOPIC_KEYWORDS 匹配查询主题
  2. 查 transcript 有没有 Read 对应权威源文件
  3. 没读 -> deny(最多 MAX_BLOCKS=3 次)

安全：fail-open / MAX_BLOCKS=3 / 状态坏了放行
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_common  # noqa: F401  导入即记账(2026-09-16 前它开没开火,统计里看不到)
except Exception:
    pass

HOME = Path.home()
# SUPEREGO_LOG_DIR = 测试隔离目录,别让测试写生产状态
STATE = Path(os.environ.get("SUPEREGO_LOG_DIR") or (HOME / ".claude" / "hooks")) / ".authority-source.json"
MAX_BLOCKS = 3

AUTH_SOURCES = {
    "superego": [
        HOME / ".claude" / "SUPEREGO.md",
        HOME / ".claude" / "lessons.md",
    ],
    "machine facts": [HOME / ".claude" / "host-machine-facts.md"],
    "browser routing": [HOME / ".claude" / "browser-routing.md"],
    "project overview": [HOME / ".claude" / "PROJECT-OVERVIEW.md"],
    "ui humanity": [HOME / ".claude" / "ui-humanity-ironlaw.md"],
    "process safety": [HOME / ".claude" / "skills" / "process-safety-sop" / "SKILL.md"],
    "local model sop": [HOME / ".claude" / "skills" / "local-model-sop" / "SKILL.md"],
    # 2026-09-16 删「cc-switch models」:要求 Read 一个二进制 .db(Read 读不了),且 model-authenticity-gate 已管这件事
}

# 2026-09-16 外审:30 条常见查询命中 20 条(「Airbnb 服务费」「启动 Next.js」「react hook form」…)
#   ⇒ 删掉高频泛词(服务/启动/端口/机器/入口/可见/hook/gate/memory/cpu/automation/ocr/tts/ui),只留指向本机那份文档的词。
TOPIC_KEYWORDS = {
    "superego": ["superego", "闸", "免疫", "superego系统"],
    "machine facts": ["卡顿", "卡死", "风扇", "硬盘", "ssd", "磁盘"],
    "browser routing": ["浏览器", "playwright", "puppeteer", "opencli", "反爬"],
    "project overview": ["项目清单", "有哪些项目", "project overview"],
    "ui humanity": ["人性化", "五问"],
    "process safety": ["杀进程", "僵尸进程", "daemon"],
    "local model sop": ["本地模型", "部署模型", "ollama", "vllm"],
}


def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _norm(p):
    """统一成 resolve 后的绝对路径字符串(跨平台兼容反斜杠/正斜杠)。"""
    return str(Path(p).resolve())


def has_read_this_turn(msgs, filepath):
    fp_norm = _norm(filepath)
    for m in msgs:
        if m.get("type") != "assistant":
            continue
        c = (m.get("message") or {}).get("content") or []
        for item in c:
            if item.get("type") != "tool_use":
                continue
            name = item.get("name", "")
            inp = item.get("input") or {}
            if name == "Read":
                if not inp.get("file_path"):
                    continue            # 空路径 resolve 成当前目录,会乱配(2026-09-16 外审)
                candidate = _norm(inp.get("file_path"))
                if candidate == fp_norm or fp_norm in candidate:
                    return True
            if name in ("ReadMcpResourceTool", "ReadMcpResourceDirTool"):
                cand_str = str(inp)
                if fp_norm in cand_str:
                    return True
    return False


def match_topic(query):
    q = (query or "").lower()
    best_key, best_score = None, 0
    def _hit(kw):
        # 英文关键词按整词匹配:否则 "ui" 会命中 build/guide、"tts" 命中 settings(闸复活前没暴露,2026-09-16)
        if kw.isascii():
            return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", q) is not None
        return kw in q
    for key, kws in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in kws if _hit(kw))
        if score > best_score:
            best_score, best_key = score, key
    if best_score < 1:
        return None, []
    return best_key, AUTH_SOURCES.get(best_key, [])


def check(data, msgs=None, state=None):
    st = state if state is not None else _load()
    sid = str(data.get("session_id") or "default")
    tool_name = data.get("tool_name") or ""

    if tool_name not in ("WebSearch", "WebFetch"):
        st.pop(sid, None)
        return None, st

    # ⛔ 2026-09-16:平台把搜索词放在 tool_input 里。原来只读顶层 data["query"](恒为空)
    #   ⇒ 这道闸 09-14 挂上后一次没开过火,而测试也用顶层 query 造数据 ⇒ 一直是假绿。
    ti = data.get("tool_input") or {}
    query = ti.get("query") or ti.get("prompt") or data.get("query") or data.get("prompt") or ""
    key, files = match_topic(query)
    if key is None:
        st.pop(sid, None)
        return None, st

    already_read = any(has_read_this_turn(msgs or [], f) for f in files)
    if already_read:
        st.pop(sid, None)
        return None, st

    cnt = int(st.get(sid, 0)) + 1
    if cnt > MAX_BLOCKS:
        st.pop(sid, None)
        return None, st
    st[sid] = cnt

    file_list = " / ".join(str(f).replace(str(HOME), "~") for f in files)
    msg = (
        f"⛔ 权威源未读：问的是【{key}】相关，请先 Read 本机权威源再答：\n  {file_list}\n"
        f"（提醒 {cnt}/{MAX_BLOCKS} 次后不再提醒；别凭记忆答）"
    )
    return msg, st


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    msgs = []
    tp = data.get("transcript_path")
    # 2026-09-16 外审:挂在 matcher "*" 上,原来【先】读整份 transcript 再看工具名 ⇒ 58MB 记录每次 Read 都多 3.9 秒。
    #   ⇒ 不是搜索工具就不读 transcript(check 只需要清计数)。
    if tp and (data.get("tool_name") or "") in ("WebSearch", "WebFetch"):
        try:
            for ln in Path(tp).read_text(encoding="utf-8").splitlines():
                try:
                    msgs.append(json.loads(ln))
                except Exception:
                    continue
        except Exception:
            return 0
    hit, st = check(data, msgs)
    _save(st)
    if hit:
        # 2026-09-16:从硬拦(exit 2)降成提醒 —— 复活当天外审测出误伤面大,先观察开火记录再决定要不要拦
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "allow",
                                                 "additionalContext": hit}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
