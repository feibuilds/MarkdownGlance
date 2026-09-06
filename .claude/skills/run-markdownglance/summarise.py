#!/usr/bin/env python3
"""Print a pass/fail table for one evidence directory; exit 1 on any failure.

A phase fails when it timed out, when any of its checks is false, or when the
run left an `error.json`. Usage: summarise.py <evidence-dir>
"""

import json
import os
import sys


def main(evidence):
    failed = False
    error = os.path.join(evidence, "error.json")
    if os.path.exists(error):
        with open(error, encoding="utf-8") as handle:
            data = json.load(handle)
        print("ERROR in phase {}:".format(data.get("phase")))
        print(data.get("traceback", ""))
        failed = True
    phases_file = os.path.join(evidence, "phases.json")
    if not os.path.exists(phases_file):
        print("no phases.json: the probe never started (is probe.json in place?)")
        return 1
    with open(phases_file, encoding="utf-8") as handle:
        phases = json.load(handle)
    for entry in phases:
        name = entry["name"]
        path = os.path.join(evidence, name + ".json")
        if not os.path.exists(path):
            print("{:<16} MISSING (never reached)".format(name))
            failed = True
            continue
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        status = "TIMED OUT" if data.get("timed_out") else "done"
        failed = failed or bool(data.get("timed_out"))
        shot = os.path.join(evidence, name + ".png")
        print(
            "{:<16} {:<9} generation={} {}".format(
                name,
                status,
                data.get("generation"),
                os.path.basename(shot) if os.path.exists(shot) else "(no screenshot)",
            )
        )
        for check, ok in sorted(data.get("checks", {}).items()):
            print("    [{}] {}".format("ok" if ok else "FAIL", check))
            failed = failed or not ok
    print("RESULT:", "FAIL" if failed else "PASS", "-", evidence)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
