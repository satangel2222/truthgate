#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""collect-list-evidence-gate — 拦【给出"该向谁收多少钱"的清单,却没碰过第一手凭据】。

⛔ 来历(2026-09-09,airbnb ai manager,Frank 差点照着我的清单去重复收钱):
   我把 `owner-delivery --prepaid` 那栏"只报价"的输出**原样端给他**,列成一张
   「2026 年内还该追的」表:Alice 80/70/80、Bob 461.20/305.35。
   他没立刻去追,我自己回头逐笔核原始对话,五笔里**四笔不成立**:
     · Alice RM22 —— **她当场就付了**(09:53 发了 M2U 转账凭证)⇒ 再追 = 重复收钱
     · Bob RM33 —— **那是 TNB 电费单**,是她发来告知金额的;而且那个电箱她说
       「no need la bro」**根本没装**
     · Alice RM44(04-21) —— 那段全是图片,**文字里没这个数**,从别处误抓
     · 另有一笔 RM55 是**她自己在算分成**(「20% - RM55」)被当成垫付
   ⇒ 拿这种清单去跟房东要钱,伤的是他最贵的东西:房东关系。

⛔ 这道闸为什么必须存在(而不是又写一条"下次注意"):
   2026-07-29 我就诊断出病根 ——「**闸几乎全在验【我有没有做该做的动作】,
   验不了【做出来的东西对不对】**」,并写下正解:「**验动作是下限,验产物才是防线**」。
   42 天后(2026-09-09)记分板实测:当天 61 道闸开火 **1482 次**,
   开火前六名(lesson-anchor 261 / commitment-execution 146 / unknowing-pretending 145 /
   capability-boundary 95 / critic 80 / institutionalize 50)**全是验动作的**,
   而当天四个真错**全是产物错**⇒ 一次都没碰到。**这道闸验产物。**

⛔ 先查现成(2026-09-09,按工具去重铁律):
   · `money-verdict-gate` —— 管【商业判决】(哪条赛道能赚钱)要多个独立数据源交叉;
     当天全程 `pass(no money verdict)`。**形状不同**:那是"选方向",这是"对账要钱"。
     判据也不同(它要"源的条数",本闸要"有没有碰第一手")。⇒ **不合并**,两边注明分工。
   · `evidence-gate` / `evidence-in-log-gate` —— 管【结论有没有落日志/有没有证据段】,
     不认"这笔钱的第一手在哪"。
   · `false-done-gate` 规则3 —— 读产物,但只认测试框架的弱验证痕迹(skip/0 passed)。
   ⇒ 无可复用者,自建薄壳,同协议(exit 2 + stderr)。

判据(全中才拦,宽放窄拦):
  ① 本轮我的回复里出现【≥2 组「人名 + RM金额」配对】—— 即一份可执行的收钱清单
     (单笔提及不算:那通常是解释某个数字,不是让他去收);
  ② 且出现【追讨意图词】(追/该收/没收回/垫付/要回/欠你/去要);
  ③ 且本轮 **没有任何一次第一手查询**痕迹 —— 银行流水(bank-md/Maybank-/bank_json)、
     原始对话(wa_live.db / msg where chat_id / wa.py)、平台原件(official_reports / payoutCSV)。
  ⇒ ①②③ 同时成立 = 我在拿二手结论让他去动别人的钱。

安全:fail-open(任何异常都放行);只读;自阻断一次后放行(防死循环)。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from guard_common import hook_log, load_transcript_tail, turn_start_index, self_blocked_this_turn
except Exception:                      # 缺依赖也不能挡住他干活
    def hook_log(*a, **k):
        pass
    load_transcript_tail = None

    def turn_start_index(msgs):        # 2026-09-16 补桩:原来只靠调用处的 try 兜着
        return -1

    def self_blocked_this_turn(*a, **k):
        return True                    # 拿不到共享层 = 当作已拦过 = 放行

GATE = "collect-list-evidence"
LOG = os.path.join(HERE, "collect-list-evidence.log")

