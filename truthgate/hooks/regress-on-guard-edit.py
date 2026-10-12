#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""改了 Superego 自己的代码 → 跑它的回归,红了喊。

为什么要有这道闸(2026-07-26):
  Superego 最大的风险不是"拦不住我",是【我改它的时候会把它改坏,而且自测不出来】。
  已发作 3 次,每次都是外部 critic 才抓到:
    ① launch-bound GPU 门控     ② CATASTROPHIC 裸通配     ③ 引号反转(critic 真删了一个目录才证伪)
  写"下次注意"必然失效 → 只能上机器:改完就跑回归,不等我想起来、不等 critic。
  (它上线当天就抓到两件真事:guard_common 缺测试映射、以及我把 guard_common 的 docstring 改出语法错。)

⛔ 为什么是【后台】跑(2026-07-26 外部 critic 实测后改的):
  第一版同步跑,实测端到端 **67~85 秒**,而 PostToolUse 拦不住已经写进文件的字 —— 同步毫无收益,
  纯粹是每次改 hook 都干等一分多钟。更糟的是它自己把 CPU 压满 → 对负载敏感的测试
  (test_guard_destructive_fp 在负载下实测 153.8s > 原 120s 上限)被推红 = **这道闸自己制造假红**,
  而"在最高风险文件上狼来了"正是让人以后忽略红灯的机制。
  改成:本次改动【后台】跑,结果落 .regress-result.json;下一次 hook 触发时把上一轮的红灯播报出来。
  慢一轮拿到结果,换零阻塞 + 零假红。
