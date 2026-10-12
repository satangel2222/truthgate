import json
import subprocess
import sys
import unittest
from pathlib import Path

BRIDGE_PATH = Path.home() / ".truthgate" / "ag_superego_bridge.py"

class TestAgPreToolInterception(unittest.TestCase):
    def run_bridge_pre_tool(self, payload):
        proc = subprocess.Popen(
            [sys.executable, str(BRIDGE_PATH), "pre_tool"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        out, err = proc.communicate(input=json.dumps(payload), timeout=5)
        self.assertEqual(proc.returncode, 0, f"Bridge itself should exit 0 with JSON decision. stderr={err}")
        return json.loads(out.strip())

    def test_destructive_rm_rf_blocked(self):
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {
                    "CommandLine": "rm -rf /"
                }
            }
        }
        res = self.run_bridge_pre_tool(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("BLOCKED", res.get("reason", ""))
        self.assertIn("rm -r", res.get("reason", ""))

    def test_single_source_command_blocked(self):
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {
                    "CommandLine": "echo 123 > C:/Users/<username>/.superego/test.py"
                }
            }
        }
        res = self.run_bridge_pre_tool(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("单源闸", res.get("reason", ""))

    def test_single_source_write_file_blocked(self):
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": "C:/Users/<username>\\.superego\\test.py",
                    "CodeContent": "abc"
                }
            }
        }
        res = self.run_bridge_pre_tool(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("单源闸", res.get("reason", ""))

    def test_safe_command_allowed(self):
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {
                    "CommandLine": "Get-ChildItem"
                }
            }
        }
        res = self.run_bridge_pre_tool(payload)
        self.assertEqual(res.get("decision"), "allow")

    def test_safe_write_allowed(self):
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": "C:/Users/<username>\\.gemini\\antigravity\\scratch\\safe_test.txt",
                    "CodeContent": "hello world"
                }
            }
        }
        res = self.run_bridge_pre_tool(payload)
        self.assertEqual(res.get("decision"), "allow")

if __name__ == '__main__':
    unittest.main()
