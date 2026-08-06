import io
import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from remote import remote_run  # noqa: E402


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class ApprovalTests(unittest.TestCase):
    def approval_state(self):
        holder = remote_run._empty_state()

        def load():
            return copy.deepcopy(holder)

        def save(value):
            holder.clear()
            holder.update(copy.deepcopy(value))

        return holder, load, save

    def test_token_is_bound_and_single_use(self):
        holder, load, save = self.approval_state()
        with (
            mock.patch.object(remote_run, "load_state", side_effect=load),
            mock.patch.object(remote_run, "save_state", side_effect=save),
        ):
            token = remote_run.create_approval("h", "echo ok", now=100)
            self.assertNotIn(token, holder["approvals"])
            self.assertIn(remote_run._token_key(token), holder["approvals"])
            remote_run.consume_approval(token, "h", "echo ok", now=101)
            with self.assertRaises(SystemExit):
                remote_run.consume_approval(token, "h", "echo ok", now=102)

    def test_mismatch_consumes_token(self):
        _, load, save = self.approval_state()
        with (
            mock.patch.object(remote_run, "load_state", side_effect=load),
            mock.patch.object(remote_run, "save_state", side_effect=save),
        ):
            token = remote_run.create_approval("h", "echo ok", now=100)
            with self.assertRaises(SystemExit):
                remote_run.consume_approval(token, "h", "echo other", now=101)
            with self.assertRaises(SystemExit):
                remote_run.consume_approval(token, "h", "echo ok", now=102)

    def test_authorize_rejects_noninteractive_callers(self):
        args = SimpleNamespace(host="h", cmd="echo ok")
        with (
            mock.patch.object(remote_run, "load_host", return_value={"ssh": "h"}),
            mock.patch.object(sys.stdin, "isatty", return_value=False),
            self.assertRaises(SystemExit),
        ):
            remote_run.cmd_authorize(args)

    def test_remote_mutations_reject_noninteractive_callers(self):
        for action in ("push", "setup"):
            with self.subTest(action=action), \
                    mock.patch.object(sys.stdin, "isatty", return_value=False), \
                    self.assertRaises(SystemExit):
                remote_run.require_interactive_confirmation(action, "h")

    def test_concurrent_token_consumption_is_serialized(self):
        root = ROOT / "tests" / ".tmp" / f"remote-{uuid.uuid4().hex}"
        root.mkdir(parents=True)
        state_path = root / "jobs.json"
        results = []
        barrier = threading.Barrier(2)

        def consume(token):
            barrier.wait()
            try:
                remote_run.consume_approval(token, "h", "echo ok", now=101)
                results.append("ok")
            except SystemExit:
                results.append("rejected")

        try:
            with mock.patch.object(remote_run, "JOBS_PATH", str(state_path)), \
                    mock.patch.object(
                        remote_run, "STATE_LOCK_PATH", str(state_path) + ".lock"
                    ):
                token = remote_run.create_approval("h", "echo ok", now=100)
                threads = [threading.Thread(target=consume, args=(token,)) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertCountEqual(["ok", "rejected"], results)


class StatusTests(unittest.TestCase):
    def test_classifier_distinguishes_all_terminal_states(self):
        cases = [
            (completed(255, "", "ssh failed"), ("SSH_ERROR", None)),
            (completed(0, "AI4MATH_STATE=RUNNING\n", ""), ("RUNNING", None)),
            (
                completed(0, "AI4MATH_STATE=EXIT\nAI4MATH_EXIT_CODE=0\n", ""),
                ("SUCCEEDED", 0),
            ),
            (
                completed(0, "AI4MATH_STATE=EXIT\nAI4MATH_EXIT_CODE=7\n", ""),
                ("FAILED", 7),
            ),
            (completed(0, "AI4MATH_STATE=UNKNOWN\n", ""), ("UNKNOWN", None)),
        ]
        for result, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(remote_run.classify_status(result), expected)

    def test_ssh_failure_is_not_reported_as_finished(self):
        jobs = {
            "j1": {
                "host": "h",
                "pid": 3,
                "started": "t",
                "log": "/w/logs/j1.log",
            }
        }
        args = SimpleNamespace(job=None)
        output = io.StringIO()
        with (
            mock.patch.object(remote_run, "load_jobs", return_value=jobs),
            mock.patch.object(remote_run, "load_host", return_value={"ssh": "h"}),
            mock.patch.object(
                remote_run, "ssh_run", return_value=completed(255, "", "connection failed")
            ),
            mock.patch.object(remote_run, "save_jobs") as save,
            mock.patch("sys.stdout", output),
        ):
            remote_run.cmd_status(args)
        self.assertIn("SSH_ERROR", output.getvalue())
        self.assertNotIn("FINISHED", output.getvalue())
        self.assertEqual(jobs["j1"]["state"], "SSH_ERROR")
        save.assert_called_once_with(jobs)


class RunTests(unittest.TestCase):
    def test_job_ids_include_random_suffix(self):
        with (
            mock.patch.object(remote_run.time, "strftime", return_value="20260806-120000"),
            mock.patch.object(remote_run.secrets, "token_hex", side_effect=["aaaaaaaa", "bbbbbbbb"]),
        ):
            self.assertNotEqual(remote_run._new_job_id(), remote_run._new_job_id())

    def test_run_records_exit_file_and_initial_state(self):
        args = SimpleNamespace(
            host="h",
            cmd="{python} experiment.py",
            approval_token="token",
        )
        jobs = {}
        captured = {}

        def fake_ssh(_host, command, timeout=60):
            captured["command"] = command
            return completed(0, "PID=42\n", "")

        def fake_save(value):
            captured["jobs"] = value

        with (
            mock.patch.object(
                remote_run, "load_host", return_value={"ssh": "h", "workdir": "~/w"}
            ),
            mock.patch.object(remote_run, "consume_approval") as consume,
            mock.patch.object(remote_run, "_new_job_id", return_value="job-unique"),
            mock.patch.object(remote_run, "ssh_run", side_effect=fake_ssh),
            mock.patch.object(remote_run, "load_jobs", return_value=jobs),
            mock.patch.object(remote_run, "save_jobs", side_effect=fake_save),
        ):
            remote_run.cmd_run(args)
        consume.assert_called_once_with(
            "token", "h", "{python} experiment.py", {"ssh": "h", "workdir": "~/w"}
        )
        self.assertIn("job-unique.exit", captured["command"])
        self.assertEqual(captured["jobs"]["job-unique"]["state"], "RUNNING")
        self.assertIsNone(captured["jobs"]["job-unique"]["exit_code"])


class FetchTests(unittest.TestCase):
    def test_fetch_only_downloads_small_named_evidence(self):
        listing = "manifest.json\nc001_evidence.json\nrun-summary.md\nraw.npy\nnotes.txt\n../bad\n"
        copied = []

        def fake_scp(arguments, timeout=600):
            copied.append(arguments[0])
            return completed()

        args = SimpleNamespace(host="h", problem="demo", max_bytes=1024)
        with (
            mock.patch.object(remote_run, "ROOT", str(ROOT)),
            mock.patch.object(
                remote_run,
                "load_host",
                return_value={"ssh": "u@h", "workdir": "~/w"},
            ),
            mock.patch.object(remote_run, "ssh_run", return_value=completed(0, listing)),
            mock.patch.object(remote_run, "scp_run", side_effect=fake_scp),
            mock.patch.object(remote_run.os, "makedirs"),
        ):
            remote_run.cmd_fetch(args)
        self.assertEqual(
            [item.rsplit("/", 1)[-1] for item in copied],
            ["c001_evidence.json", "manifest.json", "run-summary.md"],
        )
        self.assertTrue(all("raw.npy" not in item for item in copied))


if __name__ == "__main__":
    unittest.main()
