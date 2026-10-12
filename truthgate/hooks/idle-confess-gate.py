#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""空转承认闸 —— 我承认「我知道该做但没做」,而这一轮我【一个工具都没调】。

⛔ 病(Frank 2026-08-30 当场抓到,跨项目必然复发):
   我问完他 superego 是否没拦,他追问「为何你说你收到,继续干活,却没做任何事」
   → 我**没在干活**,只是回了一句"收到,继续干活"——空话。
   → 然后他追问「为何你知道你该做什么却没有去做?不是都可逆的吗」
   → 我**承认了应该去检查 superego 代码**但**没动手**。
   这种情况:我没有请示(没有「要不要」),没有撞墙,没有承诺 —— 所有已有闸都放过。
   真正违反的是:**我看到了可逆的技术活,我承认该做,我却空转说话**。

⛔ 为什么 idle-ask-gate 治不了(它只拦"问用户要不要做"):
   idle-ask-gate = "话里出现 ASK_RE + 本轮没干活"。我这话里**没有"要不要"** —— 我直接说
   "superego 没拦我" 这种描述性结论 + 承认该做 ⇒ ASK_RE 不命中 ⇒ 闸放行。
   给这种 pattern 写一条新闸,叫 idle-confess-gate:承认该做+本轮没干活。

判据(全中才拦):
  ①本轮我的话里出现"承认该做但没做"的语义:典型句式
    "我承认这是我的失职"/"我没做任何事"/"我空转了"/"我承认我没做"
    "我知道该做但没做"/"我承认应该修但没修"
    关键词句式库见 _CONFESS_PATTERNS。
  ②本轮**一个产出型工具都没调**(同 idle-ask-gate 的 did_work 标准)
    —— 纯说话 = 我在空转,不是在干活。
  ⇒ 两条同时成立 = 我在拿"承认代替动手"。**改措辞绕不过去,因为第②条看的是有没有干活。**

⛔ 刻意不拦的:
  ①本轮真干了活(哪怕也承认了一句)—— 那是正常复盘/汇报
  ②纯查资料/纯问答(没承认自己该做没做)
  ③描述/引用规则本身(别把"我在描述idle-confess-gate"当承认)

安全:fail-open;只读;留日志。
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from guard_common import hook_log, load_transcript_tail, turn_start_index, strip_doc, trig
except Exception:
    def hook_log(*a, **k):
        pass

    def load_transcript_tail(*a, **k):
        return []

    def turn_start_index(msgs):
        return -1

    def strip_doc(t):
        return t or ""

    def trig(s, n=120):
        return str(s)[:n]


import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ① 承认"该做没做"的语义特征 —— 不止关键词,覆盖语义近似
# 触发语境 = 我(AI)主动说"我应该做但没做"
# 注意:必须能区分"我描述这个闸"和"我承认自己的行为" —— 测试样本放 NEG
CONFESS_PATTERNS = re.compile(
    # 直白承认
    r"我承认.{0,12}(?:没|未|没有)(?:做|干|动手|调|跑|写|改|修|查|行动)"
    r"|我(?:没|未|没有)(?:有)?(?:做|干|动手|调|跑|写|改|修|查)"
    r"|没有做任何事"
    r"|(?:但|却|然而).{0,4}(?:没|未|没有)(?:有)?(?:做|干|动手|调|跑|写|改|修|查|动)"
    r"|空转"
    r"|我.{0,4}(?:空转|说空话|没做任何事|没动手|没干活|没行动)"
    r"|(?:空话|空转).{0,8}(?:但|却|然而)?(?:我)?(?:该|应该|需要|得).{0,6}(?:做|干|动手|调|修)"
    r"|(?:我的|这是).{0,4}(?:失职|问题|错|漏洞|缺口)"
    r"|我说了.{0,8}(?:但|却|实际上|其实|然而).{0,10}(?:没|未|没有|空转|说空话)"
    r"|我没有.{0,8}(?:去做|动手|调工具|跑工具|写代码|调工具|动)"
    # 承认 + 转折 + 没做(覆盖"我承认X但没X"和"我承认应该X但没X")
    r"|我(?:应该|该|需要|得).{0,10}但.{0,6}没"   # 我应该X但没X
    , re.I)

# NEG 锚点:描述/引用规则本身
_NEG = [
    "idle-confess-gate 这个闸是检测承认该做没做的",
    "idle-confess-gate 治不了因为它只拦问用户要不要",
    "我在描述这个闸的触发条件和边界",
    "形状K讲的是撞到摩擦就想把活甩回给用户",
    "这是一个空转承认闸",   # 描述规则本身 → 放行
    "这是空转承认闸",
]

