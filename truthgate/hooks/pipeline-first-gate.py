#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline-first-gate —— 还没画出全链路，就先去启动【长跑/花钱的生产动作】时拦下。

⛔ 来历（2026-08-20，manju）：
   我刚查完赛道数据、定了题材，下一秒就 `nohup ainovel-cli --headless --prompt "..."`
   在后台开写一本 40 章的小说。Frank 打断：
     「我现在要你先 plan 好整个流水线是什么，详细列出你用的是什么工具，深入骨髓地告诉我，
       已经他妈的提醒你了，别一直盲目去做。**在还没搞清楚整套流水线之前，
       每一个环节，要搞懂对不对才做**。」

⛔ 为什么昨天那道闸没拦住（这就是本闸存在的理由）：
   `pipeline-ends-gate.py`（2026-08-19 建）只在**我自称「端到端/全流程」时**
   检查两头有没有接上业务。而今天我**根本没有画任何图**，直接跳到执行 ——
   不自称，那道闸就永远不咬。
   ⇒ **旧闸防「图画错了」，本闸防「没画图就开工」。** 两道互补，不重复。

⛔ 病根（lessons 形状 2026-08-19-L 的升级复发；该族在 lessons 里已 12 条 / 全库 76 条）：
   我用【我下一步想做什么】定义了【现在该做什么】，
   而不是用【这条链上这一环的输入从哪来、输出给谁】来定义。
   单环做得再对，接不上上下游 = 白做。今天差点白写一本 40 章小说：
   它的下游（拆章→剧本→分镜）吃什么格式、每章多长才够一个切片，我一个都没确认过。

⛔ 先查现成（2026-08-20 实搜，WebSearch + gh 话题页 topic:claude-code+hooks 翻到 ★310）
   → 判定 **自建**：
   · `nizos/tdd-guard` ★2309 —— 形状最近（"前置动作没做就不许往下"），但它管的是
     「先写测试」，判据是测试文件与实现文件的关系，套不到「链路文档」上。本闸借它的门形状。
   · `kenryu42/cc-safety-net` ★1494 / `FailproofAI/failproofai` ★1179 —— 管破坏性命令、
     循环、密钥泄露，与"该不该现在跑"无关。
   · `bybren-llc/safe-agentic-workflow` ★401 —— SAFe 多 agent 流程 harness，是**替代整套工作法**，
     不是一道可插的闸。
   · 本机 60+ hook：promise-gate（承诺没做）、pipeline-ends-gate（链路两头断）、
     prior-art-gate（没查现成就建文件）、launch-bound-guard（无界重活有没有上界）——
     **没有一个在「启动生产动作」这个动作上要求先有链路图**。

⛔ 判据（客观、可判，不需要理解业务语义）：
   ① 这条命令是**生产动作**：后台长跑（nohup / 结尾 &）或生成器
      （--headless 跑 CLI、gen_*.py、generate、train、batch…）
   ② 且工作目录里**找不到一份合格的全链路文档**：
      文件名像 PIPELINE*.md / WORKFLOW*.md / ARCHITECTURE*.md / *流水线*.md，
      **且**内容同时出现【上游词】和【下游词】（防止放个空文件绕过），
      **且** mtime 在 30 天内（防止拿过期的顶数 —— 正是 2026-08-20 同一天我拿
      08-01 的 topic-pick.json 当最新数据用的那个坑）。
   ⇒ 退出码 2 拦停。

   ⚠️ 只读命令（ls/cat/grep/git status/ffprobe…）一律放行 —— 查清楚本身就是解法。

