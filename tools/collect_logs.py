#!/usr/bin/env python3
"""Collect everything a bug report needs into one zip, with your user name, home folder and any key or token values
hidden.

  python3 tools/collect_logs.py                         -> beamng-earth-logs-<time>.zip in the current folder
  python3 tools/collect_logs.py --user-dir "C:/Users/me/AppData/Local/BeamNG.drive/current" -o bug.zip

It holds server.log and its two earlier runs, launcher.log, the game's beamng.log (when --user-dir is given or
found), the in-game reports, and SUMMARY.txt (tools/logdigest.py's summary of server.log). Nothing is sent anywhere.
"""
import argparse
import glob
import os
import platform
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, ".."))
import logtools  # noqa: E402


def find_user_dir():
    import apppaths
    cands = []
    if apppaths.IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or ""
        cands.append(os.path.join(base, "BeamNG", "BeamNG.drive", "current"))
        cands.append(os.path.join(base, "BeamNG.drive", "current"))
    else:
        home = os.path.expanduser("~")
        cands += [os.path.join(home, ".local", "share", "BeamNG.drive", "current"),
                  os.path.join(home, ".steam", "steam", "steamapps", "compatdata", "284160", "pfx", "drive_c", "users",
                               "steamuser", "AppData", "Local", "BeamNG", "BeamNG.drive", "current")]
    return next((c for c in cands if os.path.isdir(c)), None)


def main(argv=None):
    import apppaths
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out")
    ap.add_argument("--user-dir", help="the game's user folder (the one with beamng.log)")
    a = ap.parse_args(argv)
    logs = os.path.join(apppaths.data_dir(), "logs")
    files = []
    for p in sorted(glob.glob(os.path.join(logs, "*.log*"))):
        files.append((p, "logs/" + os.path.basename(p)))
    ud = a.user_dir or find_user_dir()
    if ud:
        files.append((os.path.join(ud, "beamng.log"), "game/beamng.log"))
        for p in sorted(glob.glob(os.path.join(ud, "beamngEarth", "reports", "*")))[-10:]:
            if os.path.isfile(p):
                files.append((p, "game/reports/" + os.path.basename(p)))
    summary = []
    try:
        with open(os.path.join(logs, "server.log"), encoding="utf-8", errors="replace") as f:
            summary = logtools.digest(f.read().splitlines())
    except OSError:
        summary = ["no server.log in " + logs]
    info = ["collected %s" % time.strftime("%Y-%m-%d %H:%M:%S"), "platform: %s" % platform.platform(),
            "python: %s" % sys.version.split()[0], "game user folder: %s" % (ud or "not found (use --user-dir)"), ""]
    out = a.out or "beamng-earth-logs-%s.zip" % time.strftime("%Y%m%d-%H%M%S")
    names = logtools.bundle(out, files, {"SUMMARY.txt": "\n".join(info + summary) + "\n"})
    print("wrote %s: %s" % (out, ", ".join(names)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
