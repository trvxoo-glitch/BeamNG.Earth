"""The server's logging set-up (server.log: the file players send): one format for earthd and its worker processes,
debug output per area, crash and stall evidence, and the session's header.

- FORMAT: every process's lines, "2026-10-17 07:04:50,488 INFO earthd.grading: ..." (launcher.echo_lines and the
  tools that read server.log parse it: keep it).
- Debug areas: `earthd --debug grading,surface` (or BNGE_DEBUG=grading,surface in the environment) turns on DEBUG for
  those loggers alone (earthd.grading, earthd.surface, ...), in the server and in every worker process it starts
  (they inherit the environment), so a problem in one area can be traced without -v's flood of every other area.
  "all" is -v. DEBUG_AREAS names the usual ones (the --help text); any earthd.<name> logger works.
- Crash evidence: an uncaught exception in any thread (and in an asyncio task nobody awaited) goes into the log with
  its traceback, and faulthandler writes every thread's stack on a native crash (Rust, DuckDB, numpy: GitHub #687's
  crashed session had only "Process finished" in its log).
- The session header (session_lines): the release, Python, the OS, the machine and the choices that differ from the
  defaults, first in every log, so a log from a player says what made it.
Pure but for the logging module, faulthandler and the environment.
"""
import atexit
import faulthandler
import logging
import os
import platform
import sys
import threading
import time

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
ENV = "BNGE_DEBUG"
# The areas a player or developer is likely to want (earthd --help); each is the logger "earthd.<area>".
DEBUG_AREAS = ("grading", "surface", "roads", "blockworker", "worker", "pools", "mapdata", "dem", "imagery", "net",
               "cache", "crossings", "vegetation", "buildings", "colormatch", "weather")
# Environment variables named like these have their values left out of the header (a key in BNGE_SERVER_ENV, ...).
SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASS", "AUTH", "COOKIE")
ENV_VALUE_CHARS = 120


def parse_areas(spec):
    """The logger names a debug spec turns on: "grading, surface" -> ["earthd.grading", "earthd.surface"]; "all" or
    "*" -> [""] (the root logger); a full dotted name (earthd.foo.bar, or another package's) stays as it is. Pure."""
    out = []
    for part in str(spec or "").replace(";", ",").replace(" ", ",").split(","):
        part = part.strip().lower()
        if not part:
            continue
        if part in ("all", "*"):
            name = ""
        elif "." in part:
            name = part
        else:
            name = "earthd" if part == "earthd" else "earthd." + part
        if name not in out:
            out.append(name)
    return out


def apply_debug(spec=None):
    """Turn DEBUG on for the areas of spec (default: $BNGE_DEBUG). Returns the logger names turned on."""
    names = parse_areas(os.environ.get(ENV, "") if spec is None else spec)
    for name in names:
        logging.getLogger(name or None).setLevel(logging.DEBUG)
    return names


def configure(verbose=False, debug=None, export=True):
    """The server's logging: INFO (DEBUG with verbose) in FORMAT, plus the debug areas (debug: a spec, else
    $BNGE_DEBUG). export: put the spec in the environment, for the worker processes started after this."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format=FORMAT)
    if debug and export:
        os.environ[ENV] = str(debug)
    return apply_debug(debug)


def worker(level=logging.INFO):
    """A worker process's logging (blockworker.init, peerwork, sharehelper): the server's level and format, and the
    debug areas it inherited in the environment."""
    logging.basicConfig(level=level, format=FORMAT)
    return apply_debug()


# ---------------------------------------------------------------------------------------------- crash evidence
_hooked = False


def install_crash_hooks(log=None, fault_file=None):
    """Uncaught exceptions of the main thread and of every other thread into the log, with their tracebacks (they
    went to stderr only, unlabelled and without a time), and faulthandler on fault_file (default stderr: server.log
    under the launcher) for native crashes. Once per process; returns False when already installed."""
    global _hooked
    if _hooked:
        return False
    _hooked = True
    log = log or logging.getLogger("earthd")
    prev_sys, prev_thread = sys.excepthook, threading.excepthook

    def sys_hook(et, ev, tb):
        if issubclass(et, KeyboardInterrupt):
            return prev_sys(et, ev, tb)
        log.critical("uncaught %s in the main thread: %s", et.__name__, ev, exc_info=(et, ev, tb))

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread is not None else "?"
        log.error("uncaught %s in thread %s: %s", args.exc_type.__name__, name, args.exc_value,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    sys.excepthook = sys_hook
    threading.excepthook = thread_hook
    try:
        f = fault_file or sys.stderr
        if f is not None and hasattr(f, "fileno"):
            f.fileno()                  # (no real file under some test runners: then no faulthandler)
            faulthandler.enable(file=f, all_threads=True)
    except (OSError, ValueError, AttributeError, RuntimeError):
        pass
    started = time.time()

    def at_exit():
        try:
            log.info("shutdown: server process ending normally after %.0f s", time.time() - started)
        except Exception:
            pass
    atexit.register(at_exit)
    install_crash_hooks.atexit = at_exit
    hooks = (prev_sys, prev_thread)
    install_crash_hooks.previous = hooks
    return True


def uninstall_crash_hooks():
    """The hooks before install_crash_hooks (tests)."""
    global _hooked
    at_exit = getattr(install_crash_hooks, "atexit", None)
    if at_exit is not None:
        atexit.unregister(at_exit)
    prev = getattr(install_crash_hooks, "previous", None)
    if prev is not None:
        sys.excepthook, threading.excepthook = prev
    _hooked = False


def asyncio_handler(log=None):
    """A loop exception handler (loop.set_exception_handler): a task's exception nobody retrieved, a callback's
    error, into the log with the task's name and traceback (asyncio printed them to stderr, at shutdown at best)."""
    log = log or logging.getLogger("earthd")

    def handler(loop, context):
        exc = context.get("exception")
        what = context.get("message") or "asyncio error"
        task = context.get("task") or context.get("future")
        name = ""
        if task is not None:
            try:
                name = " (task %s)" % task.get_name()
            except AttributeError:
                name = " (%r)" % (task,)
        if exc is not None:
            log.error("%s%s: %s: %s", what, name, type(exc).__name__, exc,
                      exc_info=(type(exc), exc, exc.__traceback__))
        else:
            log.error("%s%s", what, name)
    return handler


