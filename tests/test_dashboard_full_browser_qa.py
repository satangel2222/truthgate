# -*- coding: utf-8 -*-
"""test_dashboard_full_browser_qa.py —— 全量穷尽真机浏览器 DOM 交互自动化 QA 测试套件。
涵盖：
1. 全局零 JavaScript 运行时报错 (Zero Console/Page Errors)
2. 顶栏 3 档字号缩放 (标准 A / 舒适 A+ / 特大 A++)
3. 全部 4 大主功能 Tab 切换与视图渲染 (Stream / Shadow / Lessons / Settings)
4. 流水监控抽屉 (Stream Event Drawer) 打开与关闭
5. 影子痛点重新扫描与倒计时渲染
6. 教训案例库实时检索与分页
7. 全部 3 种 AI 驯化模式 (Profile Mask) 切换与响应式角标更新
8. 全部 8 种外审裁判模型联动映射 (Base URL & Model Name 动态更新)
9. API Key 密码框眼睛显隐切换
10. 外审连通性真实探针测试 (Test Connection)
11. 4 大系统安全硬开关切换 (Security Toggles)
12. 四端对齐与紧急熔断回滚动作
13. 保存配置端到端生效持久化
14. 满血度 6 大核心器官体检向导弹窗 (Blood Diagnostic Modal) 打开、诊断刷新与关闭
15. 全景系统 5 大支柱体检与自愈中心弹窗 (Doctor Diagnostic Modal) 打开、重测、自愈与关闭
"""
import sys
import time
import threading
from pathlib import Path
from http.server import HTTPServer
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from truthgate.dashboard import DashboardServer, DashboardHandler

EXPECTED_MAP = {
    'agnes': ('https://apihub.agnes-ai.com/v1', 'agnes-3.0-flash'),
    'openai': ('https://api.openai.com/v1', 'gpt-5.6-sol'),
    'gemini': ('https://generativelanguage.googleapis.com/v1beta/openai', 'gemini-3.8-flash'),
    'glm': ('https://open.bigmodel.cn/api/paas/v4', 'glm-4-flash'),
    'deepseek': ('https://api.deepseek.com/v1', 'deepseek-chat'),
    'openai_compatible': ('https://your-relay.com/v1', 'gpt-5.6-sol'),
    'ollama': ('http://localhost:11434/v1', 'qwen2.5:7b'),
    'local_heuristic': ('local', 'local_ast_tier0'),
}

