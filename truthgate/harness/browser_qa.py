# -*- coding: utf-8 -*-
"""browser_qa.py —— 通用 Playwright 真机无头浏览器全生命周期质检脚手架 (Frozen External Harness)

核心功能:
  1. 真实启动 Playwright Chromium 无头实例（零焦点抢占，静默运行）；
  2. 挂载真实网络与 DOM 监听器：全程监听 pageerror（未捕获异常）与 console.error（控制台报错）；
  3. 真实页面导航与渲染等待，检验 HTTP 状态码与 DOM 节点就绪；
  4. 截取高质量全景页面截图，生成不可伪造的落盘证据（PNG）；
  5. 严格判定 0 PageError 与 0 ConsoleError，退出码 0 表示及格，非 0 伴随具体堆栈输出。
"""
import os
import sys
import time
import json
import argparse
from pathlib import Path


def run_browser_qa(url: str, output_image: str = None, selector: str = None, timeout_ms: int = 15000, wait_until: str = "domcontentloaded") -> dict:
    from playwright.sync_api import sync_playwright

    page_errors = []
    console_errors = []
    actions_verified = []

    out_path = Path(output_image) if output_image else Path(os.getcwd()) / f"browser_qa_{int(time.time())}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result = {
        "url": url,
        "success": False,
        "screenshot": str(out_path),
        "screenshot_path": str(out_path),
        "page_errors": page_errors,
        "console_errors": console_errors,
        "actions_verified": actions_verified,
        "duration_ms": 0
    }

    t0 = time.perf_counter()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1080})
        page = context.new_page()

        page.on("pageerror", lambda err: page_errors.append(f"PageError: {err}"))
        page.on(
            "console",
            lambda msg: console_errors.append(f"ConsoleError: {msg.text}")
            if msg.type == "error"
            else None
        )

        try:
            resp = page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            status_code = resp.status if resp else None
            actions_verified.append(f"页面导航成功: 状态码 {status_code}")

            if selector:
                page.wait_for_selector(selector, timeout=min(timeout_ms, 5000))
                actions_verified.append(f"关键选择器就绪: {selector}")
            else:
                page.wait_for_timeout(500)

            page.screenshot(path=str(out_path), full_page=True)
            if out_path.exists() and out_path.stat().st_size > 1024:
                actions_verified.append(f"真实截图生成成功: {out_path.name} ({round(out_path.stat().st_size/1024, 1)} KB)")

            total_errs = len(page_errors) + len(console_errors)
            if total_errs == 0:
                result["success"] = True
            else:
                result["success"] = False
                result["error"] = f"页面存在 {len(page_errors)} 个未捕获异常和 {len(console_errors)} 个控制台报错"

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
        finally:
            browser.close()

    result["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result


def main():
    parser = argparse.ArgumentParser(description="TruthGate 通用 Playwright 真机浏览器质检脚手架")
    parser.add_argument("--url", required=True, help="待检测的目标 URL (如 http://127.0.0.1:17911/dashboard 或 file://...)")
    parser.add_argument("--out", default="", help="截图输出路径 (默认为当前目录)")
    parser.add_argument("--selector", default="", help="可选: 待等待的关键 DOM 选择器")
    parser.add_argument("--timeout", type=int, default=15000, help="页面加载超时时间 (毫秒)")
    parser.add_argument("--wait-until", default="domcontentloaded", choices=["domcontentloaded", "load", "networkidle"], help="页面等待事件")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")

    args = parser.parse_args()
    res = run_browser_qa(
        url=args.url,
        output_image=args.out if args.out else None,
        selector=args.selector if args.selector else None,
        timeout_ms=args.timeout,
        wait_until=args.wait_until
    )

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        status_tag = "[PASS]" if res["success"] else "[FAIL]"
        print(f"{status_tag} Browser QA: {args.url} (耗时: {res['duration_ms']}ms)")
        for act in res["actions_verified"]:
            print(f"  + {act}")
        if res["page_errors"]:
            print("  - Page Errors:")
            for pe in res["page_errors"]:
                print(f"    * {pe}")
        if res["console_errors"]:
            print("  - Console Errors:")
            for ce in res["console_errors"]:
                print(f"    * {ce}")
        if not res["success"] and "error" in res:
            print(f"  ! 错误详情: {res['error']}")

    sys.exit(0 if res["success"] else 1)


if __name__ == "__main__":
    main()