"""
import glob
import hashlib
import json
import re as _re
import os
import subprocess
import sys
import time

HOOKS = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.path.dirname(HOOKS)
# ⛔ 2026-07-26:原来所有后台分身写【同一个】结果文件、无锁 —— 两次改动挨得近,后一个直接覆盖
#   前一个的红灯,而红灯正是这道闸唯一的产出。改成【每个分身一个文件】(名字带 pid):零锁、
#   不可能互相覆盖,也没有"锁自旋耗尽"那条降级路径要操心。_drain 一次收走全部。
# ⛔ 2026-09-07:尊重 SUPEREGO_LOG_DIR —— 全仓其它状态(hook_log/log_path/自拦标记)都听它,
#   只有这里硬编码成 HOOKS,导致测试没法隔离:
#   `_drain()` 会 glob 所有桶并【消费掉】,跑全量时别的测试先把
#   test_regress_on_guard_edit 刚写的那份喝掉 ⇒ 它断言读不到 ⇒ 假红(单独跑就绿)。
#   没设 env 时仍是 HOOKS,生产行为一个字不变。
RESULT_DIR = os.environ.get("SUPEREGO_LOG_DIR") or HOOKS
RESULT_PAT = ".regress-result.*.json"
# ⛔ 2026-07-26(Frank「电脑突然那么卡顿」当场查出是我):这道闸原本【每次 Edit 都无条件再放飞一个
#   后台回归,不管上一个还在不在跑】。实测 14:40~14:47 七分钟里放飞 8 个、互相重叠,其中 3 个是
#   test_guard_destructive_fp(113 条样本 × 每条一个 python 子进程 × 150 秒)—— 把 Frank 正在用的
#   机器压卡了。文件头那段"后台跑"的理由只想到了【自己制造假红】,漏了【拖垮用户的机器】。
#   这正是全局「资源边界铁律」第③条:后台长活必须自带上界,绝不裸奔。→ 去重 + 并发封顶。
RUN_MARK = ".regress-running.%s.%d"      # <测试集指纹>.<pid>,分身在跑时存在
MAX_CONCURRENT = 2                       # 24 核机器上留足余量给 Frank 自己在用的东西
MARK_TTL = 400                           # 比 per-test timeout(300s)稍长;超过即视为分身崩了的僵尸标记


def _key(tests):
    """一组测试的短指纹 —— 同一组已经在跑就没必要再放一个。
    含变异测试(*_mutate*)的组带 `m` 记号:它们会把闸文件改坏再复原,期间别把文件变化当成「外部改动」(见 _outside_edits)。"""
    k = hashlib.md5(",".join(sorted(tests)).encode("utf-8")).hexdigest()[:8]
    return k + "m" if any("mutate" in t for t in tests) else k


def _mutating():
    """有没有带变异测试的后台分身正在跑(标记名里带 m 记号)。"""
    return any(_re.match(r"\.regress-running\.[0-9a-f]{8}m\.", m) for m in _live_marks())


def _claim(key):
    """抢一个并发名额:原子创建标记,成功返回路径,已被别人占了返回 None。

    ⛔ 2026-07-26 异模型二次意见抓到的 TOCTOU:第一版是【父进程数完 → 放飞 → 子进程自己写标记】,
      从 Popen 返回到子进程真正写下标记之间隔着一整个 Python 冷启动(几百毫秒),这个窗口里
      别的 hook 数到的还是旧数字 → 超额。改成【父进程用 O_EXCL 先抢名额、再放飞】:
      同一组回归的竞争由文件系统原子性彻底解决,窗口从几百毫秒缩到微秒。
      (残留风险:两个【不同组】的父进程仍可能同时数到 1 都放飞 → 偶尔 3 个而非 2 个。
       这是防压卡的软限制不是安全判据,多一个的后果只是稍慢,不值得为它引入真锁。)
    """
    p = os.path.join(RESULT_DIR, RUN_MARK % (key, os.getpid()))
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(time.time()).encode())
        os.close(fd)
        return p
    except OSError:
        return None


def _live_marks():
    """当前在跑的后台分身,顺手清掉过期僵尸标记(分身被杀时不会自己删)。"""
    now = time.time()
    live = []
    for p in glob.glob(os.path.join(RESULT_DIR, ".regress-running.*")):
        try:
            if now - os.path.getmtime(p) > MARK_TTL:
                os.remove(p)                     # 只删【确认过期】的,在跑的动不了
            else:
                live.append(os.path.basename(p))
        except OSError:
            pass
    return live


def _result_path():
    # pid % 16:够多到并发分身不会互相覆盖(实测同时最多跑一两个),又不会像裸 pid 那样
    # 每个 hook 进程留一个文件、无限堆积(调试时 10 分钟就攒了 7 个)。
    return os.path.join(RESULT_DIR, ".regress-result.%d.json" % (os.getpid() % 16))

try:
    from guard_common import hook_log
except Exception:                                        # 共用模块坏了不能拖垮这道闸(fail-open 铁律)
    # ⛔ 2026-09-07:签名要跟真的 hook_log 一致(name, msg, ctx="")。只收两个的话,
    #   走兜底路径时带触发词的调用会 TypeError,再被外层 except 吞掉 ⇒ 闸静默失效、测试还绿。
    def hook_log(name, msg, ctx=""):
        try:
            with open(os.path.join(HOOKS, name + ".log"), "a", encoding="utf-8") as f:
                f.write(msg + (" " + str(ctx) if ctx else "") + "\n")
        except Exception:
            pass

LOG = "regress-on-guard-edit"
WATCH = (os.path.join(CLAUDE, "hooks"),
         os.path.join(CLAUDE, "dissat-classifier"),
         os.path.join(CLAUDE, "superego-recall"))
EXTS = (".py", ".cjs", ".mjs", ".ps1")   # .ps1 本来漏了 —— 而启动器/快照守卫都是 .ps1(critic 抓到)

# 出现在几乎所有闸名里、没有区分度的词。做匹配时剔掉,否则 "guard" 会命中全部 test_guard_*。
NOISE = {"guard", "gate", "hook", "check", "superego", "on", "edit"}
# 名字实在对不上的:共享模块/服务的测试不叫它的名字。critic 反查出 5 个孤儿测试,这里补齐。
ALIAS = {
    # 2026-09-11 补 test_bare_allow:改 _bare_allow 时它没被自动跑(是手动跑的),而它正是记账误判的靶子
    # ⛔ 2026-09-26 补后 4 个:它们是 should_escalate 调用方自己的测试。09-19 往 should_escalate 塞了
    #   一层不看锚点的 Jev 前置,这 4 组里 3 组当场变红(能力边界误拦 5 条、不唠叨误拦滑块、留出集误拦 3/10),
    #   而原来那 4 个别名测试全绿 ⇒ 就算改动走了这道闸,也会报"全绿"。改共享判据要跑用它的人的测试。
    "guard_common": ["test_guard_exempt", "test_hook_log_concurrency", "test_intent_gates", "test_bare_allow",
                     "test_capability_boundary_gate", "test_no_nagging_semantic", "test_no_nagging_holdout",
                     "test_semantic_escalate"],
    "service": ["test_degradation_guard", "test_port_preclaim", "test_unanchored_metric", "test_recall"],
    "build_anchors": ["test_recall"],
    "start_dissat_service": ["test_start_guard"],
    "guard_settings_snapshot": ["test_guard_settings"],
    "reaper_rule": ["test-reaper"],          # 判据 2026-08-19 抽出来共享,测试仍叫旧名
}
# ⛔ 绝不自动放飞的测试:它们会动真东西(杀在跑的服务),只能由人手动跑。
#   test-selfheal-e2e.ps1 会 Stop-Process 掉 7911 上活着的实例来验自愈链 ——
#   让这道闸在后台悄悄跑它 = 每改一次文件就把 Frank 的语义层杀一次。
NO_AUTORUN = {"test-selfheal-e2e"}


def related_tests(path):
    """找跟被改文件对应的回归。

    ⛔ 2026-07-26 critic 反查:第一版用「stem 整串是否出现在测试名里」,漏了 5/29 个测试 ——
    其中 `launch-bound-guard.py` 判成 NOTEST,而它正是本闸文档第一行列的 ① 号翻车案例
    (测试就在隔壁叫 test_launch_bound.py,只是名字不含完整 stem)。**专门防这病的闸防不住这病本人。**
    改成:剔掉无区分度的词后,**核心段全部命中**才算 —— launch_bound_guard→[launch,bound]→命中。
    """
    base = os.path.splitext(os.path.basename(path))[0]
    # ⛔ 2026-08-19 补洞:NO_AUTORUN 原本只在下面的 glob 分支生效,而【改的就是测试本身】这条分支
    #   直接 return 它自己 ⇒ 绕过名单。实测:我改了一次 test-selfheal-e2e.ps1,这道闸当场把它跑了 ——
    #   而那个测试会 Stop-Process 掉正在服务的语义层。等于"每改一次这个文件就杀一次服务"。
    #   (这次侥幸无害:服务恰好已经不在,它直接 abort。侥幸不是防御。)
    if base in NO_AUTORUN:
        return []
    stem = base.replace("-", "_")
    if stem.startswith("test_"):                         # 改的就是测试本身 → 跑它自己
        return [path] if os.path.exists(path) else []
    hits = set()
    for a in ALIAS.get(stem, []):
        for d in WATCH:
            for ext in (".py", ".ps1"):
                p = os.path.join(d, a + ext)
                if os.path.exists(p):
                    hits.add(p)
    parts = [w for w in stem.split("_") if w and w not in NOISE]
    if parts:
        for d in WATCH:
            # ⛔ 2026-08-19:原来只 glob `test_*`,而 `test-reaper.ps1` 用的是【连字符】
            #   ⇒ 所有连字符命名的测试对这道闸【完全隐形】,改了共享判据它只会说"没有任何回归测试"
            #   —— 而那份测试就在同一个目录里,刚刚才咬住一个真变异。
            cands = (glob.glob(os.path.join(d, "test_*.py")) + glob.glob(os.path.join(d, "test_*.ps1"))
                     + glob.glob(os.path.join(d, "test-*.py")) + glob.glob(os.path.join(d, "test-*.ps1")))
            for t in cands:
                if os.path.splitext(os.path.basename(t))[0] in NO_AUTORUN:
                    continue
                name = os.path.basename(t).replace("-", "_").lower()
                if all(w in name for w in parts):
                    hits.add(t)
    # ⛔ 2026-09-07:改了 hooks 下的任何一道闸,顺带跑一次【合规体检】(实测 1.07 秒)。
    #   它验的是"建闸的三条不变量":接线了有没有测试 / 兜底桩签名对不对得上 /
    #   开火留不留触发词,外加故障注入欠债的棘轮。
    #   ⛔ 为什么要挂在这里而不是只放全量回归:新建一道闸的那一刻就该被拦住,
    #   否则等我跑全量时早就忘了当初为什么那么写(当天实测:体检首跑就抓到我自己刚建的闸没留证据)。
    #   —— 这正是形状 2026-09-07-J:**建议靠人记得,约束会当场变红。**
    _conf = os.path.join(HOOKS, "test_gate_conformance.py")
    if (hits and os.path.exists(_conf)
            and os.path.normcase(os.path.dirname(os.path.abspath(path)))
            == os.path.normcase(HOOKS)):
        hits.add(_conf)
    return sorted(hits)


def _runner(result_path, mark, tests):
    """后台分身:跑测试、把结果写盘。不打印给用户,由下一轮 hook 播报。

    名额标记由【父进程】在放飞前原子创建(见 _claim),这里只负责跑完还回去。
    """
    try:
        return _run_tests(result_path, tests)
    finally:
        if mark and os.path.exists(mark):                # 跑完(或崩了)都要还名额,否则被永久占住
            try:
                os.remove(mark)
            except OSError:
                pass


def _run_tests(result_path, tests):
    env_dir = os.environ.get("SUPEREGO_LOG_DIR") or os.path.join(
        os.environ.get("TEMP", HOOKS), "superego-regress-logs")
    try:
        os.makedirs(env_dir, exist_ok=True)
    except Exception:
        env_dir = HOOKS                                  # 建不了目录就退回本地,别让日志静默蒸发
    env = dict(os.environ)
    env["SUPEREGO_LOG_DIR"] = env_dir
    failed = []
    for t in tests:
        try:
            if t.endswith(".ps1"):
                cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", t]
            else:
                cmd = [sys.executable, t]
            # 300s(不是 120):负载下 test_guard_destructive_fp 实测要 153.8s,120 会误判成 TIMEOUT
            # ⛔ 2026-07-27 修【每个测试弹一个黑窗口糊在 Frank 脸上】(他截图报"一直不停弹窗打扰我打字"):
            #   派发那层(见下方 Popen)早就带了 DETACHED_PROCESS|CREATE_NO_WINDOW,但**只挡住第一层**。
            #   第一层 detach 后自己没有 console ⇒ 这里再 subprocess.run 跑每个 test 时若不带 flag,
            #   Windows 会【为每个子进程新建一个 console 窗口】—— 于是 N 个测试文件 = N 个黑窗口,
            #   而且因为 capture_output 把输出吃掉了,窗口还是全黑的、连是谁弹的都看不出来。
            #   ⇒ 子进程这层必须自己也带 CREATE_NO_WINDOW。**教训:防窗口要防到最里面那层,挡住父进程没用。**
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                               env=env, cwd=os.path.dirname(t), errors="replace",
                               **({"creationflags": 0x08000000} if os.name == "nt" else {}))
            if r.returncode != 0:
                tail = ((r.stdout or "")[-400:] + (r.stderr or "")[-400:]).strip()
                failed.append([os.path.basename(t), r.returncode, tail])
        except subprocess.TimeoutExpired:
            failed.append([os.path.basename(t), "TIMEOUT", "超过 300s"])
        except Exception as e:
            failed.append([os.path.basename(t), "ERR", str(e)[:200]])
    try:
        with open(result_path, "w", encoding="utf-8") as f:
            # ts/trigger:播报时能说清"这盏红灯是几点、改哪个文件跑出来的" —— 2026-09-16 之前
            # 一盏旧红灯在三个项目里重播了一上午,谁也不知道它是哪次改动的产物。
            json.dump({"failed": failed, "n": len(tests), "ts": time.time(),
                       "trigger": os.environ.get("REGRESS_TRIGGER", "")}, f, ensure_ascii=False)
    except Exception:
        pass


def _drain():
    """把之前后台跑出来的红灯【全部】取出来播报(播报过就清空,不重复喊)。

    ⛔ 清空用【覆写成空 JSON】而不是删文件:这是本机仅有的待播报红灯,
    读失败时什么都不动、留着下一轮再试 —— 宁可晚一轮喊,不可把红灯弄丢。
    ⛔ 收【全部】分身的文件:每个后台分身写自己 pid 的那份,不会互相覆盖(见文件头)。
    """
    failed = []
    newest_ts, trigger = 0.0, ""
    paths = sorted(glob.glob(os.path.join(RESULT_DIR, RESULT_PAT)))
    old = os.path.join(RESULT_DIR, ".regress-result.json")   # 兼容改名前留下的那份
    if os.path.exists(old):
        paths.append(old)
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue                                     # 还在写/坏了 → 原样留着,下轮再取
        failed.extend((d or {}).get("failed") or [])     # ①先把红灯搬进内存
        if isinstance(d, dict) and d.get("failed"):
            try:
                if float(d.get("ts") or 0) > newest_ts:
                    newest_ts, trigger = float(d.get("ts") or 0), str(d.get("trigger") or "")
            except (TypeError, ValueError):
                pass
        drained = isinstance(d, dict)                    # ②确认①真成功了,盘上这份才可以清
        if drained:
            # ⛔ 2026-07-26:原来是覆写成 "{}" —— 内容清了、**文件永远留着**。实测攒到 13 个
            #   (含改 pid%16 之前的裸 pid 残留),而每次 Edit/Write 都要把它们全部
            #   open+parse+覆写一遍 = 26 次纯浪费的文件 IO,只增不减。改成删掉。
            #   删不掉(Windows 上分身正占着)才退回覆写 —— 红灯此时已在 failed 里,丢不了。
            try:
                os.remove(p)
            except OSError:
                try:
                    with open(p, "w", encoding="utf-8") as f:
                        f.write("{}")
                except OSError:
                    pass
    if not failed:
        return ""
    detail = "\n".join("  · %s (rc=%s)\n    %s" % (n, rc, str(t).replace("\n", " ")[:300]) for n, rc, t in failed)
    src = ("改的是 %s" % trigger) if trigger else "触发文件未知"
    when = time.strftime("%H:%M", time.localtime(newest_ts)) if newest_ts else "时间未知"
    age = (time.time() - newest_ts) if newest_ts else None
    if age is not None and age > 30 * 60:
        # 2026-09-16:一盏 07:11 的红灯在三个项目里重播到 12:57,每次都说"上一次改动打红了"——
        # 而那几轮谁都没改闸。旧灯要说清是旧灯:债还在,但别把它算到这一轮头上。
        head = ("🔴 **旧红灯重播**(%s 跑的回归,%s;这不是这一轮改出来的,但债还没还):\n"
                % (when, src))
    else:
        head = ("🔴 **上一次改动把回归打红了**(%s,%s;改闸→自动跑,机器发现的,不是你想起来的):\n"
                % (when, src))
    return (head + "%s\n"
            "⛔ 别往下走。这正是发作过 3 次的形状:修误伤时顺手放松了真拦截。"
            "先确认红的那条是不是【必须仍拦】的对抗样本——如果是,你刚开了一个漏拦。" % detail)


FILE_RE = _re.compile(r"[\w:./\\~$-]+\.(?:py|ps1|js|cjs|mjs|sh)")
# ⛔ 2026-09-16:Bash 命令只要【提到】闸文件就当成"改了" —— rg/cat/跑测试都算。实录:我读 churn-guard.py
#   源码 3 次(rg + 跑 test_gate_conformance.py)⇒ 后台跑了 3 次回归、重播了一盏早就红着的旧灯。
#   只有命令里【对那个文件】带写入动作才算改:重定向进它 / tee / sed -i / cp、mv 到它 / git 还原它 / PowerShell 写它。
#   (`2>&1`、`> out.log` 这类不会命中:重定向后面紧跟的必须是那个闸文件本身。)
#   2026-09-16 副作用推演补的三种漏网:`cp -f 源 目标`(带参数)、`rm 闸文件`(删掉一道闸也是改)、
#   Python 代码里 `open(路径,'w')` / `Path(路径).write_text(`(bypass 模式下我真会这么写文件)。
WRITE_BEFORE = (r"(?:>>?\s*|\btee\b[^|;&\n]*|\bsed\s+-i[^|;&\n]*|\bperl\s+-p?i[^|;&\n]*"
                r"|\b(?:cp|mv|rsync|install|rm|del)\b[^|;&\n]*\s"
                r"|\bgit\s+(?:checkout|restore|apply)\b[^|;&\n]*"
                r"|(?:Set-Content|Out-File|Add-Content|Copy-Item|Move-Item|Remove-Item)[^|;&\n]*)%s")
WRITE_AFTER = r"(?:open|Path)\(\s*r?['\"]?%s['\"]?\s*(?:,\s*['\"][wa]|\)\s*\.write_(?:text|bytes)\()"


def _bash_writes(cmd, path_as_written):
    e = _re.escape(path_as_written)
    return bool(_re.search(WRITE_BEFORE % e, cmd) or _re.search(WRITE_AFTER % e, cmd))


def _spawn(label, tests, trigger, msgs):
    """放飞一组后台回归(去重 + 并发封顶)。返回 True = 这组测试已经有人在跑了(本次放飞或早已在跑)。"""
    if any(m.startswith(".regress-running.%s." % _key(tests)) for m in _live_marks()):
        # 同一组回归已经在跑 —— 再放一个纯属重复烧 CPU(密集编辑同一个文件时最常见)
        hook_log(LOG, "SKIP-DUP %s (同一组回归已在跑)" % label)
        return True
    if len(_live_marks()) >= MAX_CONCURRENT:
        hook_log(LOG, "SKIP-BUSY %s (已有 %d 个后台回归在跑,让机器喘口气)" % (label, len(_live_marks())))
        msgs.append("⏸️ 已有 %d 个后台回归在跑,这次跳过没放新的(防止把机器压卡)。"
                    "改完这一批后手动跑一次相关回归确认。" % MAX_CONCURRENT)
        return False
    mark = _claim(_key(tests))                           # 先原子抢名额,再放飞(见 _claim 的 TOCTOU 注释)
    if not mark:
        hook_log(LOG, "SKIP-RACE %s (名额刚被别人抢走)" % label)
        return False
    hook_log(LOG, "BG %s -> %s" % (label, ",".join(os.path.basename(t) for t in tests)))
    try:                                                 # 后台放飞,不等它(见文件头"为什么是后台")
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x08000000   # DETACHED_PROCESS | NO_WINDOW
        env2 = dict(os.environ)
        env2["REGRESS_TRIGGER"] = trigger                # 让结果文件记下是改哪个文件跑的
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--run",
                          _result_path(), mark] + tests,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env2, **kw)
        return True
    except Exception as e:
        hook_log(LOG, "SPAWN-FAIL %s" % str(e)[:120])
        if os.path.exists(mark):                         # 放飞失败要把名额还回去,否则永久占住
            try:
                os.remove(mark)
            except OSError:
                pass
        return False


# ⛔ 2026-09-26【外部改动账本】:这道闸只挂在 Claude Code 的 PostToolUse 上,只看得见【这一次工具调用】改的文件。
#   看不见的:Antigravity 改的、我用脚本 open(...,'w') 改的(命令里没出现那个路径)、别的会话改完还没轮到它的。
#   实录:09-19 Antigravity 往 guard_common.should_escalate 塞了一层不看锚点的 Jev,3 组回归当场变红,
#   这道闸一次没跑(那两天日志里 guard_common 零条)⇒ 带病 7 天、303 次错拦,Frank 看着我每天被拦。
#   ⇒ 每次触发顺手比一遍 WATCH 里闸文件的修改时间(实测 <10ms),变了的而且不是本次调用自己改的 ⇒ 补跑它的回归。
SEEN = os.path.join(RESULT_DIR, ".regress-seen.json")
MAX_OUTSIDE_TESTS = 30        # 外部一次改一大片(git 还原/批量重构)时的上界,别把全量回归压到他机器上


def _scan():
    now = {}
    for d in WATCH:
        try:
            for e in os.scandir(d):
                if e.is_file() and e.name.endswith(EXTS):
                    now[os.path.normcase(e.path)] = e.stat().st_mtime
        except OSError:
            pass
    return now


def _sha1(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def _outside_edits(handled, msgs):
    # ⛔ 2026-09-27 死循环实录(10 分钟被触发 47 次):后台的变异测试把闸文件【改坏再复原】,
    #    复原后内容没变、修改时间变了 ⇒ 下一次工具调用把它当成「外部改动」⇒ 又放一轮变异测试 ⇒ 又复原 ⇒ …
    #    期间所有会话跑的都是被故意改坏的闸;两轮重叠时后一轮还会把改坏的样子当成原样存下来。
    #    ⇒ ①有【变异测试】的后台分身在跑时先不判(读到的可能是改坏的中间态,下次工具调用再判,不丢);
    #      ②时间变了但内容与上次记账相同 ⇒ 不算改动。
    if _mutating():
        return
    try:
        with open(SEEN, encoding="utf-8") as f:
            seen = json.load(f)
    except Exception:
        seen = None
    hashes = dict((seen or {}).pop("__sha1__", None) or {})
    old_hashes = dict(hashes)
    now = _scan()
    changed = [] if seen is None else sorted(      # 第一次跑只立账,不补跑(否则等于全量回归)
        p for p, m in now.items()
        if p != handled and seen.get(p) != m and not (hashes.get(p) and _sha1(p) == hashes[p]))
    if changed:
        tests = sorted({t for p in changed for t in related_tests(p)})
        names = ",".join(os.path.basename(p) for p in changed[:5]) + ("…" if len(changed) > 5 else "")
        if len(tests) > MAX_OUTSIDE_TESTS:
            hook_log(LOG, "TRUNC-OUTSIDE %d 个测试只跑前 %d 个" % (len(tests), MAX_OUTSIDE_TESTS))
            tests = tests[:MAX_OUTSIDE_TESTS]
        if tests and not _spawn("外部改动 " + names, tests, "外部改动(非本次工具调用):" + names, msgs):
            for p in changed:                            # 没放出去 ⇒ 不记账,下次触发再补
                if seen.get(p) is None:
                    now.pop(p, None)
                else:
                    now[p] = seen[p]
    for p, m in now.items():                             # 记下内容指纹(只算时间变了的,一次 <10ms 量级)
        if seen is None or seen.get(p) != m or p not in hashes:
            h = _sha1(p)
            if h:
                hashes[p] = h
    if now != seen or hashes != old_hashes:
        try:
            tmp = SEEN + ".%d.tmp" % os.getpid()
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dict(now, __sha1__=hashes), f)
            os.replace(tmp, SEEN)
        except OSError:
            pass


def main():
    if len(sys.argv) > 3 and sys.argv[1] == "--run":     # 后台分身入口:<结果文件> <名额标记> <测试…>
        _runner(sys.argv[2], sys.argv[3], sys.argv[4:])
        return 0
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ""
    # 2026-08-19: matcher had only Write|Edit, but bypass mode tells me to edit via Bash
    #   => this guard was blind to every edit I made today. Real case: I edited
    #   start-dissat-service.ps1 through Bash, turned its regression test 2-red,
    #   and this guard never fired. Found only by an external review.
    if not path and data.get("tool_name") == "Bash":
        cmd = ti.get("command") or ""
        for c in FILE_RE.findall(cmd):
            c2 = os.path.expanduser(c.replace("$HOME", "~"))
            try:
                ap0 = os.path.normcase(os.path.abspath(c2))
            except Exception:
                continue
            if (any(ap0.startswith(os.path.normcase(w) + os.sep) for w in WATCH)
                    and ap0.endswith(EXTS) and os.path.exists(ap0)):
                if not _bash_writes(cmd, c):
                    hook_log(LOG, "SKIP read-only bash %s" % os.path.basename(ap0))
                    continue                             # 读它 / 跑它 ≠ 改它
                path = ap0
                break
    pending = _drain()                                   # 先播报上一轮的红灯(与本次是否命中无关)
    msgs = [pending] if pending else []

    if path:
        # ⛔ normcase:不做的话 'c:\...' 小写盘符会 startswith 失配 → 闸【静默不跑】(critic 实测)
        ap = os.path.normcase(os.path.abspath(path))
        watch = [os.path.normcase(w) for w in WATCH]
        if any(ap.startswith(w + os.sep) for w in watch) and ap.endswith(EXTS):
            tests = related_tests(path)
            if os.path.splitext(os.path.basename(ap))[0] in NO_AUTORUN:
                # 名单里的东西是【故意】不自动跑的(会动真服务),不是"没有测试"。
                # 不加这一支的话它会掉进下面的 NOTEST 分支,报一句假警告催我"补个测试"——而它自己就是测试。
                hook_log(LOG, "NO-AUTORUN %s (会动真服务,只能人手跑)" % os.path.basename(ap))
            elif not tests:
                hook_log(LOG, "NOTEST %s" % os.path.basename(ap))
                msgs.append("⚠️ 你改了 %s,但**它没有任何回归测试**。Superego 的闸没测试 = 改坏了没人知道(已发作3次)。补一个 test_*.py 再收工。"
                            % os.path.basename(path))
            else:
                _spawn(os.path.basename(ap), tests, os.path.basename(ap), msgs)

    _outside_edits(os.path.normcase(os.path.abspath(path)) if path else "", msgs)
    if msgs:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": "\n\n".join(msgs)}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