# ------------------------------------------------------------------------------------------------ session header
def _memory_gb():
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return m.ullTotalPhys / 2 ** 30, m.ullAvailPhys / 2 ** 30
            return None
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
        avail = None
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        avail = int(line.split()[1]) / 2 ** 20
                        break
        except OSError:
            pass
        return total, avail
    except (OSError, ValueError, AttributeError):
        return None


def release():
    """The release in the repository's VERSION file ('' when none: a packaged app reads it the same way)."""
    for root in (os.path.dirname(os.path.dirname(os.path.abspath(__file__))), getattr(sys, "_MEIPASS", "")):
        try:
            with open(os.path.join(root, "VERSION"), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            continue
    return ""


def changed_args(args, defaults):
    """{name: value} of the argparse Namespace's values that differ from defaults (a Namespace or dict of the parser's
    defaults), in name order. Pure."""
    d = vars(defaults) if not isinstance(defaults, dict) else defaults
    out = {}
    for k in sorted(vars(args)):
        v = getattr(args, k)
        if k in d and d[k] == v:
            continue
        out[k] = v
    return out


def env_lines(environ=None, prefixes=("BNGE_", "BNE_", "BNGEARTH_")):
    """'NAME=value' of the mod's own environment switches that are set (secrets masked, long values cut). Pure."""
    environ = os.environ if environ is None else environ
    out = []
    for k in sorted(environ):
        if not k.startswith(prefixes):
            continue
        v = str(environ[k])
        if any(w in k.upper() for w in SECRET_WORDS):
            v = "<set>"
        elif len(v) > ENV_VALUE_CHARS:
            v = v[:ENV_VALUE_CHARS] + "..."
        out.append(f"{k}={v}")
    return out


def session_lines(args=None, defaults=None, debug_names=(), environ=None, extra=()):
    """The header lines (without the logger's prefix): the release and Python, the OS and machine, the choices that
    differ from the defaults, the environment switches set, the debug areas on."""
    mem = _memory_gb()
    frozen = " (packaged app)" if getattr(sys, "frozen", False) else ""
    lines = [f"session: BeamNG.Earth {release() or '?'}{frozen}, Python {platform.python_version()} "
             f"({platform.python_implementation()}, {platform.architecture()[0]}), pid {os.getpid()}",
             f"session: {platform.system()} {platform.release()} ({platform.version()[:60]}), {platform.machine()}, "
             f"{os.cpu_count() or '?'} logical CPUs"
             + (f", {mem[0]:.1f} GB RAM" + (f" ({mem[1]:.1f} GB free)" if mem[1] is not None else "") if mem else "")]
    if args is not None and defaults is not None:
        ch = changed_args(args, defaults)
        if ch:
            lines.append("session: options: " + ", ".join(f"{k}={v!r}" for k, v in ch.items()))
    env = env_lines(environ)
    if env:
        lines.append("session: environment: " + ", ".join(env))
    if debug_names:
        lines.append("session: debug logging on for " + ", ".join(n or "everything" for n in debug_names))
    lines.extend("session: " + x for x in extra)
    return lines

