#!/usr/bin/env python3
"""PostToolUse hook·规则双写守卫(2026-07-26)——写新教训时,当场告诉我它跟哪条已有规则是同一件事。

【治什么】深搜调研员在真实的 100 条规则上跑了一次体检,结论出人意料:
  规则库的头号病【不是矛盾,是双写】—— 相似度最高的几对全是"一条教训 + 它升格成的铁律"
  两处各存一份(形状L↔交付形态、8G教训↔资源边界、形状J↔先测现成)。
  这是【有意为之】的(教训要细节、铁律要精简),但意味着**改一处忘另一处就会变成真矛盾**。
  另有 22/86 条疑似"被遮蔽的死规则"(总是被更相似的另一条压住,永远召不回来)。

【为什么在源头拦而不是季度大扫除】
  季度扫描要人逐对判、且矛盾已经产生;在写入那一刻提示"这跟 §X 是同一件事",
  我当场就能决定【升级那一条】还是【真的新开一条】—— 便宜一个量级。

【怎么判】复用已经在跑的 7911 语义服务(规则向量早就算好了,零额外模型、零额外成本)。
  相似度 ≥0.80 才提示,只提示不拦(PostToolUse 本来也拦不住),让我自己决定合并还是新开。
fail-open:服务挂/超时/异常一律静默,绝不打扰。
"""
import os as _os_sp, sys as _sys_sp
_sys_sp.path.insert(0, _os_sp.path.join(_os_sp.path.expanduser("~"), ".claude"))
from superego_port import BASE as _SEM  # 端口唯一出处:~/.claude/superego-port.txt
import os as _o
import sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
try:
    from guard_common import hook_log
except Exception:
    def hook_log(*a, **k):
        pass
import json
import re
try:
    from guard_common import trig
except Exception:
    def trig(s, n=120): return (s or '')[:n]
import sys
import urllib.request

# ⛔ 阈值必须在【你自己的数据】上标定,不许从调研报告里抄。
#   第一版我抄了报告里的 0.80,实测这套语料上真重复只打到 0.57 —— 等于这道闸永远不会响(空壳)。
#   标定实录(2026-07-26,拿调研员点名的 5 对真重复 vs 5 个完全无关主题):
#     真重复:0.522 / 0.555 / 0.584 / 0.594 / 0.665  (5 对全部正确认出各自的"真身")
#     全新  :0.228 / 0.265 / 0.288 / 0.323 / 0.384
#     分离间隙 0.138,取中点 → 0.45。
SIM_T = 0.45
TOPK = 3
RULE_SRC = ("lessons.md", "CLAUDE.md")


def _new_headings(text):
    """从这次写入的内容里挑出【新增的规则标题】(## 开头那种),没有就不用查。"""
    return [h.strip() for h in re.findall(r"^##+\s*(.+)$", text or "", re.M) if len(h.strip()) > 6]


def main():
    data = json.loads(sys.stdin.read())
    inp = data.get("tool_input") or {}
    fp = str(inp.get("file_path", ""))
    if not any(fp.endswith(s) for s in RULE_SRC):
        # ⛔ 2026-09-07:出口日志(形状 S)。裸 return 会让内部 bug 全隐形。
        hook_log("rule-dup-guard", "pass(不是规则源文件)")
        return
    # Edit 看新增段,Write 看全文;shell 追加的内容拿不到,跳过(不硬猜)
    body = inp.get("new_string") or inp.get("content") or ""
    heads = _new_headings(body)
    if not heads:
        hook_log("rule-dup-guard", "pass(没有新标题)")
        return

    hits = []
    for h in heads[:2]:                     # 一次最多查两条,别拖慢收尾
        try:
            payload = json.dumps({"text": h, "topk": TOPK, "thresh": SIM_T}).encode()
            req = urllib.request.Request(_SEM + "/recall", payload,
                                         {"Content-Type": "application/json"})
            for r in json.loads(urllib.request.urlopen(req, timeout=4).read()).get("hits", []):
                if float(r.get("score", 0)) >= SIM_T and r.get("title", "")[:20] not in h:
                    hits.append((h, r["title"], r["score"]))
        except Exception:
            return                          # fail-open:静默
    if not hits:
        hook_log("rule-dup-guard", f"ok(no dup) heads={len(heads)}")
        return

    lines = [f"  · 新写的「{h[:34]}」 ≈ 已有的「{t[:44]}」(相似 {s:.2f})" for h, t, s in hits[:4]]
    ctx = ("⚠️[规则双写守卫] 你刚写进规则库的内容,和下面已有的规则高度重合:\n"
           + "\n".join(lines)
           + "\n—— 规则库的头号病是【双写】不是矛盾:同一件事存两处,改一处忘另一处就会变成真矛盾。"
             "现在决定:①如果是同一件事 → 去【升级那一条】,别新开;"
             "②如果确实是不同的形状 → 在新条目里写清它和那条的【区别在哪】,让下一个读到的人不会混。")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": ctx}}, ensure_ascii=False))
    hook_log("rule-dup-guard", f"WARN {len(hits)} dup-candidates",
             trig(" | ".join(str(h)[:60] for h in hits[:3]), 160))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            hook_log("rule-dup-guard", f"error(fail-open): {type(e).__name__}: {e}")
        except Exception:
            pass