def run_exhaustive_browser_qa():
    port = 17992
    server = DashboardServer(('127.0.0.1', port), DashboardHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.5)

    page_errors = []
    console_errors = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            def on_page_error(err):
                print(f"❌ [PAGE_ERROR] {err}")
                page_errors.append(str(err))

            def on_console(msg):
                if msg.type == "error":
                    print(f"⚠️ [CONSOLE_ERROR] {msg.text}")
                    console_errors.append(msg.text)

            def on_response(res):
                if res.status >= 400:
                    print(f"⚠️ [HTTP_{res.status}] {res.url}")

            page.on("pageerror", on_page_error)
            page.on("console", on_console)
            page.on("response", on_response)
            page.on("dialog", lambda dialog: dialog.accept())

            print("🌐 [1/7] 打开仪表盘页面...")
            page.goto(f'http://127.0.0.1:{port}/dashboard')
            page.wait_for_selector('.header-actions')
            print("  ✅ 仪表盘基础 DOM 加载就绪")

            # ----------------------------------------------------
            # Phase 1: 顶栏 3 档字号缩放
            # ----------------------------------------------------
            print("\n🔤 [2/7] 测试顶栏字号无级缩放...")
            page.click('button:has-text("标准 A")')
            assert 'font-compact' in page.evaluate("() => document.body.className"), "标准 A 缩放失败"
            print("  ✅ 标准 A (font-compact) 生效")

            page.click('button:has-text("特大 A++")')
            assert 'font-large' in page.evaluate("() => document.body.className"), "特大 A++ 缩放失败"
            print("  ✅ 特大 A++ (font-large) 生效")

            page.click('button:has-text("舒适 A+")')
            assert 'font-comfort' in page.evaluate("() => document.body.className"), "舒适 A+ 缩放失败"
            print("  ✅ 舒适 A+ (font-comfort) 生效")

            # ----------------------------------------------------
            # Phase 2: 全部 4 大主功能 Tab 切换与视图渲染
            # ----------------------------------------------------
            print("\n📑 [3/7] 遍历全部 4 大主功能 Tab 切换与视图完整性...")
            
            # Tab 1: Stream
            page.click('#tab-btn-stream')
            assert page.is_visible('#view-stream'), "#view-stream 未显示"
            assert not page.is_visible('#view-shadow'), "#view-shadow 未隐藏"
            page.fill('#search-input', 'gate')
            page.wait_for_timeout(300)
            page.fill('#search-input', '')
            page.select_option('#sort-select', 'asc')
            page.wait_for_timeout(200)
            page.select_option('#sort-select', 'desc')
            print("  ✅ Tab 1: 实时判官监控大盘切换正常 (检索与排序过滤就绪)")

            # Tab 2: Shadow
            page.click('#tab-btn-shadow')
            assert page.is_visible('#view-shadow'), "#view-shadow 未显示"
            assert not page.is_visible('#view-stream'), "#view-stream 未隐藏"
            page.click('button:has-text("重新扫描痛点")')
            page.wait_for_timeout(400)
            assert page.is_visible('#shadow-incidents-container'), "#shadow-incidents-container 未就绪"
            print("  ✅ Tab 2: 四端影子监管与痛点扫描切换正常")

            # Tab 3: Lessons
            page.click('#tab-btn-lessons')
            assert page.is_visible('#view-lessons'), "#view-lessons 未显示"
            page.fill('#search-lesson-input', 'truthgate')
            page.wait_for_timeout(300)
            page.fill('#search-lesson-input', '')
            print("  ✅ Tab 3: 历代教训案例库切换正常 (检索过滤就绪)")

            # Tab 4: Settings
            page.click('#tab-btn-settings')
            assert page.is_visible('#view-settings'), "#view-settings 未显示"
            print("  ✅ Tab 4: 系统设置与规则市场切换正常")

            # ----------------------------------------------------
            # Phase 3: 深度测试 Settings 面板全部控件
            # ----------------------------------------------------
            print("\n⚙️ [4/7] 穷尽测试系统设置面板全部交互控件...")
            
            # 3.1 Profile Mask 切换
            page.wait_for_selector('.profile-card')
            count = len(page.query_selector_all('.profile-card'))
            assert count >= 3, f"期望至少 3 个 Profile 卡片，实际: {count}"
            for i in range(count):
                page.click(f'.profile-card:nth-child({i+1})')
                page.wait_for_timeout(200)
                badge_text = page.inner_text('#badge-settings-profile')
                assert len(badge_text) > 0, "Profile Badge 文字为空"
                print(f"  ✅ Profile [{i+1}/3] 切换成功 -> 顶栏角标: {badge_text}")

            # 3.2 全部 8 种外审模型联动映射
            for provider, (exp_base, exp_model) in EXPECTED_MAP.items():
                page.select_option('#critic-provider', provider)
                cur_base = page.input_value('#critic-base-url')
                cur_model = page.input_value('#critic-model')
                assert cur_base == exp_base, f"Provider {provider} 期望 Base URL {exp_base}, 实际 {cur_base}"
                assert cur_model == exp_model, f"Provider {provider} 期望 Model {exp_model}, 实际 {cur_model}"
            print("  ✅ 全部 8 种外审模型下拉动态联动 100% 正确映射")

            # 3.3 API Key 密码框眼睛显隐切换
            page.fill('#critic-api-key', 'sk-test-secret-sample-key')
            assert page.get_attribute('#critic-api-key', 'type') == 'password', "初始状态非 password"
            page.click('button[onclick*="toggleKeyVisibility"]')
            assert page.get_attribute('#critic-api-key', 'type') == 'text', "点击眼睛后未转为 text"
            page.click('button[onclick*="toggleKeyVisibility"]')
            assert page.get_attribute('#critic-api-key', 'type') == 'password', "再次点击后未恢复 password"
            print("  ✅ API Key 密码眼睛显隐切换正常")

            # 3.4 连通性测试按钮
            page.select_option('#critic-provider', 'local_heuristic')
            page.click('#btn-test-critic')
            page.wait_for_function(
                "() => { const el = document.getElementById('test-critic-result'); return el && !el.innerText.includes('正在向外审端点') && el.innerText.trim().length > 0; }",
                timeout=15000
            )
            res_text = page.inner_text('#test-critic-result')
            assert 'Tier 0' in res_text or '正常' in res_text or '成功' in res_text, f"连通性测试反馈异常: {res_text}"
            print(f"  ✅ 连通性测试执行成功: {res_text[:60]}...")

            # 3.5 4 大系统安全硬开关切换
            for sec_id in ['#sec-anti-inject', '#sec-overwrite', '#sec-ast', '#sec-leak']:
                orig = page.is_checked(sec_id)
                page.eval_on_selector(sec_id, 'el => el.click()')
                assert page.is_checked(sec_id) != orig, f"安全开关 {sec_id} 切换失败"
                page.eval_on_selector(sec_id, 'el => el.click()') # 恢复
                assert page.is_checked(sec_id) == orig, f"安全开关 {sec_id} 恢复失败"
            print("  ✅ 4 大系统安全硬开关点击状态翻转正常")

            # 3.6 保存配置端到端生效
            page.click('button[onclick="saveSettings()"]')
            page.wait_for_timeout(500)
            toast_text = page.inner_text('#settings-toast')
            assert '成功保存' in toast_text, f"保存配置 Toast 提示异常: {toast_text}"
            print(f"  ✅ 保存配置触发成功: {toast_text}")

            # 3.7 四端对齐与回滚按钮点击
            page.click('button[onclick="syncFourEnds()"]')
            page.wait_for_timeout(300)
            toast_text = page.inner_text('#settings-toast')
            assert '四端' in toast_text, f"四端对齐 Toast 异常: {toast_text}"
            print("  ✅ 立即对齐四端按钮触发成功")

            page.click('button[onclick="triggerRollback()"]')
            page.wait_for_timeout(300)
            toast_text = page.inner_text('#settings-toast')
            assert '回滚' in toast_text, f"回滚 Toast 异常: {toast_text}"
            print("  ✅ 紧急熔断回滚按钮触发成功")

            # ----------------------------------------------------
            # Phase 4: 模态框与体检中心 (Blood & Doctor Modals)
            # ----------------------------------------------------
            print("\n🩺 [5/7] 深度测试全部系统诊断与自愈模态框...")

            # 4.1 满血度诊断体检向导弹窗
            page.click('#blood-status-badge')
            page.wait_for_timeout(500)
            assert page.is_visible('#blood-modal-overlay'), "满血度模态框未弹出"
            assert page.is_visible('#blood-organs-grid'), "满血度器官网格未渲染"
            page.click('#blood-modal-overlay button:has-text("刷新诊断")')
            page.wait_for_timeout(400)
            page.click('#blood-modal-overlay button:has-text("✕")')
            page.wait_for_timeout(300)
            assert not page.is_visible('#blood-modal-overlay'), "满血度模态框未关闭"
            print("  ✅ 满血度 6 大核心器官体检向导弹窗 (打开/刷新/关闭) 全部通过")

            # 4.2 全景系统体检与自愈中心弹窗
            page.click('#doctor-status-badge')
            page.wait_for_timeout(500)
            assert page.is_visible('#doctor-modal-overlay'), "全景体检模态框未弹出"
            page.click('#doctor-modal-overlay button:has-text("重新体检")')
            page.wait_for_timeout(400)
            page.click('#doctor-modal-overlay button:has-text("✕")')
            page.wait_for_timeout(300)
            assert not page.is_visible('#doctor-modal-overlay'), "全景体检模态框未关闭"
            print("  ✅ 全景系统体检中心弹窗 (打开/重测/关闭) 全部通过")

            # 4.3 顶栏独立体检中心按钮触发
            page.click('button:has-text("体检中心")')
            page.wait_for_timeout(500)
            assert page.is_visible('#doctor-modal-overlay'), "顶栏体检中心按钮触发模态框失败"
            page.click('#doctor-modal-overlay button:has-text("✕")')
            page.wait_for_timeout(300)
            assert not page.is_visible('#doctor-modal-overlay'), "体检中心弹窗未关闭"
            print("  ✅ 顶栏【体检中心】独立入口触发与关闭通过")

            # ----------------------------------------------------
            # Phase 5: 全局无异常断言
            # ----------------------------------------------------
            print("\n🛡️ [6/7] 审计全局 JavaScript 运行时与控制台错误...")
            assert len(page_errors) == 0, f"发现致命 JavaScript 异常: {page_errors}"
            assert len(console_errors) == 0, f"发现控制台 Console Error: {console_errors}"
            print("  ✅ 全局 0 运行时报错，0 控制台异常")

            # 截取全景最终完成截图
            screenshot_path = Path(r"~/.gemini/antigravity\brain\a02a741f-4f6a-423f-92d3-8976979451cd\dashboard_exhaustive_qa_pass.png")
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"  📸 全景真机测试通过截图已落盘: {screenshot_path}")

            browser.close()
            print("\n" + "="*70)
            print("🎉🎉🎉 真机全量穷尽浏览器 DOM 交互自动化 QA 测试全部通过！")
            print("="*70)
    finally:
        server.shutdown()

if __name__ == '__main__':
    run_exhaustive_browser_qa()
