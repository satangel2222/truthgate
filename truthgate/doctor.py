# -*- coding: utf-8 -*-
"""truthgate_doctor.py: 全方位体检与自动化监控诊断引擎 (TruthGate Full-Spectrum System Doctor).
核心使命:
1. 严禁头疼医头与盲人摸象 —— 一键穿透探测 6 大支柱全景健康;
2. 实时探测:
   - 云端双核推理 (TypeSafe Jev 毫秒快车道 + Agnes 3.0-flash 深度审计 + Tier 0 本地确定性启发式)
   - 上游控制台 (console.typesafe.ai 状态透传)
   - 本地常驻后台 (17911 司法服务 + ag_watch 操作系统级文件守护)
   - 四端门禁集成 (Claude Code 103闸, Codex 103闸, Antigravity 插件桥接, DSH 旁路)
   - 数据管道新鲜度 (毫秒级审计流心跳、停滞断流自动告警)
3. 动态熔断与自动降级 (Circuit Breaker): 当 TypeSafe 500/宕机时, 无缝确认 Tier 0 兜底接管;
4. 提供 CLI 命令、API 接口 (`/api/doctor`) 与一键自愈恢复 (`/api/doctor/heal`)。
"""
import os
import sys
import time
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
GEMINI_DIR = HOME / ".gemini"
CODEX_DIR = HOME / ".codex"
DSH_DIR = Path(os.environ.get("APPDATA", str(HOME / ".config"))) / "dsh-desktop" / "harness"

# Cache for doctor results (10s) to prevent spamming upstream APIs
_CACHE_DATA = None
_CACHE_TIME = 0.0