# ① 人名+金额:人名从 owner-config 读(别写死),读不到就退回通用「大写开头的名字」
MONEY = re.compile(r"RM\s?([\d,]+(?:\.\d{1,2})?)", re.I)
# ② 追讨意图 —— 只认【让他去收钱】,不认单纯提到金额
INTENT = re.compile(
    r"(该追|要追|去追|追讨|没收回|该收|要回来|去要|欠你|垫付.{0,6}(没|未)(扣|收)|收回来|"
    r"chase|collect from|not recovered|should charge)", re.I)
# ③ 第一手凭据的查询痕迹(命令/路径/SQL 片段都算)
FIRSTHAND = re.compile(
    r"(bank-md|Maybank-\d{4}|bank_json|reconcile\.bank_coverage|"
    r"wa_live\.db|wa_distilled\.db|from\s+msg\b|chat_id\s*=|scripts[/\\]wa\.py|"
    r"official_reports|payoutCSV|RemittancesExport|FetchPayoutTransactions)", re.I)


def _log(msg):
    try:
        hook_log(GATE, msg)
    except Exception:
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass


def owner_names():
    """房东名从项目配置读,不写死 —— 换项目/换人这道闸仍然成立。"""
    names = set()
    for root in (os.environ.get("CLAUDE_PROJECT_DIR") or "", os.getcwd()):
        p = os.path.join(root, "data", "owner-config.json")
        if not os.path.exists(p):
            continue
        try:
            cfg = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for v in (cfg.get("listingOwner") or {}).values():
            v = str(v).strip()
            if len(v) >= 2:
                names.add(v)
        break
    return names


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not data.get("stop_hook_active"):
        try:
            self_blocked_this_turn(GATE, turn_start=True)
        except Exception:
            pass
    else:
        try:
            if self_blocked_this_turn(GATE):
                _log("skip(self-blocked-this-turn)")
                return 0
        except Exception:
            pass

    tp = data.get("transcript_path")
    if not tp or not load_transcript_tail:
        _log("skip(no transcript)")
        return 0
    try:
        msgs = load_transcript_tail(tp)
        turn = msgs[turn_start_index(msgs) + 1:]
    except Exception:
        _log("skip(transcript unreadable)")
        return 0

    my_text, tool_text = [], []
    for m in turn:
        msg = m.get("message") or {}
        content = msg.get("content")
        role = msg.get("role") or m.get("type")
        chunks = []
        if isinstance(content, str):
            chunks = [content]
        elif isinstance(content, list):
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text":
                    chunks.append(c.get("text") or "")
                elif c.get("type") == "tool_use":
                    chunks.append(json.dumps(c.get("input") or {}, ensure_ascii=False))
                elif c.get("type") == "tool_result":
                    cc = c.get("content")
                    chunks.append(cc if isinstance(cc, str) else json.dumps(cc, ensure_ascii=False))
        joined = "\n".join(chunks)
        if role == "assistant":
            my_text.append(joined)
        tool_text.append(joined)      # 工具入参+结果都算"我碰过第一手"的痕迹

    mine = "\n".join(my_text)
    allt = "\n".join(tool_text)

    if not INTENT.search(mine):
        _log("pass(no collect intent)")
        return 0

    # ① 数「人名 + 金额」配对:同一行里既有房东名又有 RM 金额
    names = owner_names()
    # ⛔ 自检 ⑥ 打回来的:原来一行只算 1 组 ⇒「Alice RM44 和 Bob RM66 这两笔该追」
    #   (两个人两个金额写在同一行)只数出 1 组、逃过判据。改成一行里每个人名各算一组,
    #   但**上限是该行的金额个数** —— 免得「Alice 和 Bob 的报告都发了 RM77」这种
    #   一个金额配两个人被算成两组。
    pairs = []
    for line in mine.splitlines():
        n_money = len(MONEY.findall(line))
        if not n_money:
            continue
        who = [n for n in names if n and n.lower() in line.lower()]
        for n in who[:n_money]:
            pairs.append((n, line.strip()[:80]))
    if len(pairs) < 2:
        _log("pass(only %d owner+amount pair)" % len(pairs))
        return 0

    if FIRSTHAND.search(allt):
        _log("pass(first-hand checked, %d pairs)" % len(pairs))
        return 0

    _log("BLOCK(%d pairs, no first-hand): %s" % (len(pairs), pairs[:3]))
    sys.stderr.write(
        "⛔ 收钱清单证据闸:你给出了一份【该向谁收多少钱】的清单(%d 组 房东+金额),"
        "但本轮**没有碰过任何第一手凭据**。\n"
        "⛔ 2026-09-09 实录:我把工具那栏「只报价」原样端给 Frank,列了 5 笔该追的 ——"
        "自己回头逐笔核原始对话,**四笔不成立**:一笔房东当场已付(有转账凭证)、"
        "一笔是电费单被当成维修费、一笔那段根本没有那个数、一笔是房东自己在算分成。"
        "**照着追 = 跟房东重复收钱**,伤的是他最贵的东西。\n"
        "⇒ 现在逐笔去看第一手,再决定报不报:\n"
        "   · 银行流水 —— `~/Downloads/bank-md/Maybank-*.md`(先 `reconcile.bank_coverage()` 看覆盖到哪个月)\n"
        "   · 原始对话 —— `wa_live.db` 按 chat_id + 时间窗读【前后文】,不是 grep 关键词那一行\n"
        "   · 平台原件 —— `official_reports.py` / payout CSV\n"
        "⇒ 核完仍成立的才留;核不出的写「查不到凭据,先别追」——**宁可少追,不可错追**。\n"
        "(本闸只管【要钱的清单】;商业赛道判决走 money-verdict-gate,两者分工不同。)\n"
        % len(pairs))
    return 2


