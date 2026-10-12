#!/usr/bin/env python3
"""PreToolUse(Bash) 闸:后台启动【无界的重活/GPU任务】= 启动前拦下(在它伤到机器之前)。

2026-07-24 钉死(Frank机器被搞到几小时不可用):
 - finetune_encoder.py 全微调 bge-m3 在8G上OOM【死锁挂9小时零输出】,机器不可用。
 - lora_llm_clf.py 抢96%显存拖卡桌面。
 病根:我默认启动【无界】进程(当自己在无限沙盒里),防御全是事后(gpu-watchdog=Stop)或软(skill略读)。
 缺一道【启动前】结构闸 → 本闸补上。

拦的条件(全中才拦):①Bash run_in_background(无harness超时,能挂到天荒地老)②命令跑一个 .py
 ③该 .py 含重活/GPU信号(torch/cuda/from_pretrained/Trainer/SentenceTransformer/peft/.train(…)
 ④却【没有显存封顶】(set_per_process_memory_fraction/gradient_checkpointing/量化) 或【没有硬超时】(Timer→os._exit/signal.alarm)
 = 无界重活 → deny,逼我按 local-model-sop point7 加护栏(可抄 dissat-classifier/experiments/safe_train.py)。

安全:fail-open(任何异常/读不到脚本一律放行);只读;留日志。前台重活不拦(harness自带2-10min超时兜底)。"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:            # ⛔ 必须带兜底:原来是裸 import —— guard_common 一坏,这道闸第一行就炸,
    from guard_common import hook_log      # 下面精心写的 fail-open 降级桩全成了到不了的死代码(外部critic抓到)
except Exception:
    def hook_log(*a, **k):
        pass
import sys, json, re, os, time

try:
    sys.stdout.reconfigure(encoding="utf-8"); sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launch-bound-guard.log")

HEAVY = re.compile(r"\btorch\b|\.cuda|from_pretrained|Trainer\(|SentenceTransformer|LoraConfig|get_peft_model|import peft|\.train\(|model\.fit|tensorflow|AutoModelFor|OllamaForCausal|device\s*=\s*['\"]cuda", re.I)
MEM_BOUND = re.compile(r"set_per_process_memory_fraction|gradient_checkpointing|load_in_4bit|load_in_8bit|gpu[_-]memory[_-]utilization|BitsAndBytes|quantiz", re.I)
TIME_BOUND = re.compile(r"threading\.Timer|signal\.alarm|os\._exit|--timeout|max_steps|watchdog", re.I)
# ⛔ 2026-07-25 critic 揪出 HIGH:HF Trainer / SentenceTransformer 默认就用 GPU、代码里【不写 .cuda 字面量】,
#   若靠"没写.cuda=CPU"判定→自动选设备的真GPU训练(bge-m3全微调那类)被当CPU、只凭超时放行=重开搞死机器的洞。
#   ⇒ 反过来:重活【默认当 GPU】(要显存封顶+硬超时),只有出现【正向CPU证据】才走CPU豁免(误判落安全侧=过拦)。
CPU_SIG = re.compile(
    r"device\s*=\s*['\"]cpu|\.cpu\(|\.to\(\s*['\"]cpu|torch\.device\(\s*['\"]cpu"
    r"|no_cuda\s*=\s*True|use_cpu\s*=\s*True|CUDA_VISIBLE_DEVICES\s*=\s*['\"]?\s*(?:['\"]|$)",
    re.I)
# ⛔ 核数封顶(2026-08-25 事故后加的第三维;2026-09-05 从 8-19 备份恢复本闸时重加)。
#   库层(set_num_threads/OMP_NUM_THREADS)是【建议】,OS 层(ProcessorAffinity/taskset)才是【墙】——
#   实测 6.4 核 → 3.53 核 → 1.94 核。两类都认(有总比没有强),但至少要出现一个。
#   ⛔ 与 MEM_BOUND/TIME_BOUND 一样,在【抹掉字符串字面量后】的代码上匹配,防"写在注释/字符串里骗过"。
CPU_CAP = re.compile(
    r"set_num_threads|OMP_NUM_THREADS|MKL_NUM_THREADS|OPENBLAS_NUM_THREADS"
    r"|NUMEXPR_NUM_THREADS|torch\.set_num_interop_threads"
    r"|ProcessorAffinity|sched_setaffinity|taskset|cpu_count\s*\(\s*\)\s*//",
    re.I)
# 字符串字面量里写边界词不算(critic:边界词写进 DOC=\"...\" 字符串能骗过);判边界前连字符串一起抹掉。
_STRLIT = re.compile(r'""".*?"""|\'\'\'.*?\'\'\'|"[^"\n]*"|\'[^\'\n]*\'', re.S)


def _log(m, ctx=""):
    # 2026-07-25:改用 guard_common.hook_log —— 单行追加(并发安全)+ 记项目/会话 + 大小轮转。
    # 原实现是「读最近300行→整个文件重写」,读写非原子,多项目并发收尾实测丢 74% 的行。
    # ⛔ 2026-09-07 加 ctx:记分板实测这道闸 185 次开火【100% 无证据】——
    #   消息经过这层包装后变成一个变量,拦的是哪条命令一个字都没留下。
    #   **包装一层就把证据吃掉了** ⇒ 包装函数必须把 ctx 透传下去。
    hook_log("launch-bound-guard", m, ctx)
def find_scripts(cmd):
    """从命令里抠出【所有】要跑的 .py 绝对路径(2026-07-25 修:旧版只抠第一个→链里第二个无界脚本漏)。"""
    out = []
    for m in re.finditer(r"(?:python|py)[0-9. \-]*\s+(?:-[^\s]+\s+)*[\"']?([^\s\"';|>&]+\.py)", cmd):
        path = m.group(1)
        if os.path.isabs(path) and os.path.exists(path):
            out.append(path); continue
        # ⛔ 2026-09-18 真闸实测:只认 cd ⇒ PowerShell `Set-Location X; python heavy.py` 找不到脚本
        #   ⇒ fail-open 放行无界 GPU 重活。段首切目录一律认(cd/chdir/Set-Location/Push-Location/pushd/sl)。
        cd = re.search(r"(?:^|&&|\|\||;|\n)\s*(?:cd|chdir|Set-Location|Push-Location|pushd|sl)(?:\s+/d)?\s+"
                       r"(?:-(?:Literal)?Path(?::|\s+)\s*)?[\"']?([^\"';&|\n]+?)[\"']?\s*(?:&&|\|\||;|\n|$)",
                       cmd, re.I)
        for base in ([cd.group(1).strip()] if cd else []) + [os.getcwd()]:
            cand = os.path.join(base.strip(), path)
            if os.path.exists(cand):
                out.append(cand); break
    return out


def _strip_comments(src):
    """去掉整行注释(# 开头)——边界/重活关键字只认【代码里的】,写在注释里不算(2026-07-25 修注释绕过)。"""
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


# ⛔ 2026-07-26 新增(Frank 卡到重启 Windows 之后):本闸原本【只认 GPU/ML 关键字】(见 HEAVY),
#   而真正卡死他机器的那次是【纯 CPU、几百次进程创建】的批量回归 —— 完全不在雷达上。
#   我两次手写 `python -c "...glob('test_*.py')...subprocess.run"` 批量跑,第二次还自以为
#   加了 `PriorityClass='Idle'` 就安全 —— 实测那招 **I/O 优先级纹丝不动是 Normal**,
#   而这活的重量全在 I/O。→ 现在只有 superego-regress.py 那个入口是有界的(它把 I/O 压到
#   VeryLow 并自己读回核实),所以:批量跑 Superego 回归**只能走它**,手写批量一律拦。
#   判据窄到几乎不可能误伤:必须同时命中「收集 test_*.py」和「批量执行」。
_BULK_TEST = re.compile(r"test_\*\.py|test_\*\.ps1")
_BULK_EXEC = re.compile(r"subprocess\.(run|Popen|call)|Start-Process|ForEach-Object|for\s+\w+\s+in\s+tests")
REGRESS_RUNNER = "superego-regress.py"


def _bulk_regress_check(cmd):
    """手写批量跑 Superego 回归 → 改走那个有界入口。返回拦截理由或 None。"""
    if REGRESS_RUNNER in cmd:                       # 已经走有界入口了
        return None
    if not (_BULK_TEST.search(cmd) and _BULK_EXEC.search(cmd)):
        return None
    return (
        "⛔ 资源边界闸:你在手写脚本批量跑 Superego 回归。这个动作 2026-07-26 **把 Frank 的机器卡到他重启**"
        "了一次,第二次我自以为加了 `PriorityClass='Idle'` 就安全 —— 实测那招只降 CPU,"
        "**I/O 优先级仍然是 Normal**,而这活的重量全在几百次进程创建+读盘。\n"
        "→ 改走有界入口(它把 I/O 压到 VeryLow 并【自己读回核实】,还能中途停):\n"
        "   py -3.12 C:/Users/User/.claude/superego-regress.py            # 全量\n"
        "   py -3.12 C:/Users/User/.claude/superego-regress.py --quick    # 跳过最慢那套\n"
        "   py -3.12 C:/Users/User/.claude/superego-regress.py --only critic\n"
        "(这台机器是 Frank 正在用的,不是我的沙盒。)")


# ════════════════════════════════════════════════════════════════════════════
# 扇出闸(2026-08-14 · Frank 点名的 R3)—— 治「一次开一百个小进程」
#
# ⛔ 起因:那天我后台跑一个 hook 跑分脚本,它 **34 个 hook × 3 遍 = 102 次 subprocess**,
#   每次都触发常驻语义服务的一次模型推理 ⇒ 服务烧 11 个核,Frank 当场喊卡。
#   **这道闸一次都没拦** —— 因为它上面那套判据要求脚本里含 torch/cuda/SentenceTransformer
#   这类"重活字样",而我那个脚本**一个都没有**,它只是个 subprocess 循环。
#   ⇒ 缺口的准确形状:**闸对「重活」的定义只认【单个进程的体量】,认不出【扇出放大】。**
#     危害在【倍数】,不在【体量】。
#
# ⛔ 为什么不再补一次"重活关键字"(lessons 形状 2026-08-14-E):
#   扇出的真实危害 = N × 单件成本,**这两个量静态都算不出来**。再堆多少关键字都是赌下次不漏。
#   ⇒ 换个角度:不假装能判"重不重",而是**逼我把上界声明出来** ——
#     这和它上面那套「GPU 重活必须有显存封顶+硬超时」完全是同一个逻辑,只是换到扇出维度。
#     声明得出来 = 我心里有数 = 放行;声明不出来 = 我根本不知道会开多少个 = 该拦。
#
# ⛔ 只管【后台】(和上面同范围):前台有 harness 超时兜底。
# ⛔ 判据必须是【结构】不是词面:循环里起子进程 / 进程池 / xargs -P —— 这些都是摆在那的结构。
# ⛔ 2026-09-27:「循环里起子进程」原来是一条正则(循环头 + 最多 25 行缩进更深的循环体 + 起子进程那一行)。
#   行首的空格既能算进缩进 `[ \t]+`、又能算进内容 `[^\n]*`,25 行的每种分法都要试 ⇒ 指数回溯:
#   喂 exam/score_gates.py 实测 2 分钟没跑完;Claude Code 等 10 秒就放弃、命令照跑 ⇒ 近 7 天超时 22 次 = 这 22 次没拦。
#   ⇒ 改成逐行扫,判定不变:循环头(for / while 开头、冒号结尾)往下 26 行内,碰到缩进不比它深的非空行就停,
#     中间哪一行起了子进程就算。线性时间。
_LOOP_HEAD = re.compile(r"[ \t]*(?:for|while)\b")
_SPAWN = re.compile(r"subprocess\.(?:run|Popen|call|check_output|check_call)|os\.system|os\.popen")


def _loop_spawns(code):
    lines = code.split("\n")
    for i, ln in enumerate(lines):
        if not _LOOP_HEAD.match(ln) or not ln.rstrip().endswith(":"):
            continue
        ind = ln[:len(ln) - len(ln.lstrip(" \t"))]
        for body in lines[i + 1:i + 27]:
            if not body.strip():
                continue
            if not (body.startswith(ind) and body[len(ind):len(ind) + 1] in (" ", "\t")):
                break
            if _SPAWN.search(body):
                return True
    return False


_FANOUT_POOL = re.compile(
    r"multiprocessing\.Pool|ProcessPoolExecutor|ThreadPoolExecutor|joblib\.Parallel|concurrent\.futures")
_FANOUT_SHELL = re.compile(r"xargs\s+-P|\bparallel\s+-j|\bGNU\s+parallel")
# 上界的证据(任一即可):并发封顶 / 明确的条数上限。
# ⛔ 2026-08-14 回归当场抓到:第一版把 `range(\d{1,2})` 也算上界 —— 而那天真实漏拦的脚本里
#   正好有个内层 `for _ in range(3)`(重复 3 遍),于是**它被判成"有界"、原样放行**。
#   ⇒ **内层的小循环根本不约束外层的扇出规模。** 判上界必须判【被扇出的那个集合】有多大,
#     不是判随便哪个循环的次数。范围词一律删掉,只认真正的封顶signal。
_FANOUT_BOUND = re.compile(
    r"max_workers\s*=|Semaphore\(|\[:\s*\d+\s*\]"
    r"|MAX_\w*\s*=\s*\d+|LIMIT\w*\s*=\s*\d+|--limit\b|head\s+-n?\s*\d+", re.I)
# ⛔ 显式声明必须在【原始源码】里找(它本身就是注释)。第一版在剥了注释的 code 里找 →
#   永远找不到 ⇒ 我明明写了 `# fanout-bound: 一共 6 次` 还是被拦。**判据和输入不匹配。**
_FANOUT_DECLARE = re.compile(r"#\s*fanout-bound", re.I)


def _fanout_check(cmd, script, code, raw=""):
    """返回拦截理由或 None。code 已剥注释;raw = 原始源码(找注释声明用)。"""
    if _FANOUT_SHELL.search(cmd):
        struct = "命令里有 xargs -P / parallel -j(shell 层扇出)"
    elif _FANOUT_POOL.search(code):
        struct = "脚本用了进程池/线程池(multiprocessing.Pool / *PoolExecutor / joblib)"
    elif _loop_spawns(code):
        struct = "脚本在循环里起子进程(subprocess.* / os.system)"
    else:
        return None
    if _FANOUT_DECLARE.search(raw) or _FANOUT_DECLARE.search(cmd):
        return None                      # 我已明确声明规模 = 心里有数 → 放行
    # 剥字符串再找上界证据 —— 边界词写进字符串骗不过去(和上面 bound_src 同一个理由)
    if _FANOUT_BOUND.search(_STRLIT.sub(" ", code)) or _FANOUT_BOUND.search(cmd):
        return None
    return (
        f"⛔ 资源边界闸(扇出):你要【后台】跑 `{os.path.basename(script)}`,而它会**成批地起子进程** "
        f"({struct}),却看不到任何【上界】。\n"
        "⛔ 2026-08-14 实录:我后台跑一个 hook 跑分,它 **34 个 hook × 3 遍 = 102 次 subprocess**,"
        "每次都触发常驻语义服务的一次模型推理 ⇒ 服务烧 **11 个核**,Frank 当场喊「突然很卡,是不是你造成的」。\n"
        "   **这道闸当时一次都没拦** —— 因为它只认『单个进程有多大』(torch/cuda 字样),"
        "认不出『一次开一百个』。**危害在倍数,不在体量。**\n"
        "⇒ 静态判不出 N 和单件成本,所以这里不猜重量,只要你**把上界写出来**(任一即可):\n"
        "   · 并发封顶:`max_workers=N` / `Semaphore(N)`\n"
        "   · 条数封顶:`items[:N]` / `MAX_ITEMS = N` / `--limit N`\n"
        "   · 你确实心里有数、且量很小:加一行注释 `# fanout-bound: 一共 N 次,每次约 X 秒`\n"
        "⛔ 写不出上界 = 我自己也不知道会开多少个 —— 那正是该拦的时刻。"
        "(这台机器是 Frank 正在用的,不是我的沙盒。)")


def main():
    data = json.loads(sys.stdin.read())
    if data.get("tool_name") not in ("Bash", "PowerShell"):   # 2026-07-25 修 HIGH:PowerShell 是本机主 shell,原来只认 Bash=后台重活零防护
        return
    ti = data.get("tool_input") or {}
    # ⛔ 这条【前台后台都查】:前台的 harness 超时救不了"跑了 8 分钟把用户卡死"这种,它不是挂死是占用。
    bulk = _bulk_regress_check(ti.get("command") or "")
    if bulk:
        _log("DENY(bulk-regress)", (ti.get("command") or "")[:160])
        print(bulk, file=sys.stderr)
        sys.exit(2)
    if not ti.get("run_in_background"):     # 前台有 harness 超时兜底,只管后台无界的
        _log("skip(not-bg)"); return
    cmd = ti.get("command") or ""
    # ⛔ 2026-08-14 回归抓到:shell 层扇出(xargs -P / parallel -j)必须在这里判 ——
    #   第一版把它塞进下面的 `for script in scripts` 里,而 `cat x | xargs -P 16 python worker.py`
    #   这种命令 find_scripts 往往抠不到存在的 .py ⇒ 直接从 `if not scripts: return` 走掉,
    #   **整条 shell 扇出路径永远到不了判据。**(判据放错位置 = 判据恒不执行,和写错判据一样致命。)
    if _FANOUT_SHELL.search(cmd):
        _sh = _fanout_check(cmd, cmd[:60], "", raw=cmd)
        if _sh:
            _log("DENY(fanout-shell)", cmd[:160])
            print(_sh, file=sys.stderr)
            sys.exit(2)
    scripts = find_scripts(cmd)
    if not scripts:
        _log("allow(no-py)"); return
    for script in scripts:                  # 逐个查,任一无界重活即拦
        try:
            src = open(script, encoding="utf-8", errors="replace").read()
        except Exception as e:
            _log(f"allow(read-fail:{e}):{os.path.basename(script)}"); continue
        code = _strip_comments(src)          # 只认代码里的关键字(注释不算)
        # ⛔ 扇出检查必须在 HEAVY 之前、且【独立于它】——
        #   2026-08-14 漏拦的那个脚本正是「不含任何重活字样、但会开 102 个子进程」,
        #   放在 HEAVY 之后(或跟它 and)就等于永远到不了。
        fo = _fanout_check(cmd, script, code, raw=src)   # raw=原始源码,找 # fanout-bound 声明
        if fo:
            _log(f"DENY(fanout):{os.path.basename(script)}", cmd[:160])
            print(fo, file=sys.stderr)
            sys.exit(2)
        if not HEAVY.search(code):
            continue
        bound_src = _STRLIT.sub(" ", code)   # 边界词(显存封顶/硬超时)必须是【真代码调用】,不认字符串字面量里的(堵字符串绕过)
        has_mem = bool(MEM_BOUND.search(bound_src)); has_time = bool(TIME_BOUND.search(bound_src))
        # ⛔ CPU 信号在【保留字符串的 code】上认:device='cpu'/.to('cpu') 的 cpu 本就是字符串值,抹了就认不到。
        #   (仅注释已剥;放宽方向=CPU豁免,故只信真代码里的 device=cpu,不信注释)
        is_cpu = bool(CPU_SIG.search(code))   # 正向CPU证据才算CPU;默认(含自动选设备的GPU训练)=当GPU
        # ⛔⛔ 第三维:CPU 重活还要【核数封顶】(2026-08-25 事故补,2026-09-05 从备份恢复本闸时重加)
        #   原判据「显式 CPU + 硬超时 = 放行」写于 CPU 抢占还没发生过的时候,后被实测推翻:
        #   我后台跑 SentenceTransformer(device='cpu' 且有超时),8 分钟烧 3,076 CPU 秒 ≈ 6.4 核、
        #   整机 CPU 78%,Frank 当场问「为什么我突然卡了」;停掉回落 15%。
        #   ⇒ **硬超时管「跑多久」,管不了「占多少核」**。三档实测:只设 OMP_NUM_THREADS → 6.4 核;
        #     加 torch.set_num_threads(2)+降优先级 → 3.53 核;再加 ProcessorAffinity → 1.94 核/8.1% ✅
        #   ⇒ 库层 set_num_threads 只是「建议」,操作系统层 ProcessorAffinity 才是「墙」——两者都认,
        #     但至少要出现一个,否则一个有超时的 CPU 活照样能用满全部核把他桌面拖死。
        #   ⛔ 这一维只对【CPU 分支】加严,GPU 分支判据一个字不动(别顺手放松真拦截)。
        has_cpucap = bool(CPU_CAP.search(bound_src))
        if (has_mem and has_time) or (is_cpu and has_time and has_cpucap):
            _log(f"allow(bounded{'/cpu' if is_cpu else ''}):{os.path.basename(script)}"); continue
        miss = ("显存封顶(set_per_process_memory_fraction/gradient_checkpointing/量化)" if (not is_cpu and not has_mem) else "") \
            + ("+" if (not is_cpu and not has_mem and not has_time) else "") \
            + ("硬超时(threading.Timer→os._exit/signal.alarm)" if not has_time else "") \
            + ("+核数封顶(torch.set_num_threads/OMP_NUM_THREADS/ProcessorAffinity)" if (is_cpu and not has_cpucap) else "")
        _log(f"DENY:{os.path.basename(script)} miss={miss}", cmd[:160])
        reason = (
            f"⛔ 资源边界闸:你要【后台】(无 harness 超时,能挂到天荒地老)启动重活/GPU 脚本 `{os.path.basename(script)}`,"
            f"但它缺【{miss}】——正是这个让 bge-m3 全微调挂9小时、LoRA抢96%显存把 Frank 机器搞到几小时不可用的漏洞。"
            f"按 `local-model-sop` point7 + 资源边界铁律先给它加护栏(显存封顶留头寸给桌面 + 硬超时自杀 + 心跳 + OOM保护),"
            f"可直接抄 `~/.claude/dissat-classifier/experiments/safe_train.py`。加完再后台启动。"
            f"(若确非重活/确已有等效边界,微调脚本让本闸认到关键字即可放行。)"
        )
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                         "permissionDecision": "deny", "permissionDecisionReason": reason}}, ensure_ascii=False))
        return
    _log("allow(all-clear)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open):{e}")