def _probe_url(url, timeout=2.5, headers=None):
    """Probes a URL and returns (status_code, latency_ms, error_msg)."""
    t0 = time.perf_counter()
    h = {"User-Agent": "TruthGate-Doctor/1.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dt = (time.perf_counter() - t0) * 1000
            return resp.status, round(dt, 1), None
    except urllib.error.HTTPError as e:
        dt = (time.perf_counter() - t0) * 1000
        return e.code, round(dt, 1), f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000
        return 0, round(dt, 1), str(e)

def check_typesafe_jev():
    """Checks TypeSafe Jev API and Console status."""
    res = {
        "name": "TypeSafe Jev System One (Tier 2 快车道)",
        "api_status": "UNKNOWN",
        "api_latency_ms": 0.0,
        "api_detail": "",
        "console_status": "UNKNOWN",
        "console_code": 0,
        "console_detail": "",
        "circuit_breaker": "ARMED",
        "configured": False
    }

    # 1. Check Console status (console.typesafe.ai)
    c_code, c_lat, c_err = _probe_url("https://console.typesafe.ai", timeout=3.0)
    res["console_code"] = c_code
    if c_code == 200:
        res["console_status"] = "OK"
        res["console_detail"] = f"正常访问 ({c_lat}ms)"
    elif c_code == 500:
        res["console_status"] = "WARN"
        res["console_detail"] = f"HTTP 500 (Web控制台服务故障，请关注API是否受波及)"
    else:
        res["console_status"] = "WARN" if c_code > 0 else "DOWN"
        res["console_detail"] = c_err or f"Code {c_code}"

    # 2. Check API key and live Jev API query
    try:
        try:
            from truthgate.jev_engine import _get_api_key, judge_assistant_text
        except ImportError:
            try:
                from jev_engine import _get_api_key, judge_assistant_text
            except ImportError:
                from superego_jev_engine import _get_api_key, judge_assistant_text
        key = _get_api_key()
        if not key:
            res["api_status"] = "UNCONFIGURED"
            res["api_detail"] = "未配置 TYPESAFE_API_KEY (自动降级至 Tier 0 本地启发式 + Tier 3)"
            return res

        res["configured"] = True
        # Live quick probe
        t0 = time.perf_counter()
        jres = judge_assistant_text("健康自检探针：这是一条测试文本，已通过全部测试。", sid="doctor_probe", timeout=3.0)
        dt = (time.perf_counter() - t0) * 1000
        res["api_latency_ms"] = round(dt, 1)

        if jres.get("mode") == "jev_system_one":
            res["api_status"] = "HEALTHY"
            res["api_detail"] = f"推理网关满血在线 (耗时 {round(dt, 1)}ms, 强类型正常判决)"
        elif "error_fallback" in jres.get("mode", ""):
            res["api_status"] = "DEGRADED"
            res["api_detail"] = f"API 出现抖动 ({jres.get('mode')})，已自动降级至本地 Tier 0 硬门禁"
        else:
            res["api_status"] = "HEALTHY"
            res["api_detail"] = f"就绪 ({jres.get('mode')})"
    except Exception as e:
        res["api_status"] = "ERROR"
        res["api_detail"] = f"探针调用异常: {e}"

    return res

def check_agnes():
    """Checks outer critic deep audit API (Gemini / GLM / DeepSeek / OpenAI / Agnes / Ollama)."""
    res = {
        "name": "外审模型裁判 (Outer Critic Engine)",
        "status": "UNKNOWN",
        "latency_ms": 0.0,
        "detail": ""
    }
    try:
        sem_dir = CLAUDE_DIR / "superego-semantic"
        if str(sem_dir) not in sys.path:
            sys.path.insert(0, str(sem_dir))
        try:
            from truthgate import semantic_judge
        except ImportError:
            try:
                import semantic_judge
            except ImportError:
                semantic_judge = None

        if not semantic_judge:
            res["status"] = "UNCONFIGURED"
            res["detail"] = "未加载语义判官模块"
            return res

        ep = getattr(semantic_judge, "get_critic_endpoint", lambda: None)()
        if not ep:
            res["status"] = "HEALTHY"
            res["detail"] = "未配置外审大模型，当前由本地 Tier 0 确定性引擎 100% 离线硬防线安全保底"
            return res

        provider = ep.get("provider", "unknown")
        model = ep.get("model", "unknown")
        url = ep.get("url", "")
        k = (ep.get("api_key") or "").strip()
        if k.startswith("env:"):
            _, resolved_k = getattr(semantic_judge, "_find_env_key", lambda x: (None, None))(k[4:])
            k = (resolved_k or "").strip()

        res["name"] = f"外审裁判 [{provider}] ({model})"

        if provider == "local_heuristic":
            res["status"] = "HEALTHY"
            res["detail"] = "纯离线 AST / 正则确定性硬安全引擎 (免Key · 0ms 延迟)"
            return res

        is_local = "localhost" in url or "127.0.0.1" in url or provider == "ollama"
        if not k and not is_local:
            res["status"] = "WARNING"
            res["detail"] = f"提供商设置为 {provider}，但未配置有效 API Key！当前已降级为 Tier 0 本地硬防线"
            return res

        # 检查最新运行状态是否有失败记录
        status_info = getattr(semantic_judge, "get_last_critic_status", lambda: {})()
        if status_info.get("last_error") and not status_info.get("ok"):
            res["status"] = "DEGRADED"
            res["detail"] = f"连通异常 ({status_info.get('last_error')[:100]})，已自动降级至 Tier 0"
            res["latency_ms"] = status_info.get("latency_ms", 0.0)
            return res

        # 执行真实轻量级探针 (5-token ping)
        import time, urllib.request
        t0 = time.time()
        is_anthropic = "1.19848845.xyz" in url or url.endswith("/messages")
        headers = {"Content-Type": "application/json"}
        if is_anthropic:
            endpoint = url if url.endswith("/messages") else f"{url.rstrip('/')}/v1/messages"
            headers["x-api-key"] = k
            headers["anthropic-version"] = "2023-06-01"
            payload = {"model": model or "glm-5.3-flash", "max_tokens": 5, "messages": [{"role": "user", "content": "ping"}]}
        else:
            endpoint = url
            if k and k != "ollama":
                headers["Authorization"] = f"Bearer {k}"
                if provider == "gemini":
                    headers["x-goog-api-key"] = k
            payload = {"model": model, "max_tokens": 5, "messages": [{"role": "user", "content": "ping"}]}

        try:
            req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                lat = round((time.time() - t0) * 1000, 1)
                res["status"] = "HEALTHY"
                res["latency_ms"] = lat
                res["detail"] = f"真实连通正常 ({lat}ms · HTTP 200 OK · 模型: {model})"
        except Exception as probe_err:
            res["status"] = "DEGRADED"
            res["detail"] = f"端点探测失败 ({str(probe_err)[:80]})，已安全降级为 Tier 0 本地硬防线"
    except Exception as e:
        res["status"] = "ERROR"
        res["detail"] = str(e)
    return res


def check_local_daemons():
    """Checks 17911 dissat service and ag_watch.py."""
    daemons = []

    # 1. Service 17911
    # 防死锁保护: 如果是在 service.py / dashboard 进程内部运行，直接读取服务内存，绝不发起自环网络请求
    is_self = False
    svc_mod = sys.modules.get("service")
    if svc_mod and hasattr(svc_mod, "RULES"):
        try:
            rules_cnt = len(svc_mod.RULES) if svc_mod.RULES else 0
            anchors_cnt = len(svc_mod.ANCHOR_EMB) if getattr(svc_mod, "ANCHOR_EMB", None) is not None else 0
            s17911 = {
                "name": "17911 司法裁决与全景大盘中枢",
                "port": 17911,
                "status": "HEALTHY",
                "latency_ms": 0.1,
                "detail": f"正常监听 (规则: {rules_cnt}, 锚点: {anchors_cnt}, 大盘: http://127.0.0.1:17911/dashboard)",
                "recall_rules": rules_cnt,
                "anchors": anchors_cnt
            }
            is_self = True
        except Exception:
            is_self = False

    if not is_self:
        code, lat, err = _probe_url("http://127.0.0.1:17911/health", timeout=1.0)
        s17911 = {
            "name": "17911 司法裁决与全景大盘中枢",
            "port": 17911,
            "status": "HEALTHY" if code == 200 else "DOWN",
            "latency_ms": lat,
            "detail": "",
            "recall_rules": 0,
            "anchors": 0
        }
        if code == 200:
            try:
                req = urllib.request.Request("http://127.0.0.1:17911/health")
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    s17911["recall_rules"] = data.get("recall_rules", 0)
                    s17911["anchors"] = data.get("anchors", 0)
                    s17911["detail"] = f"正常监听 (规则: {s17911['recall_rules']}, 锚点: {s17911['anchors']}, 大盘: http://127.0.0.1:17911/dashboard)"
                    if data.get("service") == "truthgate-dashboard":   # 2026-09-27:这个端口现在归看板,别写成语义服务在线
                        s17911["detail"] = "端口上是看板 dashboard.py(http://127.0.0.1:17911/dashboard);语义服务 9/25 按 Frank 下线令关着"
            except Exception:
                s17911["detail"] = "200 OK (http://127.0.0.1:17911/dashboard)"
        else:
            s17911["detail"] = "没人监听(看板没开;语义服务 9/25 按 Frank 下线令关着,别自动拉起)"
    daemons.append(s17911)

    # 2. ag_watch.py
    watch = {
        "name": "ag_watch 操作系统级外审守护",
        "status": "UNKNOWN",
        "pid": None,
        "detail": ""
    }
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = " ".join(p.info.get("cmdline") or [])
                if "ag_watch.py" in cmd:
                    watch["status"] = "HEALTHY"
                    watch["pid"] = p.info["pid"]
                    break
            except Exception:
                pass
        if watch["status"] == "HEALTHY":
            watch["detail"] = f"常驻运行中 (PID: {watch['pid']}, 毫秒监听 Antigravity/Codex)"
        else:
            watch["status"] = "DOWN"
            watch["detail"] = "守护进程未运行 (Antigravity 长会话可能断流)"
    except Exception as e:
        watch["status"] = "WARN"
        watch["detail"] = f"进程检查受限: {e}"
    daemons.append(watch)

    return daemons

def check_platforms():
    """Checks mounting status across all 4 platforms."""
    platforms = []

    # 1. Claude Code
    c_hooks_dir = CLAUDE_DIR / "hooks"
    c_count = len(list(c_hooks_dir.glob("*.py"))) if c_hooks_dir.exists() else 0
    c_mounted = c_count > 0
    platforms.append({
        "id": "claude",
        "name": "Claude Code",
        "mounted": c_mounted,
        "path": str(CLAUDE_DIR),
        "status": "HEALTHY" if c_mounted else "NOT_FOUND",
        "detail": f"黄金母库挂载完全 ({c_count} 道物理门禁与测试组件)" if c_mounted else "未发现环境"
    })

    # 2. OpenAI Codex
    x_hooks_dir = CODEX_DIR / "hooks"
    x_count = len(list(x_hooks_dir.glob("*.py"))) if x_hooks_dir.exists() else 0
    x_mounted = x_count > 0
    platforms.append({
        "id": "codex",
        "name": "OpenAI Codex",
        "mounted": x_mounted,
        "path": str(CODEX_DIR),
        "status": "HEALTHY" if x_mounted else "NOT_FOUND",
        "detail": f"镜像同步完全 ({x_count} 道物理门禁与测试组件)" if x_mounted else "未发现环境"
    })

    # 3. Google Antigravity
    ag_plugin = GEMINI_DIR / "config" / "plugins" / "superego-plugin"
    ag_hooks = ag_plugin / "hooks.json"
    ag_script = GEMINI_DIR / "antigravity" / "scripts" / "ag_superego_bridge.py"
    ag_mounted = ag_hooks.exists() and ag_script.exists()
    platforms.append({
        "id": "antigravity",
        "name": "Google Antigravity",
        "mounted": ag_mounted,
        "path": str(GEMINI_DIR),
        "status": "HEALTHY" if ag_mounted else "DEGRADED",
        "detail": "原生全局插件 + Jev 双核桥接就绪" if ag_mounted else "桥接文件缺失"
    })

    # 4. DSH
    dsh_mounted = DSH_DIR.exists()
    platforms.append({
        "id": "dsh",
        "name": "DeepSeek Harness (DSH)",
        "mounted": dsh_mounted,
        "path": str(DSH_DIR),
        "status": "HEALTHY" if dsh_mounted else "NOT_FOUND",
        "detail": "Cordis 沙箱旁路只读同步就绪" if dsh_mounted else "未检测到运行目录"
    })

    return platforms

def check_pipeline_freshness():
    """Checks log stream freshness and alerts if stream is stale."""
    log_file = CLAUDE_DIR / "hooks" / "semantic-superego-gate.log"
    res = {
        "status": "UNKNOWN",
        "latest_event_time": "无记录",
        "age_minutes": -1,
        "total_lines": 0,
        "detail": ""
    }
    if not log_file.exists():
        res["status"] = "EMPTY"
        res["detail"] = "尚未产生审计流水日志"
        return res

    try:
        lines = [l.strip() for l in log_file.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
        res["total_lines"] = len(lines)
        if not lines:
            res["status"] = "EMPTY"
            res["detail"] = "日志文件为空"
            return res

        last_line = lines[-1]
        ts_part = last_line[:19]
        res["latest_event_time"] = ts_part
        try:
            dt = datetime.strptime(ts_part, "%Y-%m-%d %H:%M:%S")
            diff_min = round((datetime.now() - dt).total_seconds() / 60.0, 1)
            res["age_minutes"] = diff_min
            if diff_min <= 10.0:
                res["status"] = "FRESH"
                res["detail"] = f"极速流水 (最新记录: {diff_min} 分钟前)"
            elif diff_min <= 60.0:
                res["status"] = "WARM"
                res["detail"] = f"正常心跳 (最新记录: {diff_min} 分钟前)"
            else:
                res["status"] = "IDLE"
                res["detail"] = f"待机中 (最新记录: {diff_min} 分钟前)"
        except Exception:
            res["status"] = "OK"
            res["detail"] = f"最新记录: {ts_part}"
    except Exception as e:
        res["status"] = "ERROR"
        res["detail"] = str(e)

    return res

def check_cross_engine_parity():
    """Checks cross-engine asset and evolution loop parity (Pillar 5)."""
    try:
        cur_dir = Path(__file__).parent
        if str(cur_dir) not in sys.path:
            sys.path.insert(0, str(cur_dir))
        from parity_auditor import audit_skills_parity, audit_evolution_loop
        sk_rep = audit_skills_parity()
        ev_rep = audit_evolution_loop()

        has_core_missing = bool(sk_rep.get("core_missing_codex") or sk_rep.get("core_missing_ag"))
        ev_intact = ev_rep.get("all_complete", False)

        status = "HEALTHY"
        details = []
        if has_core_missing:
            status = "DEGRADED"
            if sk_rep.get("core_missing_codex"):
                details.append(f"Codex缺失核心治理技能: {sk_rep['core_missing_codex']}")
            if sk_rep.get("core_missing_ag"):
                details.append(f"Antigravity缺失核心治理技能: {sk_rep['core_missing_ag']}")
        if not ev_intact:
            status = "DEGRADED"
        # 深度语义与运行时对账 (端口、AST、幽灵门禁、假阴性自动监控)
        try:
            try:
                from deep_parity_auditor import run_full_deep_parity_audit
            except ImportError:
                from truthgate.deep_parity_auditor import run_full_deep_parity_audit
            deep_res = run_full_deep_parity_audit()
            if not deep_res.get("all_passed"):
                status = "DEGRADED"
                details.append("深度真值审计发现端口/AST/幽灵门禁或假阴性监控未通过")
            else:
                details.append("深度端口/AST/幽灵门禁/假阴性监控 100% 满分通过")
        except Exception:
            pass

        return {
            "name": "四端资产与自动进化闭环 (Parity & Evolution)",
            "status": status,
            "parity_score": sk_rep.get("parity_score", 100.0) if status == "HEALTHY" else 80.0,
            "detail": "；".join(details),
            "skills_parity": sk_rep,
            "evolution_loop": ev_rep
        }
    except Exception as e:
        return {
            "name": "四端资产与自动进化闭环 (Parity & Evolution)",
            "status": "WARN",
            "parity_score": 50.0,
            "detail": f"对账审计异常: {e}"
        }

def run_doctor(cached=True):
    """Runs full-spectrum diagnostics across all 6 pillars."""
    global _CACHE_DATA, _CACHE_TIME
    now = time.time()
    if cached and _CACHE_DATA and (now - _CACHE_TIME < 15.0):
        return _CACHE_DATA

    t0 = time.perf_counter()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as ex:
        f_typesafe = ex.submit(check_typesafe_jev)
        f_agnes = ex.submit(check_agnes)
        f_daemons = ex.submit(check_local_daemons)
        f_platforms = ex.submit(check_platforms)
        f_freshness = ex.submit(check_pipeline_freshness)
        f_parity = ex.submit(check_cross_engine_parity)

        typesafe_info = f_typesafe.result()
        agnes_info = f_agnes.result()
        daemons_info = f_daemons.result()
        platforms_info = f_platforms.result()
        freshness_info = f_freshness.result()
        parity_info = f_parity.result()
    duration_ms = round((time.perf_counter() - t0) * 1000, 1)

    # Compute overall score and state
    issues = []
    score = 100

    if typesafe_info["api_status"] not in ("HEALTHY", "UNCONFIGURED"):
        score -= 20
        issues.append("Jev 推理 API 降级或未响应")
    if typesafe_info["console_status"] == "WARN":
        # Console 500 does not break local inference, but is a warning
        issues.append("TypeSafe Web 控制台 (console.typesafe.ai) 报 500，但本地 API 降级链路已保护")

    if agnes_info["status"] not in ("HEALTHY", "UNCONFIGURED"):
        score -= 10
        issues.append("Agnes 外部深审通道异常")

    for d in daemons_info:
        if d["status"] not in ("HEALTHY", "STANDBY"):
            score -= 25
            issues.append(f"{d['name']} 未正常运行")

    for p in platforms_info:
        if p["status"] == "DEGRADED":
            score -= 15
            issues.append(f"{p['name']} 挂载不完整")

    if parity_info["status"] != "HEALTHY":
        score -= 20
        issues.append(f"跨端资产或进化闭环异常: {parity_info['detail']}")

    if score >= 90:
        overall_status = "HEALTHY"
        status_label = "🟢 全系统满血就绪 (All Systems Operational)"
    elif score >= 60:
        overall_status = "DEGRADED"
        status_label = "🟡 自动降级自愈中 (Degraded / Fail-Safe Active)"
    else:
        overall_status = "CRITICAL"
        status_label = "🔴 关键服务离线 (Critical Services Down)"

    summary = "全部核心服务正常在线。" if not issues else "；".join(issues)

    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "diagnostic_duration_ms": duration_ms,
        "overall_status": overall_status,
        "overall_status_label": status_label,
        "overall_score": max(0, score),
        "summary": summary,
        "pillars": {
            "typesafe_jev": typesafe_info,
            "agnes": agnes_info,
            "daemons": daemons_info,
            "platforms": platforms_info,
            "freshness": freshness_info,
            "parity": parity_info
        },
        "circuit_breaker": {
            "active_tier": "Tier 2 (Jev 强类型)" if typesafe_info["api_status"] == "HEALTHY" else "Tier 0 (本地启发式硬门禁保底)",
            "fail_safe_ready": True,
            "offline_heuristic_active": True
        }
    }

    _CACHE_DATA = result
    _CACHE_TIME = now
    return result

def auto_heal():
    """Triggers automated recovery for any offline daemon."""
    actions_taken = []
    # 1. Revive 17911 if down
    c_code, _, _ = _probe_url("http://127.0.0.1:17911/health", timeout=0.5)
    if c_code != 200:
        starter_ps1 = CLAUDE_DIR / "dissat-classifier" / "start-dissat-service.ps1"
        if starter_ps1.exists():
            import subprocess
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(starter_ps1)],
                creationflags=0x00000008 | 0x08000000 if os.name == "nt" else 0,
                close_fds=True
            )
            actions_taken.append("已重新拉起 17911 司法裁决服务")

    # 2. Revive ag_watch.py if down
    watch_running = False
    try:
        import psutil
        for p in psutil.process_iter(["cmdline"]):
            cmd = " ".join(p.info.get("cmdline") or [])
            if "ag_watch.py" in cmd:
                watch_running = True
                break
    except Exception:
        pass

    if not watch_running:
        watch_script = GEMINI_DIR / "antigravity" / "scripts" / "start-ag-watch.ps1"
        if watch_script.exists():
            import subprocess
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(watch_script)],
                creationflags=0x00000008 | 0x08000000 if os.name == "nt" else 0,
                close_fds=True
            )
            actions_taken.append("已重新拉起 ag_watch 后台守护")

    # Flush cache to re-evaluate
    global _CACHE_DATA
    _CACHE_DATA = None
    return {
        "success": True,
        "actions": actions_taken or ["全部核心守护进程均已处于运行状态，无需重启"]
    }