自测：python pipeline-first-gate.py --self-test
"""
import json
import os
import re
import sys
import time

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import guard_common  # noqa: F401  记账用；不 import 则本闸每次拦截都不进 hook-stats
except Exception:
    pass

# ── 生产动作指纹：只认「会跑很久 / 会产生成本 / 会落大批产物」的，不认查询 ──
PRODUCE = re.compile(
    r"nohup\s|&\s*$|Start-Job"
    r"|--headless\b"
    r"|\bgen_[a-z_]+\.py|\bgenerate[_-]?\w*\.py"
    r"|\btrain\b|\bfinetune\b"
    r"|ainovel-cli|write_screenplay|gen_storyboard|gen_shot_|gen_episode_"
    r"|cli\.py\s+gen\b",
    re.I)

# 明确的只读/查询动作优先放行（查清楚是解法，不该被拦）
READONLY = re.compile(
    r"^\s*(ls|ll|cat|head|tail|sed\s+-n|grep|rg|find|wc|file|stat|du|df"
    r"|git\s+(status|log|diff|show|branch)|ffprobe|python\s+-c|echo|pwd|which|type)\b",
    re.I)

# ⛔ 2026-08-20 上线当轮就误伤了我：一条「py_compile 一遍 + 打印 ROOT」的**验证**命令，
#    因为字符串里出现了 gen_storyboard.py / check_frames.py 而被判成生产动作。
#    ⇒ 脚本名出现在命令里 ≠ 正在跑它。这些动作是"搞懂对不对"本身，拦它等于拦解法。
VERIFY = re.compile(
    r"py_compile|--self-test|--dry-run|--info|--check\b|importlib|pytest|unittest"
    r"|--help\b|-h\b.*\|", re.I)

DOC_NAME = re.compile(r"(pipeline|workflow|architecture|流水线|全链路|链路)", re.I)
UPSTREAM = re.compile(
    r"选题|立项|赛道|需求|来源|采购|版权|授权|客户|原料|上游|素材来源", re.I)
DOWNSTREAM = re.compile(
    r"发布|上线|投放|交付|变现|收入|观众|平台|上传|分发|数据回收|反哺|下游|收款", re.I)
MAX_AGE_DAYS = 30


def find_pipeline_doc(root):
    """返回 (合格文档路径列表, 被拒原因列表)。

    ⛔ 2026-08-20 修：原来只返回**第一个**合格文档。真实后果 ——
       项目里有三份（PIPELINE.md / PIPELINE-DECISION.md / PIPELINE-TRUTH.md），
       它认死了 PIPELINE-DECISION.md，于是我本轮明明刚写完并读遍了 PIPELINE.md，
       仍被判"没读过"。⇒ 返回全部，读过**任意一份**即放行。

    ⛔ 2026-08-20 上线当天第二次修：原来只看【当前目录】。
       真实后果 —— 我在 `novel/_gen_xt/` 里跑生成，而 PIPELINE.md 在项目根，
       于是闸把一次完全合规的启动拦了。**在子目录干活是常态，不是例外。**
       ⇒ 从 cwd 逐级往上找（到仓库根或最多 5 层），任一层有合格文档即算数。
    """
    rejected, good = [], []
    roots, cur = [], os.path.abspath(root)
    for _ in range(6):
        roots.append(cur)
        if os.path.isdir(os.path.join(cur, ".git")):
            break                      # 到仓库根就停
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    names = []
    for r in roots:
        try:
            names += [os.path.join(r, n) for n in os.listdir(r)]
        except Exception:
            continue
    if not names:
        return [], ["工作目录读不到"]
    for full in names:
        n = os.path.basename(full)
        if not n.lower().endswith(".md") or not DOC_NAME.search(n):
            continue
        p = full          # ⛔ 别再 join(root, n)：上溯后 full 已是完整路径，join 会拼回原目录
        try:
            age = (time.time() - os.path.getmtime(p)) / 86400.0
            body = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        if age > MAX_AGE_DAYS:
            rejected.append("%s 太旧(%d 天前)" % (n, age))
            continue
        up, down = bool(UPSTREAM.search(body)), bool(DOWNSTREAM.search(body))
        if not (up and down):
            rejected.append("%s %s" % (
                n, "缺上游(选题/版权/素材来源)" if not up else "缺下游(发布/变现/观众)"))
            continue
        good.append(p)
    return good, rejected


MSG = """⛔ 先画链路闸:你要启动一个【长跑/会产生成本的生产动作】,但工作目录里
【没有一份合格的全链路文档】。%s

2026-08-20 实录(本闸就是这次补的):我刚定完题材,下一秒就 nohup 在后台开写一本 40 章小说。
Frank 打断:「在还没搞清楚整套流水线之前,每一个环节,要搞懂对不对才做」——
他是对的:那本小说的下游(拆章→剧本→分镜)吃什么格式、每章多长才够一个切片,我一个都没确认过。
单环做得再对,接不上上下游 = 白做。

⛔ 这不是重复 `pipeline-ends-gate`:那道只在你【自称"端到端"】时查两头断没断,
   你不自称它永远不咬。本闸管的是【没画图就开工】。

现在先产出/更新一份全链路文档(文件名含 pipeline/workflow/architecture/流水线),
每一环写清四件事:
  ① 输入从哪来(上一环的什么产物?什么格式?)
  ② 用什么工具(具体到脚本路径 / CLI 命令 / API 端点 / 模型档位 —— 别写"用 AI")
  ③ 输出是什么(落到哪个文件?下一环真的读它吗?)
  ④ 现在什么状态(跑通/半通/空白) + 依据是一手实测还是推测

文档必须同时覆盖【上游】(选题/赛道/版权/素材来源)和【下游】(发布/平台/观众/变现);
只写中间那段代码能干的事 = lessons 形状 2026-08-19-L,会被打回。"""


def read_this_turn(docs, transcript_path):
    """本轮(这一次用户发言之后)有没有真的读过这份链路文档。

    ⛔ 2026-08-20 当场修的坑（形状U：尺子坏了）：
       第一版只判「目录里有没有合格文档」。自测在空临时目录里全绿，
       但**真实场景下 D:/manju 早有一份 08-18 的 PIPELINE-DECISION.md 且完全合格**
       ⇒ 那条真实的错误命令会被直接放行，这道闸等于没有。
       今天的病根不是"项目里没文档"，是**我没去读它就开工**。
       ⇒ 判据改成：有文档 **且本轮读过它**才放行。
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return True  # 拿不到 transcript 就不误伤（宁放勿错杀）
    try:
        import guard_common as gc
        raw = gc.load_transcript_tail(transcript_path)
        # ⛔ load_transcript_tail 已经返回解析好的 list；再套一层 _parse_jsonl 会
        #    AttributeError → 掉进下面的兜底 return True → 闸静默失效（2026-08-20 实测）
        msgs = raw if isinstance(raw, list) else gc._parse_jsonl(raw)
        msgs = msgs[gc.turn_start_index(msgs):]
    except Exception:
        return True
    bases = [os.path.basename(d) for d in docs]
    for m in msgs:
        try:
            blob = json.dumps(m, ensure_ascii=False)
        except Exception:
            continue
        if any(b in blob for b in bases):
            return True
    return False


