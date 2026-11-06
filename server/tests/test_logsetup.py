"""logsetup.py: one log format for the server and its workers, debug areas, crash hooks, the session's header."""
import argparse
import asyncio
import logging
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import logsetup  # noqa: E402


class AreasTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(logsetup.parse_areas("grading, surface;roads"),
                         ["earthd.grading", "earthd.surface", "earthd.roads"])
        self.assertEqual(logsetup.parse_areas("all"), [""])
        self.assertEqual(logsetup.parse_areas("earthd.foo.bar,duckdb.x,grading,grading"),
                         ["earthd.foo.bar", "duckdb.x", "earthd.grading"])
        self.assertEqual(logsetup.parse_areas(""), [])
        self.assertEqual(logsetup.parse_areas(None), [])
        self.assertEqual(logsetup.parse_areas("earthd"), ["earthd"])

    def test_apply_debug_from_the_environment(self):
        lg = logging.getLogger("earthd.testarea")
        try:
            with mock.patch.dict(os.environ, {logsetup.ENV: "testarea"}):
                self.assertEqual(logsetup.apply_debug(), ["earthd.testarea"])
            self.assertEqual(lg.level, logging.DEBUG)
            self.assertTrue(lg.isEnabledFor(logging.DEBUG))
            self.assertEqual(logging.getLogger("earthd.otherarea").getEffectiveLevel(),
                             logging.getLogger().getEffectiveLevel(), "other areas as they were")
        finally:
            lg.setLevel(logging.NOTSET)

    def test_configure_exports_for_the_workers(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(logsetup.ENV, None)
            try:
                logsetup.configure(False, "testexport")
                self.assertEqual(os.environ[logsetup.ENV], "testexport", "worker processes inherit it")
            finally:
                logging.getLogger("earthd.testexport").setLevel(logging.NOTSET)

    def test_debug_lines_pass_an_info_root(self):
        """An area's DEBUG lines reach the handlers though the root logger stays at INFO."""
        root = logging.getLogger()
        old = root.level
        root.setLevel(logging.INFO)
        lg = logging.getLogger("earthd.passarea")
        try:
            logsetup.apply_debug("passarea")
            with self.assertLogs("earthd.passarea", logging.DEBUG) as cm:
                lg.debug("visible")
            self.assertEqual(cm.output, ["DEBUG:earthd.passarea:visible"])
        finally:
            lg.setLevel(logging.NOTSET)
            root.setLevel(old)


class HeaderTest(unittest.TestCase):
    def test_lines(self):
        ap = argparse.ArgumentParser()
        ap.add_argument("--cells", type=int, default=32)
        ap.add_argument("--imagery", default="on")
        args = ap.parse_args(["--cells", "64"])
        lines = logsetup.session_lines(args, {a.dest: a.default for a in ap._actions}, ["earthd.grading"],
                                       environ={"BNGE_SAMPLE": "/tmp/x", "BNGE_API_KEY": "abc", "HOME": "/root",
                                                "BNE_GRADE_MAJOR": "x" * 500})
        text = "\n".join(lines)
        self.assertTrue(lines[0].startswith("session: BeamNG.Earth "), lines[0])
        self.assertIn("Python", lines[0])
        self.assertIn("logical CPUs", lines[1])
        self.assertIn("options: cells=64", text)
        self.assertNotIn("imagery", text, "defaults left out")
        self.assertIn("BNGE_SAMPLE=/tmp/x", text)
        self.assertIn("BNGE_API_KEY=<set>", text, "secrets masked")
        self.assertNotIn("abc", text)
        self.assertNotIn("HOME", text)
        self.assertIn("x" * logsetup.ENV_VALUE_CHARS + "...", text)
        self.assertIn("debug logging on for earthd.grading", text)

    def test_release_read(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "..", "VERSION"), encoding="utf-8") as f:
            self.assertEqual(logsetup.release(), f.read().strip())


class CrashHooksTest(unittest.TestCase):
    def setUp(self):
        logsetup.uninstall_crash_hooks()
        self.prev = (sys.excepthook, threading.excepthook)

    def tearDown(self):
        logsetup.uninstall_crash_hooks()
        sys.excepthook, threading.excepthook = self.prev

    def test_thread_and_main_exceptions_logged(self):
        lg = logging.getLogger("earthd.hooktest")
        with mock.patch("faulthandler.enable"):
            self.assertTrue(logsetup.install_crash_hooks(lg))
            self.assertFalse(logsetup.install_crash_hooks(lg), "once per process")

        def boom():
            raise ValueError("in a thread")
        with self.assertLogs("earthd.hooktest", logging.ERROR) as cm:
            t = threading.Thread(target=boom, name="worker-x")
            t.start()
            t.join()
            try:
                raise KeyError("main")
            except KeyError:
                sys.excepthook(*sys.exc_info())
        self.assertIn("uncaught ValueError in thread worker-x: in a thread", cm.output[0])
        self.assertIn("Traceback", cm.output[0])
        self.assertIn("uncaught KeyError in the main thread", cm.output[1])

    def test_asyncio_handler(self):
        lg = logging.getLogger("earthd.asynctest")

        async def run():
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(logsetup.asyncio_handler(lg))
            loop.call_exception_handler({"message": "Task exception was never retrieved",
                                         "exception": RuntimeError("lost")})
            loop.call_exception_handler({"message": "plain"})
        with self.assertLogs("earthd.asynctest", logging.ERROR) as cm:
            asyncio.run(run())
        self.assertIn("Task exception was never retrieved: RuntimeError: lost", cm.output[0])
        self.assertIn("plain", cm.output[1])


if __name__ == "__main__":
    unittest.main()