# ───────────────────────── 自检 ─────────────────────────
# ⛔ 写在本文件里(而不是另起 test_*.py):功能回退闸拦住了新建同名测试文件,
#   而它拦得对 —— 项目惯例本来就是 `--selftest` 内建(owner-delivery.js / room_month.py 都是)。
#   跑法: py -3.12 collect-list-evidence-gate.py --selftest
# ⛔ 正负样本【取自 2026-09-09 真实发生的两条回复】,不是编的:
#   两条都列了「房东+金额」,唯一差别是**有没有碰第一手** ⇒ 判据就该只认这个差别。
_BAD = """2026 年内真正该追的（你垫了钱、没扣回来）：
| 2026-05-27 | Alice | RM44 | 叫电工来检查 |
| 2026-05-17 | Alice | RM22 | Fix Done，rm70 |
| 2026-04-10 | Bob | RM66 | 洗衣机 |
Alice 三笔合计 230。这些都该追。"""
_GOOD = """我上一条那份追讨清单是错的，别去追：
| Alice | RM22 | 她当场就付了，发了 M2U 转账凭证 |
| Bob | RM33 | 那是电费单，不是维修费 |
所以这几笔不该追。"""
_FH = ("py -3.12 -c \"glob.glob('~/Downloads/bank-md/Maybank-2026-0*.md')\"\n"
       "sqlite3 wa_live.db select ts,text from msg where chat_id=?")
_UNREL = "npm test\nnode scripts/test_owner_recon.js"


