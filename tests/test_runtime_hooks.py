import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
VERIFIERS = ROOT / "verifiers"
sys.path.insert(0, str(VERIFIERS))

SPEC = importlib.util.spec_from_file_location("ai4math_hook_gate", VERIFIERS / "hook_gate.py")
hook_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook_gate)


class ClaudeHookTests(unittest.TestCase):
    def test_mutating_tools_require_full_tree_check(self):
        for name in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "ApplyPatch"):
            with self.subTest(name=name):
                self.assertTrue(hook_gate.event_requires_check({"tool_name": name}))
        self.assertFalse(hook_gate.event_requires_check({"tool_name": "Read"}))

    def test_bash_event_runs_tree_checker(self):
        payload = io.TextIOWrapper(
            io.BytesIO(json.dumps({"tool_name": "Bash", "tool_input": {}}).encode()),
            encoding="utf-8",
        )
        with (
            mock.patch.object(sys, "stdin", payload),
            mock.patch.object(hook_gate, "_maybe_reexec"),
            mock.patch.object(hook_gate, "check_tree", return_value=(True, "")) as check,
        ):
            self.assertEqual(hook_gate.main([]), 0)
        check.assert_called_once_with(str(ROOT))

    def test_read_event_skips_tree_checker(self):
        payload = io.TextIOWrapper(
            io.BytesIO(json.dumps({"tool_name": "Read", "tool_input": {}}).encode()),
            encoding="utf-8",
        )
        with (
            mock.patch.object(sys, "stdin", payload),
            mock.patch.object(hook_gate, "_maybe_reexec"),
            mock.patch.object(hook_gate, "check_tree") as check,
        ):
            self.assertEqual(hook_gate.main([]), 0)
        check.assert_not_called()

    def test_venv_interpreter_supports_posix_and_windows_layouts(self):
        root = str(ROOT)
        posix = str(ROOT / ".venv" / "bin" / "python")
        windows = str(ROOT / ".venv" / "Scripts" / "python.exe")
        with mock.patch.object(
            hook_gate.os.path, "isfile", side_effect=lambda path: path == posix
        ):
            self.assertEqual(hook_gate.venv_interpreter(root), posix)
        with mock.patch.object(
            hook_gate.os.path, "isfile", side_effect=lambda path: path == windows
        ):
            self.assertEqual(hook_gate.venv_interpreter(root), windows)


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the OpenCode plugin test")
class OpenCodePluginTests(unittest.TestCase):
    def test_cross_platform_claude_launcher_is_valid_module(self):
        result = subprocess.run(
            [shutil.which("node"), "--check", str(VERIFIERS / "hook_gate_launcher.mjs")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        source = (VERIFIERS / "hook_gate_launcher.mjs").read_text(encoding="utf-8")
        self.assertIn('process.platform === "win32" ? "python" : "python3"', source)

    def test_current_after_event_and_patch_paths_trigger_gate(self):
        plugin_url = (ROOT / ".opencode" / "plugins" / "ai4math-gate.js").as_uri()
        script = f"""
import {{ Ai4mathGate, shouldGate, toolArgs }} from {json.dumps(plugin_url)};
const calls = [];
const shell = (parts, ...values) => {{
  calls.push(values.map((value) => String(value)));
  const chain = {{ cwd: () => chain, quiet: async () => undefined }};
  return chain;
}};
const hooks = await Ai4mathGate({{ $: shell, directory: {json.dumps(str(ROOT))} }});
await hooks["tool.execute.after"](
  {{ tool: "write", args: {{ filePath: "problems/p/conjectures/C.md" }} }},
  {{ title: "write", output: "ok", metadata: {{}} }},
);
await hooks["tool.execute.after"](
  {{ tool: "apply_patch", args: {{ patchText: "*** Begin Patch" }} }},
  {{ output: "ok" }},
);
await hooks["tool.execute.after"](
  {{ tool: "bash", args: {{ command: "python script.py" }} }},
  {{ output: "ok" }},
);
await hooks["tool.execute.after"]({{ tool: "read", args: {{}} }}, {{ output: "ok" }});
console.log(JSON.stringify({{
  calls: calls.length,
  inputPath: toolArgs({{ args: {{ filePath: "sentinel" }} }}).filePath,
  patch: shouldGate({{ tool: "apply_patch" }}),
}}));
"""
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data, {"calls": 3, "inputPath": "sentinel", "patch": True})


if __name__ == "__main__":
    unittest.main()
