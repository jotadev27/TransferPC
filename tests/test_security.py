"""Guard the local-only runtime boundary against accidental additions."""
import ast
import unittest
from pathlib import Path


class RuntimeSecurityTests(unittest.TestCase):
    def test_runtime_has_no_network_or_process_execution(self):
        root = Path(__file__).resolve().parents[1] / "transferpc"
        blocked = {"socket", "requests", "urllib", "http", "ftplib", "paramiko",
                   "subprocess", "webbrowser", "QtNetwork", "QtWebEngineCore",
                   "QtWebEngineWidgets"}
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or "", *(alias.name for alias in node.names)]
                else:
                    names = []
                for name in names:
                    self.assertFalse(set(name.split(".")) & blocked, f"{path.name}: {name}")
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        self.assertNotIn(node.func.id, {"eval", "exec", "__import__"})
                    if isinstance(node.func, ast.Attribute):
                        self.assertNotIn(node.func.attr, {"system", "popen", "startDetached"})


if __name__ == "__main__":
    unittest.main()
