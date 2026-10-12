#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Stop 闸:【对比表里某一数值列所有行都一样 ⇒ 那把尺子多半没在测量】。

⛔ 起因(2026-09-06,Frank 原话):
   「你凭什么说要用 128 是不降级的方案?**如果 128 能用不可能还会有 1024 的存在**」
   「**尺子坏了不修?那么白痴的逻辑,三岁小孩都能懂,为何 ai 你那么厉害不懂?**」

⛔ 当天我连造两把坏尺子,两次都差点拿去当结论:
   v1:六个维度(1024→128)的 recall@3 **全是 2/7** —— 7 个样本 + "标题含某词"判据,分辨率为 0
   v2:八个维度的 top1 一致率 **全是 0.5%** —— 排除"自己"的下标算错了
   真相(第三版加了自检才测出来):1024=100% / 512=82.5% / 128=**60.5%** —— 降维**明显降级**。

⛔ 病根不是某次手滑,是**我从不验证尺子本身**:造尺子 → 直接用 → 报结论。
   缺的那一步:**拿已知答案量一次**(1024 维跟自己比必须 100%)。
   这一步三岁小孩都懂,而我在代码测试里天天做"对照组",却从没给【测量工具】做过对照组。

判据(全中才提醒,宽放窄拦):
  ① 本轮我输出里有 markdown 表格,且数据行 ≥3
  ② 某一【数值列】所有行完全相同(数值列 = 该列每格都能解析出数字)
  ③ 该表看起来在做【对比/评测】(表头或上下文含 对比/vs/维度/性能/召回/耗时/准确…)
  = 一个随输入变化的量,在所有输入下给出同一读数 ⇒ 尺子可疑

安全:非阻塞提醒(nudge,不 block) / fail-open / 只读 transcript。
⛔ 故意不做成 block:表格里确实存在"该列本来就该相同"的合法情况
   (例如状态列全 ✅)。宁可提醒,别锁死他的活。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import hook_log, turn_start_index
except Exception:
    def hook_log(*a, **k):
        pass

    def turn_start_index(msgs):
        return -1

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GATE = "flat-table"
MIN_ROWS = 3

# 这张表是在做对比/评测吗 —— 只有对比表才适用"该变而没变=可疑"
COMPARE_CTX = re.compile(
    r"对比|vs\b|维度|性能|召回|recall|准确|耗时|速度|命中|评测|基准|benchmark|一致|重合|占用",
    re.I)

NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _texts(turn):
    out = []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        c = (m.get("message") or {}).get("content")
        if isinstance(c, str):
            out.append(c)
            continue
        for it in c or []:
            if isinstance(it, dict) and it.get("type") == "text":
                out.append(it.get("text") or "")
    return "\n".join(out)


def tables(text):
    """抠出 markdown 表格,返回 [(表头行, [数据行...])]"""
    found, cur = [], []
    for ln in text.split("\n"):
        if ln.strip().startswith("|") and ln.count("|") >= 3:
            cur.append(ln)
        else:
            if len(cur) >= 2:
                found.append(cur)
            cur = []
    if len(cur) >= 2:
        found.append(cur)
    out = []
    for tb in found:
        rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in tb]
        # 去掉 |---|---| 这种分隔行
        rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "-") for c in r)]
        if len(rows) >= MIN_ROWS + 1:
            out.append((rows[0], rows[1:]))
    return out


def flat_numeric_cols(header, rows):
    """找出【每格都有数字、且所有行数值完全相同】的列。"""
    bad = []
    ncol = min(len(r) for r in rows)
    for c in range(ncol):
        vals = []
        for r in rows:
            ms = NUM.findall(r[c])
            if not ms:
                vals = None
                break
            vals.append(tuple(ms))          # 整格的数字序列,防 "2/7" 只取到 2
        if vals and len(set(vals)) == 1:
            name = header[c] if c < len(header) else "第%d列" % (c + 1)
            bad.append((name or "第%d列" % (c + 1), vals[0]))
    return bad


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return 0
    try:
        # 2026-09-06:走共享的 load_transcript_tail —— 它内含【回合拦截预算】,
        #   本轮被 Stop 闸拽回次数到上限就返回空列表 => 本闸自然放行,防无限 loop。
        #   实测:55 道 Stop 闸只有 64% 受管,自己 open() 读的 12 道完全绕过,
        #   而本闸就在那 12 道里(Frank:「触发了无限Loop的bug…think twice 然后阻塞」)。
        #   安全类闸在 _BUDGET_NEVER 白名单里永不熔断;逃生阀 SUPEREGO_NO_BUDGET=1。
        from guard_common import load_transcript_tail as _ltt
        msgs = _ltt(tp)
    except Exception:
        return 0
    start = turn_start_index(msgs)
    scope = msgs[start:] if start >= 0 else msgs[-40:]
    said = _texts(scope)
    if not said:
        return 0
    # 本轮已经拦过一次(记录里已有这段话)就放行 —— 不用计时标记:测试每条用例是新记录,互不串
    if any("⛔ 坏尺子闸" in json.dumps(m, ensure_ascii=False) for m in scope):
        hook_log(GATE, "pass(本轮已拦过一次)")
        return 0

    hits = []
    for header, rows in tables(said):
        blob = " ".join(header) + " " + said[:400]
        if not COMPARE_CTX.search(blob):
            continue
        for name, val in flat_numeric_cols(header, rows):
            hits.append((name, "/".join(val), len(rows)))

    if not hits:
        hook_log(GATE, "pass(no flat numeric col)")
        return 0

    # ⛔ 2026-09-07:触发词挪到第三个参数,拼进消息里记分板解析不到 ⇒ 记成"无证据"。
    hook_log(GATE, "NUDGE flat-col", ",".join(h[0] for h in hits))
    lines = ["⛔ 坏尺子闸:你贴的对比表里,**有数值列在所有行上完全相同** ——"]
    for name, val, n in hits[:3]:
        lines.append("   · 「%s」列 %d 行全是 %s" % (name.strip() or "(无表头)", n, val))
    lines += [
        "⛔ **一个本该随输入变化的量,在所有输入下给出同一读数 ⇒ 那把尺子多半没在测量。**",
        "⛔ 实录(2026-09-06,Frank 原话「尺子坏了不修?那么白痴的逻辑,三岁小孩都能懂」):",
        "   我测降维影响,六个维度的 recall 全是 2/7,我写成「持平,可以砍到 128 维」。",
        "   换一把有分辨率的尺子重测:1024=100% / 512=82.5% / 128=**60.5%** —— 降维明显降级。",
        "   同一天第二把尺子也坏了(八行全是 0.5%),我又差点拿它下结论。",
        "⇒ 现在做一件三岁小孩都懂的事:**拿已知答案量一次**。",
        "   例:原生维度跟它自己比,一致率必须是 100%;不是 100% 就是尺子坏了,先修尺子再谈结论。",
        "(若该列本来就该相同——例如状态列全 ✅——说明一句即可。)",
    ]
    # ⛔ 2026-09-11:原来是裸 print —— Stop 闸的纯文本输出【送不到模型】,这道闸从建成那天起模型一次都没看到过。
    #   Stop 阶段没有「不拦又让模型看见」的通道 ⇒ 改成拦(每轮最多一次,见上面的「本轮已拦过」判断):
    #   让我先修尺子,或说明为什么该列本来就相同。
    print(json.dumps({"decision": "block", "reason": "\n".join(lines)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)      # fail-open:观测类闸,绝不挡住他
