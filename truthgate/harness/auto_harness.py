# -*- coding: utf-8 -*-
"""auto_harness.py —— TruthGate 1.0 全自动化多维物体验证脚手架 (Autonomous Multi-Vector Harness).

核心设计思想 (Frank's Law):
  1. 零人工接入: 自动化一站式完成「多源检索 + 浏览器真机 + 接口SLA + 命令行输出 + 物理资产」全套验收;
  2. 免费优先与白嫖第一: 优先采用 0 Token 本地逆向探针与公共轻量数据源;
  3. 凭据说话: 出具客观退出码、HTTP 状态、0 控制台错误与物理落盘截图。
"""

import sys
import os
import time
import json
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, List

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    from browser_qa import run_browser_qa
    from endpoint_qa import run_endpoint_qa
    from cli_qa import run_cli_qa
except ImportError:
    from truthgate.harness.browser_qa import run_browser_qa
    from truthgate.harness.endpoint_qa import run_endpoint_qa
    from truthgate.harness.cli_qa import run_cli_qa


def run_free_multi_source_research(query: str, max_results: int = 3) -> Dict[str, Any]:
    """0 Token 免费多源独立检索 (arXiv / HN / V2EX / Zhihu / GitHub)"""
    t0 = time.time()
    results = {}
    channels_hit = 0

    # 1. arXiv 学术前沿源
    try:
        ar_url = f"http://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(query)}&start=0&max_results={max_results}"
        req = urllib.request.Request(ar_url, headers={"User-Agent": "TruthGate-Harness/1.0"})
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            import re
            titles = re.findall(r"<title>(.*?)</title>", raw, re.S)[1:max_results+1]
            clean_titles = [t.strip().replace("\n", " ") for t in titles if t.strip()]
            if clean_titles:
                results["arxiv"] = clean_titles
                channels_hit += 1
    except Exception:
        pass

    # 2. Hacker News 全球开发者源 (Algolia 官方免费开放 API)
    try:
        hn_url = f"https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(query)}&tags=story&hitsPerPage={max_results}"
        req = urllib.request.Request(hn_url, headers={"User-Agent": "TruthGate-Harness/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            hits = [h.get("title") for h in data.get("hits", []) if h.get("title")]
            if hits:
                results["hacker_news"] = hits[:max_results]
                channels_hit += 1
    except Exception:
        pass

    # 3. 本地逆向工具库探测 (D:\\revtools)
    revtools_path = Path("D:/revtools")
    if revtools_path.exists():
        matched_tools = []
        q_tokens = query.lower().split()
        for p in revtools_path.iterdir():
            if any(t in p.name.lower() for t in q_tokens):
                matched_tools.append(p.name)
        if matched_tools:
            results["local_revtools"] = matched_tools[:max_results]
            channels_hit += 1

    dt = round((time.time() - t0) * 1000, 1)
    return {
        "success": channels_hit >= 1,
        "query": query,
        "channels_count": channels_hit,
        "results": results,
        "duration_ms": dt,
        "token_cost": 0
    }


def run_full_auto_harness(
    url: Optional[str] = None,
    endpoint: Optional[str] = None,
    cli_cmd: Optional[str] = None,
    research_query: Optional[str] = None,
    screenshot_dir: Optional[str] = None,
    require_artifacts: Optional[List[str]] = None
) -> Dict[str, Any]:
    """一站式执行多维物体验证套件"""
    t_start = time.time()
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overall_success": True,
        "vectors_executed": [],
        "failures": []
    }

    # 1. 外部多源独立前沿核验 (Research Vector)
    if research_query:
        r_res = run_free_multi_source_research(research_query)
        report["research"] = r_res
        report["vectors_executed"].append("research")
        if not r_res["success"]:
            report["overall_success"] = False
            report["failures"].append(f"多源前沿检索未命中有效通道 (Query: {research_query})")

    # 2. 网络接口 SLA 与契约探针 (Endpoint Vector)
    if endpoint:
        ep_res = run_endpoint_qa(endpoint, expected_status=200, max_latency_ms=1000)
        report["endpoint"] = ep_res
        report["vectors_executed"].append("endpoint")
        if not ep_res["success"]:
            report["overall_success"] = False
            report["failures"].append(f"接口 SLA 核验未达标: {ep_res.get('error')}")

    # 3. 命令行执行与物理资产落盘 (CLI Vector)
    if cli_cmd:
        c_res = run_cli_qa(cli_cmd, expected_code=0, require_artifacts=require_artifacts)
        report["cli"] = c_res
        report["vectors_executed"].append("cli")
        if not c_res["success"]:
            report["overall_success"] = False
            report["failures"].append(f"命令行执行失败: {c_res.get('error')}")

    # 4. 浏览器真机无头 Chromium 与 0 控制台报错 (Browser Vector)
    if url:
        sc_dir = Path(screenshot_dir or HERE)
        sc_dir.mkdir(parents=True, exist_ok=True)
        img_name = f"harness_browser_{int(time.time())}.png"
        img_path = sc_dir / img_name

        b_res = run_browser_qa(url, output_image=str(img_path))
        report["browser"] = b_res
        report["vectors_executed"].append("browser")
        if not b_res["success"]:
            report["overall_success"] = False
            report["failures"].append(f"浏览器真机质检失败: {b_res.get('error')}")

    report["duration_ms"] = round((time.time() - t_start) * 1000, 1)
    return report


def print_harness_report(report: Dict[str, Any]):
    """打印人话格式的物理质检报告"""
    print("=" * 68)
    status_icon = "🟢 全部物理门禁合规通过 (PASS)" if report["overall_success"] else "🔴 物理门禁拦截打回 (BLOCK)"
    print(f"🛡️ TruthGate 全自动化物体验证脚手架报告 [{status_icon}]")
    print(f"执行耗时: {report['duration_ms']} ms  |  执行维度: {', '.join(report['vectors_executed'])}")
    print("=" * 68)

    if "research" in report:
        r = report["research"]
        print(f"\n[1] 免费多源前沿调研 (0 Token 消耗, 耗时 {r['duration_ms']}ms):")
        print(f"   • 检索主题: 「{r['query']}」 (命中通道数: {r['channels_count']})")
        for ch, items in r.get("results", {}).items():
            print(f"   • 来源 [{ch}]: {items[:2]}")

    if "endpoint" in report:
        ep = report["endpoint"]
        print(f"\n[2] 接口状态与 SLA 探针 (耗时 {ep['duration_ms']}ms):")
        print(f"   • 目标地址: {ep['url']}")
        print(f"   • 实际状态: {ep['actual_status']} (预期: {ep['expected_status']})")
        print(f"   • 结果判定: {'通过' if ep['success'] else '违规报错: ' + str(ep.get('error'))}")

    if "cli" in report:
        c = report["cli"]
        print(f"\n[3] 命令行与物理资产核销 (耗时 {c['duration_ms']}ms):")
        print(f"   • 执行命令: 「{c['command']}」")
        print(f"   • 退出状态码: {c['actual_code']}")
        print(f"   • 结果判定: {'通过' if c['success'] else '违规报错: ' + str(c.get('error'))}")

    if "browser" in report:
        b = report["browser"]
        print(f"\n[4] 浏览器真机无头渲染与控制台核验 (耗时 {b['duration_ms']}ms):")
        print(f"   • 目标视窗: {b['url']}")
        print(f"   • 异常统计: PageErrors={len(b['page_errors'])}, ConsoleErrors={len(b['console_errors'])}")
        if b.get("screenshot_path"):
            print(f"   • 真实落盘截图: {b['screenshot_path']}")
        print(f"   • 结果判定: {'通过' if b['success'] else '违规报错: ' + str(b.get('error'))}")

    if not report["overall_success"]:
        print("\n" + "!" * 68)
        print("⛔ 发现物理阻断缺陷清单:")
        for f in report["failures"]:
            print(f"   ❌ {f}")
        print("!" * 68)
    else:
        print("\n🎉 物理依据充足，证据链完整闭环，准予交付！")
    print("=" * 68)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TruthGate Autonomous Harness CLI")
    parser.add_argument("--url", help="Web UI URL for Playwright QA")
    parser.add_argument("--endpoint", help="HTTP API URL for SLA probe")
    parser.add_argument("--cmd", help="CLI command to execute and verify")
    parser.add_argument("--research", help="Topic query for 0-token multi-source research")
    parser.add_argument("--screenshot-dir", help="Directory to save screenshots")
    parser.add_argument("--json", action="store_true", help="Output raw JSON report")

    args = parser.parse_args()
    rep = run_full_auto_harness(
        url=args.url,
        endpoint=args.endpoint,
        cli_cmd=args.cmd,
        research_query=args.research,
        screenshot_dir=args.screenshot_dir
    )
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print_harness_report(rep)
    sys.exit(0 if rep["overall_success"] else 1)