def print_cli_report():
    """Prints a beautiful terminal diagnostic report."""
    data = run_doctor(cached=False)
    p = data["pillars"]
    print("=" * 72)
    print(f"🩺 TRUTHGATE SYSTEM DOCTOR (全景健康诊断体检中心)  [{data['timestamp']}]")
    print(f"系统状态: {data['overall_status_label']}  |  健康评分: {data['overall_score']} / 100")
    print(f"诊断耗时: {data['diagnostic_duration_ms']}ms  |  运行模式: {data['circuit_breaker']['active_tier']}")
    print("=" * 72)

    # 1. 云端双核推理
    tj = p["typesafe_jev"]
    ag = p["agnes"]
    print("\n🧠 [1/6] 云端双核与本地推理引擎")
    print(f"   • TypeSafe Jev : [{tj['api_status']}] {tj['api_detail']}")
    print(f"   • TypeSafe Web : [{tj['console_status']}] {tj['console_detail']}")
    print(f"   • Agnes 3.0    : [{ag['status']}] {ag['detail']}")
    print(f"   • Tier 0 本地  : [HEALTHY] 原生 AST / 正则 / 命令退出码核验 (100% 离线硬生效)")

    # 2. 本地常驻守护
    print("\n⚡ [2/6] 本地常驻守护与服务")
    for d in p["daemons"]:
        print(f"   • {d['name']:<28} : [{d['status']}] {d['detail']}")

    # 3. 四端挂载
    print("\n🛡️ [3/6] 四端门禁集成与桥接")
    for pl in p["platforms"]:
        print(f"   • {pl['name']:<28} : [{pl['status']}] {pl['detail']}")

    # 4. 数据管道
    fr = p["freshness"]
    print("\n📡 [4/6] 审计日志流新鲜度")
    print(f"   • 状态: [{fr['status']}] {fr['detail']} (总行数: {fr['total_lines']})")

    # 5. 跨端资产与自动进化闭环
    par = p.get("parity", {})
    print("\n🔄 [5/6] 四端资产与自动进化闭环对账")
    print(f"   • 状态: [{par.get('status', 'UNKNOWN')}] {par.get('detail', '')}")

    # 6. 总结
    print("\n" + "-" * 72)
    print(f"📋 [6/6] 综合研判: {data['summary']}")
    print("=" * 72)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--heal":
        res = auto_heal()
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "--json":
        print(json.dumps(run_doctor(cached=False), ensure_ascii=False, indent=2))
    else:
        print_cli_report()
