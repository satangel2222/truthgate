from pathlib import Path
import sys
import os
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "truthgate"))
from ag_superego_bridge import check_no_nagging_violation

class TestDeclarativeOffloadingGuard(unittest.TestCase):
    def test_link_manual_dump(self):
        text = "已生成链接，通过该链接打开一次即可自动写入最新 Cookie，页面将直接进入主界面。"
        res = check_no_nagging_violation(text)
        self.assertIsNotNone(res, "必须拦截：把链接甩给用户手动打开")

    def test_config_revert_dump(self):
        text = "遗留事项（供你决定）：若你希望回到干净的包名写法，下次重启时把 patch 改回即可。"
        res = check_no_nagging_violation(text)
        self.assertIsNotNone(res, "必须拦截：甩锅让用户下次重启改回 patch")

    def test_manual_operate_dump(self):
        text = "你可以手动在浏览器里打开该链接并刷新。"
        res = check_no_nagging_violation(text)
        self.assertIsNotNone(res, "必须拦截：让用户手动操作")

    def test_legitimate_captcha_exempt(self):
        text = "平台出现了人机验证码，需要你本人过滑块验证。"
        res = check_no_nagging_violation(text)
        self.assertIsNone(res, "真不可逆人机滑块边界应放行")

    def test_normal_done_delivery(self):
        text = "全链路已跑通，冷重启测试通过，所有服务均已正常启动。"
        res = check_no_nagging_violation(text)
        self.assertIsNone(res, "正常完成交付应放行")

if __name__ == "__main__":
    unittest.main()