def _selftest():
    import subprocess
    import tempfile
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or r"D:\airbnb ai manager"
    if not os.path.exists(os.path.join(proj, "data", "owner-config.json")):
        print("  跳过:找不到 owner-config.json —— 本闸的房东名从它读")
        return 0
    tmpdir = tempfile.mkdtemp(prefix="clev-selftest-")   # 只在自己建的空目录里落文件

    def run(reply, tool):
        msgs = [
            {"type": "user", "message": {"role": "user", "content": "还有什么该收的"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "input": {"command": tool}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "(output)"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": reply}]}},
        ]
        p = os.path.join(tmpdir, "t%d.jsonl" % len(os.listdir(tmpdir)))
        with open(p, "w", encoding="utf-8") as f:
            for m in msgs:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        r = subprocess.run([sys.executable, os.path.abspath(__file__)],
                           input=json.dumps({"transcript_path": p, "stop_hook_active": False}),
                           capture_output=True, text=True, encoding="utf-8", cwd=proj)
        # ⛔ 不删:临时目录由系统回收。自检产物留着还能事后查"那次为什么判这样",
        #   删它零收益、却要多写一层"确认删对了"的验证(guard-destructive 提醒得对)。
        return r.returncode, (r.stderr or "")

    ok = fail = 0

    def chk(name, cond, extra=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print("  OK   " + name)
        else:
            fail += 1
            print("  FAIL " + name + ("  " + str(extra) if extra else ""))

    print("collect-list-evidence-gate 自检")
    # ⓪ ⛔ 哨兵(2026-09-09 变异测试打回来的):跑器把本文件【整个换成空壳】时,
    #   `--selftest` 也一起没了 ⇒ 跑起来什么都不做、exit 0 ⇒ 判成"绿" = **哑尺子**。
    #   内建自检天生量不到"被测者整体消失"这一类故障。这条哨兵是我能在文件内做的补救:
    #   它**读自己的源码**,四个关键判据缺任何一个就红 —— 至少"判据被抽掉"这一档能抓住。
    #   ⛔ 真正的解法是把测试搬到独立 test_*.py(住在被注入的文件之外),
    #     但本轮被功能回退闸挡住(它把测试文件误判成"重写",且它的"写理由就放行"是纸面豁免)
    #     ⇒ 已登记 lessons 形状 2026-09-09-AJ,**没假装做完**。
    _self = open(os.path.abspath(__file__), encoding="utf-8").read()
    _miss = [k for k in ("FIRSTHAND", "INTENT", "owner_names", "len(pairs)") if k not in _self]
    chk("⓪ 哨兵:四个关键判据都在(被抽掉任一个即红)", not _miss, "缺:" + ",".join(_miss))
    if _miss:
        print("\n  哨兵已红,后面不用跑了")
        return 1
    c, e = run(_BAD, _UNREL)
    chk("① 正样本:收钱清单 + 本轮没碰第一手 ⇒ 拦", c == 2, "exit=%d" % c)
    chk("②   拦时说得出为什么(带真实病历)", "重复收钱" in e or "四笔不成立" in e)
    c, e = run(_GOOD, _FH)
    chk("③ 负样本:同样有清单,但真查了银行+原始对话 ⇒ 放行", c == 0, "exit=%d" % c)
    c, e = run("这个月 Bob 应付 RM88，已经算好了。", _UNREL)
    chk("④ 负样本:只有一个人一个金额(不是清单)⇒ 放行", c == 0, "exit=%d" % c)
    c, e = run(_BAD.replace("该追", "已收到").replace("这些都该追。", "都已入账。"), _UNREL)
    chk("⑤ 负样本:有清单但没追讨意图(在报已收)⇒ 放行", c == 0, "exit=%d" % c)
    c, e = run("Alice RM44 和 Bob RM66 这两笔该追。", _UNREL)
    chk("⑥ 边界:两组配对写在同一行也算清单 ⇒ 拦", c == 2, "exit=%d" % c)
    # ⑦ 故障注入 —— ⛔ 首版我拿 _GOOD 做,错了:那条说的是"别去追",本来就不该拦,
    #   抹不抹第一手都放行 ⇒ 测不出判据有没有在看第一手。
    #   正解:拿【确实在让他去追】的 _BAD,只切换"有没有第一手",两个方向都要验。
    c, e = run(_BAD, _FH)
    chk("⑦a 同一条『该追』的清单 + 有第一手 ⇒ 放行", c == 0, "exit=%d" % c)
    # ⛔ 注入必须抹【干净】:首版只换掉 bank-md/wa_live.db,而 `Maybank-2026-0` 和 `chat_id=`
    #   还留在字符串里 —— 判据有多个冗余信号,照样命中 ⇒ 测试报 FAIL,我差点误判成"判据坏了"。
    #   (判据其实很稳;弱注入测不出东西。故障注入要真的把那个信号抹没。)
    blind = (_FH.replace("bank-md", "xxx").replace("Maybank-", "Zzz-")
             .replace("wa_live.db", "yyy").replace("from msg", "from zzz")
             .replace("chat_id", "cid"))
    assert not FIRSTHAND.search(blind), "注入没抹干净,这条测了个寂寞"
    c, e = run(_BAD, blind)
    chk("⑦b 把第一手痕迹【彻底】抹掉 ⇒ 立刻转为拦(证明判据真在看它,不是恒真恒假)", c == 2, "exit=%d" % c)
    print("\n  %d/%d 通过" % (ok, ok + fail))
    print("  (自检产物在 %s)" % tmpdir)
    return 1 if fail else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception as e:                 # fail-open:闸自己崩了也不能挡住他
        _log("fail-open(%s)" % e)
        sys.exit(0)
