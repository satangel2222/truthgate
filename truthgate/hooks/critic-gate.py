#!/usr/bin/env python3
"""Stop hook·Superego Phase2 外部 critic 闸(2026-07-24 迁移)——实质代码交付前,逼我先派【独立子实例】
按 Frank 的收敛7步SOP对着真 artifact 挑刺(tool-grounded),而不是我自己拍脑袋说"做完了"。

治的病:我不自发结构化自审;Frank 现在当那个"局外探测器"。CRITIC/Reflexion 已证:内省式自评失效,
只有【外部+工具落地】的审查有效 → 新 instance = 真"局外"、无"我做的所以对"偏见。

触发(全满足才拦,收窄防污染):
  (a) 本轮助手文本含【交付物工作/上线】强完成 claim(生效/跑通/修好了/已上线…,已剥文档/代码块)
  (b) 本轮真改了【代码/配置文件】(Edit/Write 命中 CODE_EXT;纯 .md 文档/记忆/PROGRESS 不算实质交付)
  (c) 本轮【没派过 critic 子实例】(无 Task/Agent 调用带 critic/审查 标记)
→ 拦一次,逼我先 invoke skill `superego-critic` 派外部审查、修完再收尾。

安全(照 false-done-gate.py):fail-open / 只拦一次:【我自己】拦过才不再拦(per-gate 标记,见 guard_common.self_blocked_this_turn);别的闸拦过不影响我 / 只读 / 窄触发 / 留日志。
MODE 一个常量可切 block|nudge|off,给 Phase4/5 调档用。"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:            # ⛔ 必须带兜底:原来是裸 import —— guard_common 一坏,这道闸第一行就炸,
    from guard_common import hook_log, turn_start_index# 下面精心写的 fail-open 降级桩全成了到不了的死代码(外部critic抓到)
except Exception:
    def turn_start_index(msgs):          # guard_common 挂了时的保守桩:-1=整份算本轮,宁可少拦
        return -1
    def hook_log(*a, **k):
        pass
import sys
import json
import re
import os
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# (原来这里有个 LOG 常量 —— 全文件零引用的死代码,早就改用 hook_log 了。2026-09-07 删)
sys.path.insert(0, HERE)
try:
    from guard_common import strip_doc, DONE_RE   # 剥文档防误伤 + 共享的加宽完成词表(finding#5)
except Exception:
    def strip_doc(t):
        return t
    DONE_RE = re.compile(r"修好了|跑通了|已上线|已部署|搞定了?|已完成|done|fixed", re.I)

# ⛔⛔ 2026-09-05 调回 block(Frank 授权彻查 superego 时改):
#   它此前停在 nudge = **只提醒、从不真拦**,回归 23 条里 8 条红,全是「期望BLOCK 实得NUDGE」。
#   代价当天可见:我改了一路代码、反复说「修好了/跑通了」,它提示了十几次、一次都没拦住 ——
#   而纯文字提示我会跳过(同 already-known-guard 记的口径:实测 30 次跳过 4 次)。
#   ⛔ 为什么现在敢调回:当初降级是为了止血 2026-07-29 那次灾难
#   (BLOCK 221 次里 176 次误伤 + 一分钟 63 次死循环),而**那两个病根后来都已单独修好**:
#     ① SELF_MAINT_RE 排除 .claude/hooks 与 .claude/superego* ⇒ 干掉 80% 的误伤
#        (那批全是「我在修这套闸,它在拦修它的人」);闸自身回归风险已由 regress-on-guard-edit.py 专管。
#     ② 每 session 冷却标记 ⇒ 干掉死循环。
#   ⇒ **止血措施留成了永久状态 = 闸活着但没牙。** 病根已除,档位就该调回来。
#   ⛔ 回滚:改回 "nudge" 即可,一个常量,秒回滚。
MODE = "block"   # block=强制档(逼我过critic) | nudge=软提示不拦 | off=停用。Phase4/5 按A/B分数调。

DONE = DONE_RE   # 用共享词表(搞定/OK了/已修复/英文…全覆盖),别再各自维护窄表

# Superego Phase3(2026-07-25):钱/数据结论盲区——critic 原只覆盖【代码】路径,钱/对账结论走 .md 报告不触发。
# 钱是最高stakes、最不能拍脑袋的。安全版=【只 nudge 不 block】(钱结论在财务项目遍地,硬拦=噪音灾难)。
# 只在【报了带数字的钱结论 + 没贴第一手来源 + 没派 critic】时软提醒。
# 钱结论的"claim"就是钱结论本身(不借用通用完成词 DONE):对账/核对/结算下了结果,或断言了多付/少付/差额+数字。
MONEY_CONCLUDE = re.compile(
    r"对账(完成|完毕|好了|结果|结论|无误|清[了完])|核对(完成|完毕|无误|一致|好了)|结算(完成|完毕|结果)"
    r"|(多付|少付|差额|欠款?|应付|应收|净收|结余)(了|是|为|共|总|达|[:：=])?\s*(RM|MYR|￥|\d)"
    r"|(确认|算出|得出|结论是?)[^。\n]{0,12}(多付|少付|差额|欠|应付|RM|MYR|\d)", re.I)
# ⛔ 2026-07-25 修误报:货币标记【必须有】(原 (元|块…)? 可选→裸数字/百分比"96.5%"也匹配→误报召回率报告为钱结论)。
MONEY_NUM = re.compile(r"RM\s*[\d,]+(\.\d+)?|MYR\s*[\d,]+(\.\d+)?|￥\s*[\d,]+(\.\d+)?|\$\s*[\d,]+|[\d,]+(\.\d+)?\s*(元|块钱?|马币|令吉|美元|人民币|港币)", re.I)
MONEY_EVIDENCE = re.compile(
    r"银行流水|银行(对账|截图|原始|记录|流水)|流水|对账单|invoice|回执|原始(响应|报表|数据|文件)"
    r"|平台(后台|导出|原始)|截图|maybank|M2U|payout|transaction|证据(如下|在此|已贴)|第一手|L1|L2", re.I)
# critic 子实例的标记:Task/Agent 调用里出现这些=本轮真派过外部审查。
# ⛔ 2026-07-24 审计 finding#7:原含裸子串 'critic',任意 Task 顺嘴带个 'critical' 就伪造豁免 → 移除裸词,
# 只认【本 skill 明确要求的 label 短语】(skill 规定 label 必含 "superego-critic 外部审查")。
CRITIC_MARK = re.compile(r"superego[-_ ]?critic|外部审查|对抗审查|挑刺审查?|critic 审", re.I)
SPAWN_TOOLS = {"Task", "Agent"}
# ⛔ 2026-07-26(Frank 限流换小号那轮暴露的设计洞):这道闸【只】认派 Claude 子实例,
#   而那恰恰是限流时最贵的动作。本机另有一条审查通道 superego-critic/second-opinion.py:
#   走第三方免费模型 = 零 Claude 额度,且是【异模型】—— 比同模型子实例更"局外"(盲区不相关),
#   实测抓到过同模型 critic 漏掉的真缺陷(占位符 \x00 冲突)。闸不认它,结果就是上一轮的实况:
#   我明明做了异模型审查,还是被拦,只好"改成过去式措辞"绕过 —— **能绕过的闸等于没有闸**。
#   → 认它,但判据必须双条件、防伪造:
#     ①assistant 真发起过跑它的 shell 调用(光 Read 它的源码不算)
#     ②对应 tool_result 里有它【成功时】那句固定尾巴(拒发/超时/失败/空 都不带这句)
#   ⛔⛔ 2026-07-29 外部 critic 实测抓到【伪造豁免】:原判据是裸文件名 `second[-_]opinion\.py`,
#     于是 `cat second-opinion.py` / `grep second-opinion.py` / `head -60 …` 都算"发起过";
#     而放行口令 SECOND_OPINION_OK 就写在那个文件【自己的 docstring 第 20 行】,
#     ⇒ tool_result 带出 docstring ⇒ so_ok=True ⇒ **看一眼源码就买到免检**。
#     critic 本轮为了审查跑了一次 `head -60 …/second-opinion.py`,那一步就足以豁免自己。
#     旧回归测不到:test_critic_gate_secondopinion.py 那条"只读源码"用的是 Read 工具,
#     而 Read 不在 SHELL_TOOLS 里 ⇒ **`cat` 走 Bash 这条路从没被测过**(测试的盲区,不只是代码的)。
#   → 判据改成【首个 token 必须是解释器】:行首,或 `&&`/`;`/`|` 之后(`cd x && py …` 是常用写法)。
#   ⛔ 2026-09-26 补:解释器前面允许一个 `timeout N` 前缀。实录:我这轮跑了两次
#     `cd ~/.claude && timeout 180 py -3.12 superego-critic/second-opinion.py …`(给外审封个上界,
#     资源边界铁律要的正是这个),两次都拿到结论,闸却说"本轮没派过外部审查" ⇒ 又被拦一轮。
#     只放这一种前缀;`timeout 60 cat …` 仍然不算(首个真命令仍必须是解释器)。
SECOND_OPINION_CALL = re.compile(
    r"(?:^|[;&|]\s*)\s*(?:timeout\s+\d+[smh]?\s+)?(?:py|python3?(?:\.\d+)?|uv\s+run)\b[^|;&]*second[-_]opinion\.py",
    re.I | re.M)

# 【高危档】—— 只有动了这些才值得花 10 分钟派 Agent 子实例;其余走 40 秒的异模型通道。
# ⛔ 判据依据(2026-07-29 实测):四轮 Agent critic 共 38 分钟,而 second-opinion 约 40 秒。
#    高危的定义 = **错了会丢钱或丢客人消息**,或者**闸自身**(它坏了会让整套防御静默失效)。
#    ⚠️ 这个词表偏保守:宁可多判几个高危,也别把生产代码放进快通道。
# regex-sanity: ok — 本职就是匹配文件路径,命中 .py/.js 是它的目的
HIGH_RISK = re.compile(
    r"(?:^|/)(?:server|connect|worker|aggregate)\.(?:js|py)$"   # 看板服务 / WhatsApp 连接器 / 后台工人
    r"|/lib/"                                                    # 业务库(钱路径、日历、对账都在这)
    # 闸自身:坏了整套防御静默失效。⛔ 但排除 test_*:测试挂了不会弄坏生产,是风险最低的产物。
    # (2026-07-29 critic 实测:本 session 20 个改动文件 17 个判高危=85%,其中 6 个是 test_* ⇒
    #  对"今天大部分时间在改闸"这个场景,分级约等于没做。加负向先行后 17→11。)
    r"|/hooks/(?!test_)[\w.-]+\.(?:py|cjs|js)$"
    # ⛔ 2026-07-29 外部 critic 抓到的盲区:上面那条只认 /hooks/ 子目录的闸,漏了 ~/.claude/ 根目录的
    #    命脉脚本 git-auto-push.sh / git-auto-init.sh —— 它们是【40+ 项目备份命脉 + PII 外泄最后一道闸】,
    #    每轮 Stop/SessionStart 跑。本轮我修它的 PII 洞时,闸只判"常规档"(该派 Agent 却只要 second-opinion),
    #    而这文件恰恰符合上面"闸自身:坏了整套防御静默失效"的定义。critic 明确建议加,理由充分,不是我自己拍脑袋。
    r"|(?:^|/)git-auto-[^/]+\.sh$"                               # 备份命脉 + PII 最后防线
    r"|(?:pnl|owner|reconcile|bank|finance|payout|tng|wise)"     # 钱相关
    r"|(?:wa_|whatsapp|baileys|connect)"                         # 客人消息通道
    r"|settings(?:\.local)?\.json$",                             # hook 接线表
    re.I)
SECOND_OPINION_OK = "它只是第三个视角"       # 只在 return 0 那条路径打印
MADE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}

# ⛔ 2026-07-28:什么样的 shell 调用才算【对现实的一次核】。
#   原来任何 shell 都算 ⇒ `git status` / `ls` / `echo` 随手一跑就买到免检金牌(lessons 早已登记未动)。
#   判据 = 命令里真的【执行了什么】:跑解释器/测试/包管理器/发请求/探服务。
#   纯查询动词(ls/cat/grep/find/head/tail/stat/wc/echo/pwd/git status|log|diff)天然不含这些词 ⇒ 不算。
#   ⚠️ 刻意不收 bash/sh —— `bash -c "ls"` 会把纯查询伪装成执行。宁可少豁免、被多拦一次。
#   ⛔ v1(整串命令任意位置匹配关键词)被外部 critic 打回:它造 16 条纯查询**全部仍能买放行**
#      (`cat src/Main.java` 命中 java、`echo "跑过 pytest 了"` 命中 pytest、`git log --grep=curl` 命中 curl),
#      同时**误堵 15 条正当验证**(`./run_tests.sh` / `bash smoke.sh` / `gh api` /
#      `opencli browser screenshot`(本项目最主力的验证通道) / `.\app.exe --selftest` / `pip install -e .`)。
#      我当时只修了 `\bpy\b` 这一个实例、没问「判据的形状对不对」—— 正是 coherence 闸要治的病,我自己犯了。
#   ⇒ v2:**按 && / || / | / ; 切段,只取每段的首个 token**(真正被执行的那个可执行文件)比对集合,
#      一次同时干掉漏放与误堵两类,而且比原正则更短。
# regex-sanity: ok — 分段用的,命中换行是本职
SEG_SPLIT = re.compile(r"\|\||&&|[|;\n]")
VERIFY_BIN = {
    "python", "python3", "py", "node", "deno", "bun", "npm", "npx", "yarn", "pnpm",
    "pytest", "tox", "cargo", "dotnet", "java", "ruby", "perl", "php", "go", "make",
    "gradle", "mvn", "pip", "pip3", "uv", "poetry",
    "curl", "wget", "httpie", "invoke-webrequest", "invoke-restmethod", "test-netconnection",
    "ruff", "eslint", "tsc", "mypy", "jest", "vitest", "mocha", "playwright",
    "netstat", "pm2", "docker", "kubectl", "systemctl", "schtasks", "start-process",
    "sqlite3", "psql", "mysql", "redis-cli", "ffmpeg", "ffprobe",
    "gh", "opencli", "codegraph", "markitdown", "bash", "sh", "pwsh", "powershell",
}
# 只问版本/帮助 = 什么都没验证,别买放行(critic 点名 `python --version` / `which python`)
VERSION_ONLY = re.compile(r"^\s*-{1,2}(v|version|h|help)\b", re.I)


def is_verify_cmd(cmd):
    """这条 shell 命令算不算【真的执行了什么】。纯结构判断,不猜语义。

    ⚠️ 已知边界(诚实标注):`bash -c "ls"` 首 token 是 bash ⇒ 会被算成验证。
       收 bash/sh 是**刻意的取舍** —— 堵死 `bash scripts/smoke.sh` 这类正当验证的代价,
       比放过一条伪装成执行的纯查询更大(前者天天发生,后者要刻意构造)。
    """
    for seg in SEG_SPLIT.split(str(cmd or "")):
        toks = seg.strip().split()
        i = 0
        while i < len(toks) and "=" in toks[i] and not toks[i].startswith("-"):
            i += 1                          # 跳过前置环境变量赋值:VAR=x cmd
        if i >= len(toks):
            continue
        t = toks[i].strip("&").lower()
        base = os.path.basename(t.replace("\\", "/"))
        rest = " ".join(toks[i + 1:])
        hit = (base in VERIFY_BIN or t.startswith("./") or t.startswith(".\\")
               or base.endswith((".sh", ".exe", ".bat", ".ps1", ".cmd")))
        if hit and not VERSION_ONLY.match(rest):
            return True
    return False
# shell 落盘代码(finding#6):重定向/tee/Set-Content/Out-File 的【目标必须是代码文件】才算实质交付。
# dogfood critic 修:原来"任意>"+"任意*.py共现"会把 `python x.py > out.log`(只是跑脚本记日志)误判成落盘代码。
_CODE_EXTS = (r"py|js|mjs|cjs|ts|tsx|jsx|json|ps1|psm1|sh|bash|html?|css|scss|go|rs|java|rb|php|c|cpp|h|hpp|"
              r"sql|vue|svelte|toml|ini|ya?ml|bat|cmd|conf|cfg|env|tf|gradle")
# ⛔ 2026-07-29 critic 实测:字符类原为 [\w./\\:-] **不含空格**,而本项目根目录就叫 `d:\airbnb ai manager`
#   ⇒ `cat > 'd:/airbnb ai manager/lib/pnl.js'` 整条 MISS ⇒ code_made=False ⇒ **整道闸直接放行**
#   (连常规档都不给)。凡带空格的路径都豁免 = 在这台机器上是结构性绕过,不是边角 case。
#   → 字符类补空格;为防吃掉后续参数,前面已有 `['\"]?` 且用非贪婪 + `\.ext\b` 收尾。
SHELL_WRITE_CODE = re.compile(
    r"(>>?|\btee\b|Set-Content|Out-File|Add-Content)\s+['\"]?[\w ./\\:-]*?\.(" + _CODE_EXTS + r")\b"
    r"|(>>?|Out-File|Set-Content)\s+['\"]?[\w ./\\:-]*Dockerfile\b", re.I)
# 实质交付=改了代码/配置。纯 .md(文档/记忆/PROGRESS/lessons/CLAUDE)不算,天然避开 Superego 自我维护轮的污染。
# ⛔ 2026-07-24 审计 finding#13:补齐 devops 配置/脚本(yaml/bat/cmd/conf/env/dockerfile)。
CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".ps1", ".psm1",
            ".sh", ".bash", ".html", ".htm", ".css", ".scss", ".go", ".rs", ".java", ".rb",
            ".php", ".c", ".cpp", ".h", ".hpp", ".sql", ".vue", ".svelte", ".toml", ".ini",
            ".yaml", ".yml", ".bat", ".cmd", ".conf", ".cfg", ".env", ".dockerfile", ".tf", ".gradle"}
# regex-sanity: ok — 就是用来认代码文件名的,命中 app.py 正确
CODE_FILE_RE = re.compile(r"[\w./\\-]+\.(py|js|mjs|cjs|ts|tsx|jsx|json|ps1|psm1|sh|bash|html?|css|scss|go|rs|"
                          r"java|rb|php|c|cpp|h|hpp|sql|vue|svelte|toml|ini|ya?ml|bat|cmd|conf|cfg|env|tf|gradle)\b"
                          r"|Dockerfile", re.I)

# ⛔⛔ 2026-08-02 复装前的必改项①:【修 superego 自己】不算"给 Frank 的交付物",不触发本闸。
#   实测账(critic-gate.log 全量):2026-07-29 当天 BLOCK 221 次,其中 **176 次(80%)** 项目名是 `hooks`
#   —— 也就是"我正在修这套闸,它在拦修它的人";全期 406 次里 187 次同因。
#   更糟的是 HIGH_RISK 把 `/hooks/*.py` 判为高危 ⇒ 强制派 Agent 子实例(实测 4 轮 38 分钟),
#   这正是 Frank 说的"逼我一轮轮派审查员 / 等 13 分钟 / 卡 6 小时"。
#   闸自身的回归风险另有专职的 regress-on-guard-edit.py 管,不该由 critic 闸重复背。
#   ⚠️ 只排 .claude/hooks 与 .claude/superego*;`.claude/` 根目录的 git-auto-*.sh(备份命脉)照旧算交付。
SELF_MAINT_RE = re.compile(r"/\.(?:claude/(?:hooks|superego[\w.-]*)|truthgate/(?:hooks|semantic))/", re.I)  # 2026-09-27 hooks、superego-semantic 搬进 ~/.truthgate，新旧路径都认


def _is_self_maint(p):
    return bool(SELF_MAINT_RE.search(str(p).replace("\\", "/")))


# ⛔⛔ 复装前的必改项②:【每 session 冷却】—— 本闸唯一的循环上限原本是 self_blocked_this_turn 的
#   per-turn 标记,而它在 `stop_hook_active=False` 的那一刻会被清掉;派出去的 critic 子实例返回时
#   带的完成通知恰好会让回合边界重置 ⇒ 标记清空 ⇒ 再拦 ⇒ 再派。实测风暴:
#   2026-07-29 11:32 一分钟 **63 次 BLOCK**、11:34 又 60 次(4 分钟内 136 次)。
#   ⇒ 加一层不依赖回合边界的硬闸门:拦过一次后 COOLDOWN_S 内一律不再拦(只记日志)。
#   语义 = 限速,不是永久关闭;冷却过了照样能拦,所以不会把闸变成摆设。
COOLDOWN_S = 1200          # 20 分钟。风暴日按此限速:221 次 → 最多 3 次


def _cooldown(sid, mark=False):
    """拦截限速。mark=True 落时间戳;否则返回"是否还在冷却中"。异常一律 False(fail-open,宁可多拦)。

    ⛔ 必须有 session_id 才限速(2026-08-02 自己踩的):没有 sid 时原本退化成全局共享的
       `nosid` 文件 —— 一装上测试就成片假 ALLOW(23 条里 7 条、19 条里 13 条),
       因为所有用例共用同一个冷却。真实 Stop payload 一定带 session_id;
       拿不到 = 合成/测试输入 ⇒ 不限速(方向与本文件其余部分一致:宁可多拦)。
    """
    sid = str(sid or "").strip()
    if not sid:
        return False
    try:
        try:
            from guard_common import _guard_dir
            d = _guard_dir()
        except Exception:
            d = HERE
        # 用 .blocked- 前缀 → 直接吃 guard_common._sweep_stale_marks 的现成清理,不另造垃圾回收
        p = os.path.join(d, ".blocked-criticcooldown-%s" % sid[:16])
        if mark:
            open(p, "w").close()
            return False
        return (time.time() - os.path.getmtime(p)) < COOLDOWN_S
    except FileNotFoundError:
        # 本 session 还没拦过 —— 这是【正常路径】不是故障,必须 False(否则第一次就被自己哑掉,闸等于没装)
        return False
    except Exception:
        # ⛔ 真故障(目录不可写/权限/路径非法)时方向必须反过来 = 当作还在冷却 ⇒ 本轮不拦。
        #   异模型二次意见 2026-08-02 抓到:原来这里一律 False,意味着冷却文件一旦写不进去,
        #   唯一的刹车片就消失 —— 那正是 63 次/分钟风暴的成因。
        #   与 guard_common.self_blocked_this_turn 落盘失败时返回 True 的判断一致:
        #   循环上限失效时,宁可少拦一次,也不能让上限静默蒸发。
        return True


try:
    from guard_common import trig   # 2026-07-28 C3:BLOCK 日志要记【惹祸的原句】
except Exception:
    def trig(s, n=120): return (s or "")[:n]

def _log(msg, ctx=""):
    # 2026-07-28 C3:加 ctx 透传【惹祸的原句】。此前 BLOCK 只记判据类别
    #   (如 "BLOCK(claimed+code+no-critic)"),事后无法判断是真拦还是误伤 ——
    #   要复算就得回去翻 transcript。trig() 早就在 guard_common 里,只是没接上。
    # 2026-07-25:改用 guard_common.hook_log —— 单行追加(并发安全)+ 记项目/会话 + 大小轮转。
    # 原实现是「读最近300行→整个文件重写」,读写非原子,多项目并发收尾实测丢 74% 的行。
    hook_log("critic-gate", msg, ctx)
def _ext(path):
    try:
        return os.path.splitext(str(path))[1].lower()
    except Exception:
        return ""


# per-gate 防死循环(见 guard_common.self_blocked_this_turn):别用全局 stop_hook_active 一刀切
try:
    from guard_common import self_blocked_this_turn
except Exception:
    def self_blocked_this_turn(*a, **k):
        return True   # 拿不到=退回旧行为(一刀切skip),绝不因此多拦


def main():
    if MODE == "off":
        return
    data = json.loads(sys.stdin.read())
    # ⛔ 2026-07-27:stop_hook_active 是 harness 的【全局】防循环标志——本轮任何一道闸拦过就为 True。
    #   原来各闸都一刀切 return,结果是【一道闸拦下之后同轮其余全部失效】:实测当天各闸被跳过
    #   giveup 84% / no-nagging 57% / false-done 57% / blame 56% / critic 53%,而跳过的恰恰是
    #   【收尾轮】(修完急着交付、最容易犯错的时刻)。防死循环只需要"我自己别连拦两次",与别的闸无关。
    if not data.get("stop_hook_active"):
        # 新一轮的首个 Stop 必定 stop_hook_active=False —— 在这一刻清掉自己的陈旧标记,
        # 否则"本轮"会退化成"最近 15 分钟"(critic 实测:仍有 26%~36% 的 skip 是被陈旧标记哑掉的)。
        self_blocked_this_turn("critic-gate", turn_start=True)
    elif self_blocked_this_turn("critic-gate"):
        _log("skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        _log("skip(no transcript)")
        return
    try:
        from guard_common import load_transcript_tail
        msgs = load_transcript_tail(tp)   # 只读尾部,别每回合重读整份历史(Frank卡顿真凶,实测44MB省~1s)
    except Exception:
        msgs = []
        for ln in open(tp, encoding="utf-8").read().splitlines():
            try:
                msgs.append(json.loads(ln))
            except Exception:
                continue

    # 定位本轮:最后一个真实 user 消息(非 tool_result)之后
    # 回合边界走 guard_common 的共享实现:本闸原来自己写了一份,和另外 5 道闸一样
    # 【漏掉了后台 Agent 完成通知】(type=user 但自称 NOT USER INPUT)⇒ 回合被重置、
    # 本轮已做的验证/审查/固化全部失效 ⇒ 反复开火。见 test_turn_boundary.py。
    last_user = turn_start_index(msgs)
    turn = msgs[last_user + 1:] if last_user >= 0 else msgs

    user_ask = ""
    if 0 <= last_user < len(msgs):
        um = msgs[last_user]
        uc = (um.get("message") or {}).get("content") or ""
        if isinstance(uc, list):
            user_ask = "\n".join(x.get("text", "") for x in uc if isinstance(x, dict) and x.get("type") == "text")
        elif isinstance(uc, str):
            user_ask = uc
        else:
            user_ask = str(uc)

    text_parts = []
    actions = []
    code_made = False          # 本轮改了代码/配置文件
    changed = []               # 改了哪些文件 —— 用来分级(见 HIGH_RISK)
    agent_critic = False       # 派过【真子实例】critic —— 它有工具,能核"我说的符不符合现实"
    bg_spawned = False         # 后台派过 critic(还要看完成通知回来没,见下面)
    bg_returned = False        # 本轮内收到了后台任务的【完成】通知 = 审查报告确实拿到了
    so_ok = False              # second-opinion 异模型成功返回 —— 只能核"代码是不是按我说的写的"
    so_called = False          # 本轮真发起过 second-opinion 调用(见 SECOND_OPINION_CALL 那段)
    # ⛔ 2026-07-27(Frank 让我审 GLM 代跑那轮时,自己撞上的设计洞):本闸原先只要
    #   second-opinion "跑成功"就放行,而放行的识别标志是它输出里那句【免责声明】"它只是第三个视角"
    #   —— 那句是成功路径【无条件打印】的,跟审查结论是 PASS 还是 NEEDS WORK 毫无关系。
    #   ⇒ 闸检测的是"你有没有走流程",不是"审出了什么" = 一台盖章机。
    #   更根本:second-opinion 只喂【代码片段 + 一句断言】给异模型,它没有浏览器/日志/任何工具,
    #   天然只能回答"代码是不是照你说的那么写的"(实录:它的全部产出就是一句同义反复),
    #   【无法验证任何关于现实的前提】(页面行为/接口返回/时序)。GLM 拿这个"同意"给一个
    #   实测零效果的修复背了书。→ 现在:真子实例照旧放行;只走 second-opinion 的,
    #   必须【改完之后真的又跑过一次】(下面 last_verify_i > last_code_i)才算数。
    last_code_i = -1           # 最后一次动代码的位置
    last_verify_i = -1         # 最后一次【非 second-opinion 的】实测调用位置
    for _i, m in enumerate(turn):
        if m.get("type") == "user":
            content = (m.get("message") or {}).get("content")
            # 后台 critic 的【完成通知】回来了没 —— 回来了才说明审查报告真拿到手
            # (通知是 type=user 的系统注入;回合边界已由 turn_start_index 正确忽略它,不会再重置本轮)
            if bg_spawned and not bg_returned:
                _t = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                if "task-notification" in _t and re.search(r"completed|finished", _t, re.I):
                    bg_returned = True
            # 只在【已发起过调用】之后才认结果,且只看 tool_result —— 光 Read 源码带出这句不算数
            if so_called and isinstance(content, list):
                for c in content:
                    if (isinstance(c, dict) and c.get("type") == "tool_result"
                            and SECOND_OPINION_OK in json.dumps(c.get("content"), ensure_ascii=False)):
                        so_ok = True
            continue
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            text_parts.append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                text_parts.append(c.get("text", ""))
            elif c.get("type") == "tool_use":
                nm = str(c.get("name", ""))
                inp = c.get("input") or {}
                _act_summary = str(inp.get("command") or inp.get("file_path") or inp.get("path") or inp.get("query") or "")[:120]
                actions.append(f"{nm}: {_act_summary}")
                fp = str(inp.get("file_path", ""))
                if (nm in MADE_TOOLS and (_ext(fp) in CODE_EXT or os.path.basename(fp).lower() == "dockerfile")
                        and not _is_self_maint(fp)):   # 修闸自己 ≠ 交付物,见 SELF_MAINT_RE
                    code_made = True
                    last_code_i = _i
                    changed.append(fp)
                # finding#6:shell 落盘代码文件也算实质交付(cat>x.py / Set-Content app.js);目标须是代码文件
                if (nm in SHELL_TOOLS and SHELL_WRITE_CODE.search(str(inp.get("command", "")))
                        and not _is_self_maint(inp.get("command", ""))):   # 同上:落盘到 hooks/ 也算自我维护
                    code_made = True
                    last_code_i = _i
                    # ⛔ 2026-07-29 critic:原来这里【不填 changed】⇒ 用 `cat > lib/pnl.js` 写钱路径时
                    #   _hi 恒空 ⇒ 判常规档 ⇒ 走快通道。整条命令串丢进去,HIGH_RISK 直接搜它即可。
                    changed.append(str(inp.get("command", "")))
                if nm in SHELL_TOOLS and SECOND_OPINION_CALL.search(str(inp.get("command", ""))):
                    so_called = True          # 条件①:真发起了。结果好不好由上面的 tool_result 判
                elif nm in SHELL_TOOLS and is_verify_cmd(inp.get("command", "")):
                    # 跑了别的东西(测试/脚本/curl)= 对【现实】的一次核。second-opinion 自己不算:
                    # 它只读代码文本,证明不了"我说的那套符合现实"。
                    # ⛔ 2026-07-28 修真漏洞(lessons 早已登记未动):原来是 `elif nm in SHELL_TOOLS:` ——
                    #   **任何** shell 调用都算实测,`git status` / `ls` / `echo` 随手一跑就买到豁免。
                    #   现在必须命中 VERIFY_EXEC = 真的【执行了什么】(跑解释器/测试/请求/服务探测),
                    #   纯查询(ls/cat/grep/git status/stat/wc/head)一律不算。宁可少豁免、被多拦一次。
                    last_verify_i = _i
                # ⛔ 2026-07-25 实测(23 次派发里 3 次 = 13%):后台派发的返回只是一张【启动回执】,
                #   里面根本没有审查内容 —— 等于加一行 run_in_background:true 就买到免检金牌。
                #   → 显式后台派发【不算】派过 critic;要豁免就同步等它把审查结果拿回来。
                # ⛔ 2026-07-25 外部 critic 抓到:上一版写 `not inp.get("run_in_background")` 基本等于没加 ——
                #   Agent 工具【默认就是后台】,模型通常省略该字段 → .get() 返回 None → falsy → 照样豁免,
                #   只有显式写 true 才拦得住,而那恰恰是最少见的写法。
                #   → 按各工具的真实默认值补:Agent 缺省=后台(不算),Task 缺省=前台(算)。
                # ⛔⛔ 2026-07-29 根因二(Frank:「我怀疑设计上有Bug才导致你无限思考不做东西」):
                #   上面那条"后台一律不算"当时是对的(后台返回只是启动回执),但它漏了一件事:
                #   **后台 Agent 跑完会把完整报告送回来**(task-notification)。于是判据变成:
                #     用后台(=本闸提示词自己建议的省时做法)→ 永远不算 → 一直拦;
                #     用前台 → 阻塞 10~15 分钟。**两条路都是坑,而且和回合边界 bug 叠成死循环。**
                #   ⇒ 判据改成【审查结果回来了没有】,而不是【派发时是不是后台】:
                #     后台派了但还没回 → 仍不算(保留原意图:防"派了就跑"买免检);
                #     后台派了且完成通知已在本轮内 → 算(报告确实拿到了)。
                if nm in SPAWN_TOOLS and CRITIC_MARK.search(json.dumps(inp, ensure_ascii=False)):
                    bg = inp.get("run_in_background")
                    if bg is None:
                        bg = (nm == "Agent")
                    if not (bg is True or str(bg).lower() == "true"):
                        agent_critic = True     # 前台派发:结果天然已拿到
                    else:
                        bg_spawned = True       # 后台派发:等下面看完成通知回来没
    # 两条审查通道的【权重不同】,不能一视同仁:
    #  · 真子实例(agent_critic):有 Read/Bash/浏览器,能核"我说的符不符合现实" → 单独就够。
    #  · second-opinion(so_ok):只拿到代码片段+一句断言,没有任何工具 → 只能核"代码是不是照我说的写的"。
    #    它证明不了那句断言对不对,所以【必须再配一次对现实的核】:改完之后真的又跑过东西
    #    (last_verify_i > last_code_i)。GLM 那轮正是:改完 → 只跑 second-opinion 拿到"同意" → 收尾,
    #    而那个修复实测零效果。这一条就是拦它的。
    # ⛔⛔ 2026-07-29 critic 判【新造的纸老虎】,实测证据:
    #   `HIGH file(connect.js) + 真跑 second-opinion + 重跑` → 闸的实际裁决 **ALLOW**。
    #   根因:_hi 原本在下面 300 多行才算,而且【只喂给提示词字符串】,从不参与放行。
    #   ⇒ "高危档必须派 Agent" 当时只是一句话,不是一条规则:我照做=10 分钟(等于没优化),
    #     我不照做=快通道静默放行 —— 两档走的是同一条 critic_ran。Frank 问的正是"能不能少一只纸老虎",
    #     结果这次改动自己生出一只。→ 把 _hi 提到这里,并真正接进判定。
    _hi = [f for f in changed if HIGH_RISK.search(str(f).replace("\\", "/"))]
    # 后台派发 + 完成通知已回 = 审查报告确实到手 ⇒ 与前台派发等价(见上面根因二)
    if bg_spawned and bg_returned:
        agent_critic = True
    critic_ran = agent_critic or (not _hi and so_ok and last_verify_i > last_code_i)
    so_only_unverified = so_ok and not agent_critic and last_verify_i <= last_code_i

    text = strip_doc("\n".join(text_parts))     # 剥文档后再判 claim,避免"描述完成"误伤
    claimed = bool(DONE.search(text))
    if not claimed:
        try:
            from guard_common import claim_kinds as _ck
            if "done" in _ck(text[-1500:], kinds=("done",)):
                claimed = True
                _log("semantic-claim(done): 词表没命中,语义判定为断言")
        except Exception:
            pass

    # ⛔⛔ 2026-09-07 L3 异构裁判【自动化】—— 治 superego 最深的根因:盲点共享。
    #   形状 2026-09-06-S(出自 Frank 自己的知识库):
    #   「生成者与评价者是同一个底座模型 —— 让一个色盲检查另一个色盲有没有看错红绿灯」。
    #   `second-opinion`(异模型、零 Claude 额度、实测 6 秒)早就有,
    #   而本闸此前做的是【打印提醒让我自己去跑】⇒ 请不请裁判还是我说了算 ⇒ 盲点原封不动。
    #   ⇒ 现在:先收上一轮发出去的裁定;异模型说【不同意】就直接拦,并贴它的原话。
    #   ⛔ 异步的理由:Stop 闸预算 25 秒,同步跑会被 harness 杀掉 = 静默失效
    #     (今晚刚量过语义层 45.5% 静默失效就是这么来的)。
    try:
        import auto_critic as _ac
        _v = _ac.read_verdict(data.get("session_id"))
        if _v:
            _verdict = _ac.classify(_v.get("answer", ""))
            _ac.clear_verdict(data.get("session_id"))
            _log("auto-critic verdict=%s (%.0fs)" % (_verdict, _v.get("elapsed", 0)))
            if _verdict == "disagree":
                _ans = (_v.get("answer") or "")[:700]
                print(json.dumps({"decision": "block", "reason": (
                    "⛔ 异构裁判(自动派出的异模型)【不同意】你上一轮那条断言。\n"
                    "⛔ 这一层存在的理由:内省式自查抓不住自己的错 —— 我写的闸、我定的判据、"
                    "我调的锚点、我写的测试,**评判者和被评判者是同一个我**,它的上限就是我的盲区。\n"
                    "被检验的断言:「%s」\n"
                    "被检查的文件:%s\n\n"
                    "异模型的原话:\n%s\n\n"
                    "⇒ 它可能是对的,也可能是它没看到全貌(它只拿到代码片段、没有任何工具)。\n"
                    "   现在二选一:**照它说的去核一遍并修**,或者**说清它哪里判错了**"
                    "(这句话会留在 log 里当证据)。"
                ) % (_v.get("claim", "")[:160], _v.get("file", ""), _ans)}, ensure_ascii=False))
                return
    except Exception:
        pass

    if claimed and code_made and not critic_ran:
        # ⛔ 限速闸门(2026-08-02):判定成立了也先看冷却——per-turn 标记挡不住回合边界被重置的连拦
        #    (实测 63 次/分钟)。这里是唯一不依赖回合边界的上限,别删。
        if _cooldown(data.get("session_id")):
            _log("skip(cooldown %ds)" % COOLDOWN_S)
            return

        # ⛔ 2026-10-10 物理真外审接入: 绝不作弊、绝不同底座自检，真实异构调用外审模型 (agnes-3.0-flash / qwen3.7-plus)
        try:
            import external_critic_engine as _ece
            c_res = _ece.review_turn(user_ask, text, actions)
            if c_res and c_res.get("verdict") == "block":
                _cooldown(data.get("session_id"), mark=True)
                reason = (
                    f"⛔ 独立外审模型({c_res.get('backend')})判定【不合格，强制打回】！\n"
                    f"【外审挑刺原因】: {c_res.get('reason')}\n"
                    f"【要求下一步动作】: {c_res.get('next')}\n\n"
                    "按 TruthGate 1.0 外审铁律：严禁在缺乏真实动作支撑时拍脑袋宣布完成！\n"
                    "请立即按照外审要求执行实测验证动作后再收尾。"
                )
                _log("BLOCK(external-critic-block)", trig(text.replace(chr(10), " "), 160))
                print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
                return
            elif c_res and c_res.get("verdict") == "pass" and c_res.get("backend") != "fail-open":
                _log(f"allow(external-critic-pass: {c_res.get('backend')})")
                return
        except Exception as _e:
            _log(f"external-critic-err: {_e}")
        # ⛔⛔ 分级(2026-07-29 Frank「为什么要 10 分钟那么久?是不是想复杂了?」——他对,数据在这):
        #    本 session 派了 4 轮 Agent critic,共 **38 分钟**(684+490+594+533 秒);
        #    而异模型 second-opinion 那次只花了 **约 40 秒** —— **快 15 倍**。
        #    ⚠️ 病根不在闸的判定逻辑(它早就允许 `so_ok + 真跑一次` 放行),
        #    **在这段提示词**:它把 Agent 写成默认、把 40 秒那条写成"额度紧张时才用" ⇒ 我每次都选贵的。
        #    ⇒ 现在按【改了什么】分档,并把便宜那条设为默认。
        _tier = "高危" if _hi else "常规"      # _hi 已在上面算过并接进了 critic_ran,这里只取名字
        # changed 里现在可能混入整条 shell 命令串(见 SHELL_WRITE_CODE 分支),basename 它会输出怪东西 ⇒ 截断。
        _names = [(os.path.basename(f) if len(f) < 120 and "\n" not in f else f.strip()[:40] + "…")
                  for f in _hi[:3]]
        reason = (
            f"⛔ 外部critic闸(Superego Phase2)·本轮判为【{_tier}档】"
            + (f":动了 {', '.join(_names)}" if _hi else "")
            + "\n你这轮改了【代码/配置】并说了「生效/跑通/修好/上线」这类实质交付 claim,但本轮【没派过外部审查】。"
            "CRITIC/Reflexion 已证:内省式自查抓不住自己的错(那些错我做的时候都觉得对),"
            "只有【独立 instance + 工具落地】的审查有效。\n"
            + ("⚡ **常规档 → 先走快的这条(约 40 秒,零 Claude 额度,而且是异模型、比我更局外)**:\n"
               "`py -3.12 C:/Users/<username>/.claude/superego-critic/second-opinion.py "
               "--claim \"<一条具体可验证的断言>\" --file <你改的文件> --lines a:b`\n"
               "⛔ 它【只】证明「代码是照你说的写的」,证明不了「你说的那套符合现实」(它没有任何工具),"
               "所以**必须改完之后真的再跑一次**(测试/脚本/curl)——两者合起来才放行。\n"
               "只有当这条给不出结论、或你自己觉得这次风险被低估了,才升级去 invoke skill `superego-critic`。\n"
               if not _hi else
               "🔴 **高危档(生产代码/钱路径/闸自身)→ 必须派 Agent 子实例**,别用快通道抵:\n"
               "invoke skill `superego-critic`,喂它本轮改的文件 + 收敛7步SOP"
               "(症状≠根因/前提逐条验/有参照就diff/反转假设/穷尽/叠层根因/修一处扫全身),"
               "让它对着真 artifact 挑刺;报的真洞先修+复验再收尾。\n"
               "⛔ 这一档【不接受】只跑 second-opinion:异模型没有浏览器/日志/数据库,"
               "核不了'你说的那套符不符合现实'——而这一档错了要么丢钱、要么丢客人消息。\n"
               "💡 想省时间就 `run_in_background: true` 派出去、自己继续干别的,别干等。\n")
            + "(若这轮并非实质交付、claim 只是复述历史,改成过去式措辞即可放行。)"
            + ("\n\n⚠️ 本轮就是这个情形:你跑了 second-opinion 并拿到回复,但【最后一次改代码之后没有再跑过任何东西】。"
               "异模型的'同意'不是放行证 —— 2026-07-27 实录:一个实测【零效果】的修复就是这样拿到'同意'并被宣布的。"
               "去把改完的东西真跑一次,再回来收尾。" if so_only_unverified else ""))
        if MODE == "nudge":
            _log("NUDGE(claimed+code+no-critic)")
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}}, ensure_ascii=False))
        else:
            _cooldown(data.get("session_id"), mark=True)   # 真拦了才起冷却(nudge 档不拦→不限速)
            # ⛔ 顺手把【这轮的断言 + 改的文件】发给异模型,下一轮收裁定。
            #   发的动作是后台 detached 的,不占本闸的 25 秒预算;发不出去也不影响这次拦截。
            try:
                import auto_critic as _ac2
                if not _hi:                      # 只在常规档用;高危档必须派 Agent(异模型没工具)
                    _ac2.fire(_ac2.pick_claim(text), list(changed), data.get("session_id"))
            except Exception:
                pass
            _log("BLOCK(claimed+code+no-critic)", trig(text.replace(chr(10), " "), 160))
            print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    elif (not code_made and not critic_ran
          and MONEY_CONCLUDE.search(text) and MONEY_NUM.search(text) and not MONEY_EVIDENCE.search(text)):
        # 钱/数据结论盲区(nudge-only,绝不 block):报了带数字的钱结论却没第一手来源、也没派 critic
        mreason = (
            "⛔ 钱/数据结论 critic 提醒(Superego Phase3·软提醒不拦):你这轮给出【钱/对账/结算类结论(带数字)】,"
            "但没贴第一手来源(银行流水/平台原始/对账单/截图),也没派外部审查。钱的结论最高 stakes、最不能拍脑袋——"
            "按证据阶梯:数字只认 L1平台原生/L2银行流水。收尾前要么贴出第一手证据,要么 invoke skill `superego-critic` "
            "让独立子实例核一遍这个钱结论对不对。(软提醒、不拦你;但钱错代价大。)")
        _log("NUDGE(money-conclusion+no-evidence+no-critic)")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": mreason}}, ensure_ascii=False))
    else:
        _log(f"allow(claimed={claimed},code_made={code_made},critic_ran={critic_ran},secondopinion={so_called})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")
