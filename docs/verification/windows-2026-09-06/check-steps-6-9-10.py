#!/usr/bin/env python3
"""Assert what the Windows runs of steps 6, 9 and 10 must show.

Reads the JSON the guest probe posted and states pass or fail per claim, so
the verification note quotes checks rather than adjectives.

    python3 check-steps-6-9-10.py [evidence-dir]
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Step 6: what each image case has to end up as. `Blocked by settings` is the
# second column, with `allow_insecure_remote_images` back at its default.
EXPECTED_IMAGES = {
    "relative": ("image", "image"),
    "absolute-rooted": ("image", "image"),
    "extensionless": ("image", "image"),
    "missing": ("Unavailable", "Unavailable"),
    "oversized-local": ("Too large", "Too large"),
    "remote-https": ("image", "image"),
    "remote-redirect": ("image", "Blocked by settings"),
    "remote-timeout": ("Timed out", "Blocked by settings"),
    "remote-invalid": ("Unavailable", "Blocked by settings"),
    "remote-oversized": ("Too large", "Blocked by settings"),
}
# Two spellings of a Windows absolute path that do not resolve. These are
# recorded as known failures, not as expectations: see the note's Findings.
KNOWN_BROKEN = {
    "absolute-drive": ("Unavailable", "Unavailable"),
    "absolute-file-url": ("Unavailable", "Unavailable"),
}

# Step 9: `kinds.md` carries front matter, a fence, `#hashtag`, closing hashes
# and both setext levels.
EXPECTED_HEADINGS = [
    (1, "ATX one"),
    (2, "Setext two"),
    (2, "ATX three"),
    (1, "Setext one"),
]


def load(directory, name):
    path = os.path.join(directory, name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def step_6(directory):
    allowed = load(directory, "i1-http-allowed.json")
    blocked = load(directory, "i2-http-blocked.json")
    if allowed is None or blocked is None:
        yield "step 6", "evidence present", False, ""
        return
    for label, (want_allowed, want_blocked) in sorted(EXPECTED_IMAGES.items()):
        got_a = allowed["results"].get(label, {}).get("result")
        got_b = blocked["results"].get(label, {}).get("result")
        yield (
            "step 6 http allowed",
            "{} -> {}".format(label, want_allowed),
            got_a == want_allowed,
            str(got_a),
        )
        yield (
            "step 6 http blocked",
            "{} -> {}".format(label, want_blocked),
            got_b == want_blocked,
            str(got_b),
        )
    for label, (want_allowed, _) in sorted(KNOWN_BROKEN.items()):
        got = allowed["results"].get(label, {}).get("result")
        yield (
            "step 6 KNOWN DEFECT",
            "{} does not resolve ({})".format(label, want_allowed),
            got == want_allowed,
            str(got),
        )
    # The three cases that do resolve locally must be the same 160x64 fixture.
    for label in ("relative", "absolute-rooted", "extensionless"):
        entry = allowed["results"].get(label, {})
        yield (
            "step 6 http allowed",
            "{} decodes to 160x64".format(label),
            (entry.get("width"), entry.get("height")) == (160, 64),
            "{}x{}".format(entry.get("width"), entry.get("height")),
        )


def step_9(directory):
    o1 = load(directory, "o1-no-preview.json")
    o2 = load(directory, "o2-with-preview.json")
    o3 = load(directory, "o3-heading-kinds.json")
    o4 = load(directory, "o4-caret-and-typing.json")
    o5 = load(directory, "o5-clicks.json")
    o6 = load(directory, "o6-empty-and-two-files.json")
    o7 = load(directory, "o7-zoom-and-close.json")
    if None in (o1, o2, o3, o4, o5, o6, o7):
        yield "step 9", "evidence present", False, ""
        return

    yield (
        "step 9 no preview",
        "the outline adds a group",
        o1["layout_after"]["num_groups"] == o1["layout_before"]["num_groups"] + 1,
        "{} -> {}".format(o1["layout_before"]["num_groups"], o1["layout_after"]["num_groups"]),
    )
    yield (
        "step 9 no preview",
        "that group holds only the outline",
        o1["layout_after"]["groups"][o1["outline"]["group"]]["sheets"] == 1,
        "",
    )
    yield (
        "step 9 with preview",
        "outline group is not the preview's",
        bool(o2["distinct_groups"]),
        "outline {} preview {}".format(o2["outline_group"], o2["preview_group"]),
    )
    yield (
        "step 9 with preview",
        "outline is not a tab beside the preview",
        o2["sheets_in_outline_group"] == 1,
        str(o2["sheets_in_outline_group"]),
    )

    found = [(h["level"], h["text"]) for h in o3["outline"]["headings"]]
    yield ("step 9 heading kinds", "exactly the four real headings", found == EXPECTED_HEADINGS, str(found))
    text = o3["source"]
    yield ("step 9 heading kinds", "front matter keys are in the source", "subtitle:" in text, "")
    yield (
        "step 9 heading kinds",
        "no front-matter entry",
        not any("subtitle" in h["text"] for h in o3["outline"]["headings"]),
        "",
    )
    yield (
        "step 9 heading kinds",
        "nothing from inside the fence",
        not any("inside a fence" in h["text"] for h in o3["outline"]["headings"]),
        "",
    )
    yield (
        "step 9 heading kinds",
        "#hashtag is not a heading",
        not any(h["text"].startswith("hashtag") for h in o3["outline"]["headings"]),
        "",
    )
    yield (
        "step 9 heading kinds",
        "closing hashes trimmed",
        ("ATX three" in [h["text"] for h in o3["outline"]["headings"]]),
        "",
    )

    for move in o4["moves"]:
        yield (
            "step 9 caret",
            "line {} activates entry {}".format(move["line"], move["expected"]),
            move["active"] == move["expected"],
            str(move["active"]),
        )
    yield ("step 9 typing", "a heading typed live appears", bool(o4["typed_present"]), "")

    for click in o5["clicks"]:
        yield (
            "step 9 clicks",
            "entry at line {} moves the caret there".format(click["line"]),
            click["caret_row"] == click["line"],
            str(click["caret_row"]),
        )

    yield ("step 9 no headings", "an empty document gets an empty outline",
           o6["none"]["open"] and not o6["none"]["headings"], str(len(o6["none"]["headings"])))
    yield ("step 9 two files", "three outlines open at once", o6["sessions_in_window"] == 3,
           str(o6["sessions_in_window"]))
    yield ("step 9 two files", "each outline has its own group",
           len({o6["none"]["group"], o6["second"]["group"], o6["kinds"]["group"]}) == 3, "")
    yield ("step 9 zoom", "zoom in changes the outline's zoom", o7["zoomed"]["zoom"] == 1.25,
           str(o7["zoomed"]["zoom"]))
    yield ("step 9 zoom", "reset puts it back", o7["reset"]["zoom"] == 1.0, str(o7["reset"]["zoom"]))
    yield ("step 9 close", "the toggle closes the outline", o7["after_close"]["open"] is False, "")


def step_10(directory):
    runs = {
        name: load(directory, "w1-{}.json".format(name))
        for name in (
            "short-auto_width-True",
            "long-auto_width-True",
            "short-auto_width-False",
            "long-auto_width-False",
        )
    }
    w2 = load(directory, "w2-drag-wins.json")
    w3 = load(directory, "w3-reopen-refits.json")
    w4 = load(directory, "w4-zoom-longer-resize.json")
    o1 = load(directory, "o1-no-preview.json")
    if None in list(runs.values()) + [w2, w3, w4, o1]:
        yield "step 10", "evidence present", False, ""
        return

    for panel in ("toc", "outline"):
        for document in ("short", "long"):
            on = runs["{}-auto_width-True".format(document)][panel]["width_px"]
            off = runs["{}-auto_width-False".format(document)][panel]["width_px"]
            yield (
                "step 10 not wider",
                "{} {} with auto_width on <= off".format(document, panel),
                on <= off,
                "{} vs {}".format(on, off),
            )
    yield (
        "step 10 narrow end",
        "short headings fit narrower than long ones",
        runs["short-auto_width-True"]["outline"]["width_px"]
        < runs["long-auto_width-True"]["outline"]["width_px"],
        "{} vs {}".format(
            runs["short-auto_width-True"]["outline"]["width_px"],
            runs["long-auto_width-True"]["outline"]["width_px"],
        ),
    )
    yield (
        "step 10 outline alone",
        "with no other panel the outline is readable (>=150px)",
        o1["outline"]["width_px"] >= 150,
        str(o1["outline"]["width_px"]),
    )
    yield (
        "step 10 KNOWN DEFECT",
        "with a table of contents open the outline is a sliver (<100px)",
        runs["long-auto_width-True"]["outline"]["width_px"] < 100,
        str(runs["long-auto_width-True"]["outline"]["width_px"]),
    )
    yield (
        "step 10 KNOWN DEFECT",
        "the outline cell is the role share of the toc cell, not the source's",
        abs(
            (1.0 - runs["long-auto_width-True"]["layout"]["cols"][3])
            / (1.0 - runs["long-auto_width-True"]["layout"]["cols"][2])
            - 0.3
        )
        < 0.01,
        str(runs["long-auto_width-True"]["layout"]["cols"]),
    )

    yield (
        "step 10 drag",
        "a dragged divider survives a repaint",
        w2["after_drag"]["cols"] == w2["after_repaint"]["cols"],
        "{} vs {}".format(w2["after_drag"]["cols"], w2["after_repaint"]["cols"]),
    )
    yield (
        "step 10 drag",
        "the drag actually moved the divider",
        w2["fitted"]["cols"] != w2["after_drag"]["cols"],
        "",
    )
    yield (
        "step 10 reopen",
        "closing and reopening hands the fit back",
        w3["outline"]["width_px"] != w2["outline"]["width_px"],
        "{} vs {}".format(w3["outline"]["width_px"], w2["outline"]["width_px"]),
    )
    yield (
        "step 10 resize",
        "the editor window really resized",
        bool(w4["resize"].get("ok")) and w4["layout"]["groups"][0]["width_px"] < 600,
        str(w4["layout"]["groups"][0]["width_px"]),
    )
    yield (
        "step 10 zoom",
        "zooming the outline changes its zoom",
        w4["zoomed"]["zoom"] == 1.5,
        str(w4["zoomed"]["zoom"]),
    )
    yield (
        "step 10 KNOWN DEFECT",
        "pinned width does not follow zoom",
        w4["zoomed"]["width_px"] == w4["base"]["width_px"],
        "{} vs {}".format(w4["zoomed"]["width_px"], w4["base"]["width_px"]),
    )
    yield (
        "step 10 KNOWN DEFECT",
        "pinned width does not follow a longer heading",
        w4["longer_heading"]["width_px"] == w4["base"]["width_px"],
        "{} vs {}".format(w4["longer_heading"]["width_px"], w4["base"]["width_px"]),
    )


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else HERE
    results = []
    for produce in (step_6, step_9, step_10):
        results.extend(produce(directory))

    failed = [row for row in results if not row[2]]
    for group, claim, ok, detail in results:
        print(
            "{}  {:24} {}{}".format(
                "PASS" if ok else "FAIL",
                group,
                claim,
                "  [{}]".format(detail) if detail and not ok else "",
            )
        )
    print("\n{} checks, {} failed".format(len(results), len(failed)))
    print(
        "Checks named KNOWN DEFECT pass when the defect is still present; they\n"
        "pin the behaviour the note reports as a finding, so a fix turns them red."
    )

    with open(os.path.join(directory, "steps-6-9-10-checks.json"), "w", encoding="utf-8") as sink:
        json.dump(
            {
                "total": len(results),
                "failed": len(failed),
                "results": [
                    {"group": group, "claim": claim, "pass": ok, "detail": detail}
                    for group, claim, ok, detail in results
                ],
            },
            sink,
            indent=2,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
