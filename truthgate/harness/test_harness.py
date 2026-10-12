# -*- coding: utf-8 -*-
"""test_harness.py —— TruthGate 2.0 外部只读测试脚手架自检套件"""
import sys
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from endpoint_qa import run_endpoint_qa
from cli_qa import run_cli_qa
from browser_qa import run_browser_qa


def test_harness_suite():
    print("=== 开始 TruthGate 外部只读测试脚手架自检 ===")

    # 1. 测试 CLI QA
    print("\n[1/3] 测试 CLI QA 模块...")
    cli_res = run_cli_qa("python -c \"print('truthgate harness active')\"", expected_code=0)
    assert cli_res["success"], f"CLI QA 失败: {cli_res.get('error')}"
    print(f"  [PASS] CLI QA 成功通过 ({cli_res['duration_ms']}ms)")

    # 2. 测试 Endpoint QA 对本地 17911 端口
    print("\n[2/3] 测试 Endpoint QA 模块 (探测 127.0.0.1:17911/dashboard)...")
    ep_res = run_endpoint_qa("http://127.0.0.1:17911/dashboard", expected_status=200, keyword="Superego")
    if not ep_res["success"]:
        # 兼容 TruthGate 关键字
        ep_res = run_endpoint_qa("http://127.0.0.1:17911/dashboard", expected_status=200, keyword="TruthGate")
    assert ep_res["success"], f"Endpoint QA 失败: {ep_res.get('error')}"
    print(f"  [PASS] Endpoint QA 成功通过 (状态码: {ep_res['actual_status']}, 耗时: {ep_res['duration_ms']}ms)")

    # 3. 测试 Browser QA 对本地 17911 界面并生成真机截图
    print("\n[3/3] 测试 Browser QA 模块 (Playwright 无头 Chromium 渲染)...")
    out_png = HERE / "test_browser_harness_pass.png"
    b_res = run_browser_qa("http://127.0.0.1:17911/dashboard", output_image=str(out_png), wait_until="domcontentloaded")
    assert b_res["success"], f"Browser QA 失败: {b_res.get('error')}"
    assert out_png.exists() and out_png.stat().st_size > 1024, "测试截图未正确生成"
    print(f"  [PASS] Browser QA 成功通过! 截图大小: {round(out_png.stat().st_size/1024, 1)} KB (耗时: {b_res['duration_ms']}ms)")

    print("\n=== 所有外部测试脚手架自检项全部通过! ===")


if __name__ == "__main__":
    test_harness_suite()
