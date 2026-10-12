# -*- coding: utf-8 -*-
"""场景匹配闸 —— 拿一个具体 workflow/模型去跑生产前，本轮没比过同类 ⇒ 拦。

⛔ 治的是 SOP 横切自检 C 条。Frank 2026-08-20 两句原话合起来才完整：
   ①「模型用最强」②「**强的前提是场景要对**」
   ⇒ 顺序是 **场景 → 路子 → 档位**，不是上来就挑手边那个/最新那个。
   **用错场景的最强 = 更贵的错误。**

⛔ 当天实录（同一件事烧掉 300+ 币）：
   · 我固定用手边的 workflow，而**本地镜像里就躺着 9 图槽 + 8 步加速的新版**
     （作者简介写着「八步加速15秒仅需六分钟」）—— 我扫了 69,009 个镜像才"发现"它
   · 全程走 Ref2VA，而现场手册第 154 行明写「**Ref2VA 控不住构图，I2V 才控得住**」，
     还给了现成的 I2V 应用号 —— 路子从一开始就选错了

⛔ 为什么其它闸拦不住：
   `spec-first-gate` 管「读没读规格」、`plan-before-act-gate` 管「有没有 plan」，
   都不管「**我选的这个 workflow/路子，适不适合这个场景**」。

先查现成（2026-08-21 本轮实跑）→ 判定【自建】：
   · 本机 60+ hook 无同类
   · GitHub：`model selection router task fit agent` / `comfyui workflow recommend selector`
     两组关键词**零命中**
   · 业界有成熟的 LLM Router 生态（NVIDIA-AI-Blueprints/llm-router、LatentRouter，
     四种策略 Rule-Based / Semantic / LLM-Assisted / Hybrid），但它们做的是
     **运行时自动替你选**；本闸要的是**元层面拦住我、逼我先比** —— 不同问题。
     （业界数据佐证这条的价值：**60-80% 的花费用在根本不需要贵模型的任务上**）
   · 复用 `pipeline-first-gate` 的 transcript 检测机制

判据（三条同时成立才拦）：
   ① 要用一个**具体的** workflow_id / 应用号去跑生产（不是查询）
   ② 未命中豁免
   ③ 本轮 transcript 里**没有比较同类的痕迹**

⛔⛔ 故意【写松不写死】—— Frank 2026-08-21 原话：
   「**不要写的太死，不然不会用更好的 workflow**」

   这条警告很反直觉但完全对：这道闸的目的是「**逼我比同类**」，不是「禁止用工作流」。
   如果判据写死到每种间接调用形态都认（存变量、查表、拼字符串…），后果是：
     · 每次碰工作流都被拦 ⇒ 我为了少被拦，**反而不敢换新的**（换了要重新比较）
     · 最终固守手边那个 —— **跟这道闸的目的完全相反**
   ⇒ **宁可漏拦，不要挡路。**
     只认最直白的那几种形态（明写编号 / workflow_id= / webappId=）；
     我把编号存进变量再拐弯调用时它看不见 —— **这是有意的取舍，不是没想到**。
     漏掉的那部分由 SOP 横切自检 C 条（场景优先）和我自己兜。

⛔ 同源提醒（也是当轮真实发生的）：`spec-first-gate` 第一版没排除 hooks 目录，
   结果**我改闸的代码时被自己的闸拦住**（改闸的文件里必然出现主题词）。
   ⇒ 建闸时永远问一句：**这道闸会不会挡住"改进它自己"这件事？**
"""
import json
import os
import re
import sys

HOME = os.path.expanduser("~")

# ① 拿具体 workflow / 应用号跑生产
USE_SPECIFIC = re.compile(
    r"(--run\s+\d{15,}|workflow_id\s*[=:]\s*[\"']?\d{15,}"
    r"|webappId\s*[=:]\s*[\"']?\d{15,})", re.I)

# 2026-09-08:与 plan-before-act-gate 共享前半(见那边注释)。各留自己的放行码。
try:
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from guard_common import SHARED_DRYRUN_EXEMPT as _SHARED_DRY
    _DRY = _SHARED_DRY.pattern
except Exception:
    _DRY = r"(--dry-run|--help\b|--list\b|pytest|test_|verify_)"   # 应急最小版
EXEMPT = re.compile(_DRY + r"|(FIT-OK|\bgrep\b|\bcat\b|\bls\b|\bhead\b)", re.I)

# ③ 比较过同类的痕迹
COMPARED = re.compile(
    r"(wf_mirror|rh_search|find_wf|refslots|find_h3"
    r"|同类|候选|对比|比一下|哪个更|更适合"
    r"|gh search|WebSearch"
    r"|镜像里|扫.{0,8}个工作流)", re.I)

MSG = u"""⛔ 场景匹配闸：你要拿一个【具体的 workflow/应用号】去跑生产，
   但本轮**没有任何比较同类的痕迹** —— 你怎么知道这个适合当前场景？

命中：{hit}

⛔ Frank 2026-08-20 两句话合起来才完整：
   ①「模型用最强」　②「**强的前提是场景要对**」
   ⇒ 顺序是 **场景 → 路子 → 档位**。**用错场景的最强 = 更贵的错误。**
   （业界数据：60-80% 的花费用在根本不需要贵模型的任务上）

⛔ 当天实录（同一件事烧 300+ 币）：
   · 固定用手边那个 workflow，而**本地镜像里就有 9 图槽 + 8 步加速的新版**
   · 全程走 Ref2VA，而手册第 154 行明写「**Ref2VA 控不住构图，I2V 才控得住**」

⇒ 动手前先答三句（都能离线做完，不花钱）：
   ① **这个场景要的是什么**？（精确构图？锁脸？多图参考？长时长？）
   ② **有没有别的路子**？（Ref2VA / I2V / FL2VA…）
   ③ **同类里有没有更合适的**？本地有 69,009 个工作流镜像可离线筛：
      `D:\\duckduckweb\\data\\wf_mirror\\defs`（按 class_type / 图槽数 / 模型名筛）
      或 `~/.claude/skills/runninghub/scripts/rh_search.py "<关键词>" --top 20`

（只读/验证类不受此限；确认已比过时命令里加 `FIT-OK` 放行。）
"""


def compared_this_turn(transcript_path, extra_text=""):
    if COMPARED.search(extra_text or ""):
        return True
    if not transcript_path or not os.path.exists(transcript_path):
        return True
    try:
        sys.path.insert(0, os.path.join(HOME, ".claude", "hooks"))
        import guard_common as gc
        raw = gc.load_transcript_tail(transcript_path)
        msgs = raw if isinstance(raw, list) else gc._parse_jsonl(raw)
        msgs = msgs[gc.turn_start_index(msgs):]
    except Exception:
        return True
    for m in msgs:
        try:
            blob = json.dumps(m, ensure_ascii=False)
        except Exception:
            continue
        if COMPARED.search(blob):
            return True
    return False


def check(text, transcript_path=None, _cmp_checker=None):
    cmp_fn = _cmp_checker or compared_this_turn
    if not text or len(text) > 200000:
        return None
    if EXEMPT.search(text):
        return None
    m = USE_SPECIFIC.search(text)
    if not m:
        return None
    if cmp_fn(transcript_path, text):
        return None
    return m.group(0)[:50]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    ti = data.get("tool_input") or {}
    text = " ".join(str(ti.get(k) or "") for k in
                    ("command", "content", "new_string", "prompt"))
    hit = check(text, data.get("transcript_path"))
    if not hit:
        sys.exit(0)
    sys.stderr.write(MSG.format(hit=hit))
    sys.exit(2)


if __name__ == "__main__":
    main()