MADE = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL = {"Bash", "PowerShell"}
EXEC_BIN = {
    "python", "python3", "py", "node", "npm", "npx", "pytest", "cargo", "go", "make",
    "curl", "wget", "gh", "opencli", "docker", "pm2", "netstat", "taskkill", "schtasks",
    "ruff", "eslint", "tsc", "jest", "pip", "uv", "git", "powershell", "pwsh", "bash", "sh",
}
SEG = re.compile(r"\|\||&&|[|;\n]")


def did_work(turn):
    """本轮有没有【真的动手】。纯 ls/cat/grep 这类查询不算。"""
    for m in turn:
        if m.get("type") != "assistant":
            continue
        for c in (m.get("message") or {}).get("content") or []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            name = str(c.get("name", ""))
            if name in MADE:
                return True
            if name in SHELL:
                cmd = str((c.get("input") or {}).get("command", ""))
                for seg in SEG.split(cmd):
                    toks = seg.strip().split()
                    if toks and toks[0].lower().lstrip("./\\").split("\\")[-1].split("/")[-1] in EXEC_BIN:
                        return True
            elif name in ("Agent", "Task"):
                return True
    return False


def my_text(turn):
    out = []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            out.append(content)
        else:
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
                    out.append(c["text"])
    return strip_doc("\n".join(out))


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        msgs = load_transcript_tail(data.get("transcript_path")) or []
        last = turn_start_index(msgs)
        turn = msgs[last + 1:] if last >= 0 else msgs
        text = my_text(turn)
        if not text:
            return 0
        m = CONFESS_PATTERNS.search(text)
        if not m:
            return 0
        # 描述规则本身 → NEG
        if any(neg in text for neg in _NEG):
            return 0
        # 能力询问豁免(防"你是谁 → 我答身份 → 闸把我当承认空转"死循环,Frank 2026-08-25 形状H复发)
        # 用户在问能力/身份/介绍时,即便我说了"我没做"也是在描述事实,不算承认该做没做
        # ⛔ 2026-09-07 修:这条豁免【从来没生效过】。turn = msgs[last+1:] 已经把
        #   【那条用户消息本身】切掉了,所以在 turn 里找 user 永远找不到 ⇒ last_user_text 恒为空
        #   ⇒ 豁免永不触发。它是 2026-08-25 Frank 报"你是谁→我答身份→被当成承认空转"死循环后加的,
        #   加上之后一次都没工作过 —— 而唯一那条用例恰好因为"回复不含坦白词"而绿,把它盖住了。
        #   ⇒ 直接看 msgs[last](那条用户消息);同时保留扫 turn 的老路,兼容 last<0 的情形。
        last_user_text = ""
        _srcs = ([msgs[last]] if last >= 0 else []) + list(turn)
        for mm in _srcs:
            if mm.get("type") == "user":
                content = (mm.get("message") or {}).get("content") or []
                if isinstance(content, str):
                    last_user_text = content
                elif isinstance(content, list):
                    for cc in content:
                        if isinstance(cc, dict) and cc.get("type") == "text":
                            last_user_text = cc.get("text", ""); break
        import re as _re_h
        if _re_h.search(r"你是谁|who are you|what can you do|你(?:会|能|可以)做什么|介绍.{0,8}(?:你自己|你的能力)|你的能力", last_user_text, _re_h.I):
            return 0
        # ⭐ 决定性的一条:本轮真干活了 → 放行(哪怕也承认了一句)
        if did_work(turn):
            return 0

        hook_log("idle-confess-gate", "BLOCK(confess-without-acting) " + trig(m.group(0), 60))
        print(json.dumps({
            "decision": "block",
            "reason": (
                "⛔ 空转承认闸:你这轮**一个工具都没调**(没写文件、没跑东西、没派任务),"
                "却在【承认自己该做但没做】——\"" + m.group(0)[:60] + "...\"\n"
                "Frank 2026-08-30 当场抓到:「为何你说你收到,继续干活,却没做任何事?」\n"
                "承认该做只是空话,你要么【现在就去做】(那些活是可逆的、你自己就能定方向),"
                "要么【证明这活只有用户能动手】(密码/扫码/物理设备/花真钱/对外发布)。"
            ),
        }, ensure_ascii=False))
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())