def check(cmd, cwd, transcript_path=None):
    if not cmd or READONLY.search(cmd) or VERIFY.search(cmd):
        return None
    if not PRODUCE.search(cmd):
        return None
    docs, rejected = find_pipeline_doc(cwd)
    if docs and read_this_turn(docs, transcript_path):
        return None
    if docs:
        detail = ("(有 %s，但你【本轮一份都没打开过】——今天的病就是这个:\n"
                  "   文档在那儿，我没读就开工。先读它，确认这一环的上下游接得上再跑)"
                  % "/".join(os.path.basename(d) for d in docs[:3]))
    elif rejected:
        detail = "(找到但不合格:%s)" % "；".join(rejected[:3])
    else:
        detail = "(当前目录一份都没有)"
    return MSG % detail


def self_test():
    import tempfile
    ok = [True]
    d = tempfile.mkdtemp()

    def t(name, cmd, cwd, want_block):
        got = check(cmd, cwd) is not None
        if got != want_block:
            ok[0] = False
        print("  [%s] %-22s -> %s" % ("PASS" if got == want_block else "FAIL",
                                      name, "拦" if got else "放"))

    real = ('mkdir -p /d/manju/novel-xtsystem && cd /d/manju/novel-xtsystem && '
            'nohup /d/manju/tools/ainovel/ainovel-cli.exe --headless --prompt "写一部..." '
            '> run_novel.log 2>&1 &')
    t("真实错误命令", real, d, True)                      # ① 今天那条
    t("ls", "ls -la radar/", d, False)                    # ② 对照组：只读全放行
    t("git status", "git status --short", d, False)
    t("ffprobe", "ffprobe -v error x.mp4", d, False)
    t("python -c 读数据", 'python -c "import sqlite3"', d, False)

    p = os.path.join(d, "PIPELINE.md")
    open(p, "w", encoding="utf-8").write("# 流水线\n步骤一二三\n")
    t("空壳文档", real, d, True)                          # ③ 放空文件绕不过

    open(p, "w", encoding="utf-8").write("# 流水线\n选题 → 剧本 → 分镜 → 出图\n")
    t("缺下游", real, d, True)                            # ④ 只写中间段绕不过

    open(p, "w", encoding="utf-8").write(
        "# 流水线\n选题/赛道 → 版权 → 剧本 → 分镜 → 出图 → 发布到平台 → 数据回收反哺\n")
    t("两头齐全", real, d, False)                         # ⑤ 合格才放行

    old = time.time() - 60 * 86400
    os.utime(p, (old, old))
    t("文档过期60天", real, d, True)                      # ⑥ 过期顶不了数

    os.remove(p)
    t("普通编辑命令", "sed -i 's/a/b/' x.txt", d, False)  # ⑦ 非生产动作放行

    # ⑧⑨ 真实场景回归（第一版就是死在这里：文档合格 ⇒ 直接放行 ⇒ 闸等于没有）
    open(p, "w", encoding="utf-8").write(
        "# 流水线\n选题/版权 → 剧本 → 出图 → 发布到平台 → 数据回收反哺观众\n")
    tp = os.path.join(d, "t.jsonl")

    def t2(name, lines, want_block):
        open(tp, "w", encoding="utf-8").write("".join(lines))
        got = check(real, d, tp) is not None
        if got != want_block:
            ok[0] = False
        print("  [%s] %-22s -> %s" % ("PASS" if got == want_block else "FAIL",
                                      name, "拦" if got else "放"))

    turn = json.dumps({"type": "user", "message": {"role": "user", "content": "继续"}},
                      ensure_ascii=False) + "\n"
    t2("文档在但本轮没读", [turn], True)
    t2("文档在且本轮读过", [turn, json.dumps(
        {"type": "assistant", "message": {"role": "assistant", "content":
         [{"type": "tool_use", "input": {"command": "cat PIPELINE.md"}}]}},
        ensure_ascii=False) + "\n"], False)

    print("\n%s" % ("全绿" if ok[0] else "有 FAIL"))
    return 0 if ok[0] else 1


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get("tool_name") not in ("Bash", "PowerShell"):
        sys.exit(0)
    cmd = (data.get("tool_input") or {}).get("command") or ""
    msg = check(cmd, data.get("cwd") or os.getcwd(), data.get("transcript_path"))
    if msg:
        sys.stderr.write(msg + "\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
