#!/usr/bin/env python3
"""
Pulls task data out of Asana, counts things up, and writes data.json.

You only need to edit the CONFIGURATION section below. Everything under
"machinery" can be left alone.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from collections import Counter
from datetime import datetime, timezone

# ============================================================
# CONFIGURATION - this is the only part you edit
# ============================================================

# The name shown at the very top of the page.
DASHBOARD_TITLE = "Program Metrics"

# Each entry below becomes one section of the dashboard.
#
#   "name"      the heading for that section
#   "project"   the Asana project ID, from the project's web address.
#               Set it to None if the board isn't ready yet - the section
#               shows placeholder dashes instead of calling Asana.
#               You can also pass a list of IDs to combine several boards
#               into one section, e.g. ["1208...", "1212..."]
#
#   "figures"   the big numbers, shown left to right in the order listed.
#               Pick ONE of these four:
#                 "sum"     add up a number field across every task
#                 "unique"  count how many different values appear in a
#                           field - use for "how many students", not
#                           "how many lessons"
#                 "fixed"   a number you type in and maintain by hand.
#                           Asana is never asked about it.
#                 (none)    just count the tasks
#
#               Add "list": True to a "unique" figure and the card becomes
#               clickable, opening a popup listing the values it counted.
#
#   "breakdowns"  the bar charts - group tasks by a field, count each value
#                 "order"   optional, forces the categories into this order
#                           and shows them even when the count is zero
#                 "rename"  optional, changes the words on the bars without
#                           changing what's asked of Asana
#                 "colors"  optional, sets each bar's colour. Use the house
#                           palette names: "accent" (coral), "live" (teal),
#                           "dev" (grey), "muted", "soft".
#
# Wherever a field name is asked for you can write "Tags" to use Asana's
# built-in tags. Tasks can hold several tags at once, so each one counts
# toward every tag it carries.
#
# Tidying up messy values - works on figures and breakdowns alike:
#
#   "ignore"    values to leave out entirely, e.g. ["Other", "TBD"]
#   "merge"     rewrite one value as another. Use it to shorten an awkward
#               tag for display, or to fold an old name into its current
#               one: {"Old Name": "Current Name"}
#               Give a list to split one value into several:
#                 {"A / B": ["A", "B"]}
#               Rewriting happens before counting, so two values pointing
#               at the same name collapse into one. Nothing in Asana
#               changes either way.
#
# Both figures and breakdowns accept these optional filters:
#
#   "where"     only tasks whose field matches, e.g. {"Status": "New"}
#   "between"   only tasks whose date field falls in a range:
#                 {"field": "Lesson Date",
#                  "from": "2026-09-01", "to": "2027-06-30"}
#               Dates must be written YYYY-MM-DD. Tasks with that date
#               field left blank are excluded.
#
# Note: "order", "rename" and "colors" key off the value as it stands
# after any merging.
#
SECTIONS = [
    {
        "name": "VSI Reports",
        "project": "1208906510346634",
        "figures": [
            {"label": "Performances", "sum": "Number of Sessions"},
            {"label": "Individuals Reached", "sum": "Number in Audience"},
            {
                "label": "Partner Facilities",
                "unique": "Tags",
                "list": True,
                # Not a facility - left out of the count entirely.
                "ignore": ["Other"],
                # Counted as one facility, shown by the short name.
                "merge": {
                    "Salastina / Huntington / UCLA": "Salastina",
                },
            },
        ],
        "breakdowns": [
            {
                "label": "Tech Issues",
                "group_by": "Tech Status",
                "order": ["Yes", "No"],
                "colors": {"Yes": "accent", "No": "live"},
            },
        ],
    },
    {
        "name": "NV Reports",
        "project": "1212646865573131",
        "figures": [
            {"label": "Lessons", "sum": "Number of Sessions"},
            {
                "label": "Enrollment 2026-2027",
                "unique": "Student",
                "between": {
                    "field": "Lesson Date",
                    "from": "2026-09-01",
                    "to": "2027-06-30",
                },
            },
            # Maintained by hand - edit the number below and commit.
            {"label": "Instruments Provided", "fixed": 14},
        ],
        "breakdowns": [
            {
                "label": "Tech Issues",
                "group_by": "Tech Status",
                "order": ["Yes", "No"],
                "colors": {"Yes": "accent", "No": "live"},
            },
        ],
    },
    {
        "name": "MFTF Metrics",
        # Board isn't built yet. Paste the project ID here when it is,
        # then replace each "REPLACE ME" with the real field name.
        "project": None,
        "figures": [
            {"label": "Students", "sum": "REPLACE ME"},
            {"label": "Graduates", "sum": "REPLACE ME"},
            {"label": "Compositions", "sum": "REPLACE ME"},
            {"label": "Instructional Hours", "sum": "REPLACE ME"},
        ],
        "breakdowns": [],
    },
]

# Set to True to skip tasks that are marked complete in Asana.
IGNORE_COMPLETED_TASKS = False

# Where to write the results.
OUTPUT_FILE = "data.json"

# ============================================================
# MACHINERY - you shouldn't need to change anything below here
# ============================================================

API_ROOT = "https://app.asana.com/api/1.0"

FIELDS_WE_WANT = ",".join([
    "name",
    "completed",
    "due_on",
    "tags.name",
    "custom_fields.name",
    "custom_fields.display_value",
    "custom_fields.number_value",
    "custom_fields.date_value",
    "custom_fields.multi_enum_values.name",
])

DUE_DATE_ALIASES = {"due date", "due on", "due_on"}
TAG_ALIASES = {"tags", "tag"}


class AsanaProblem(Exception):
    """One project couldn't be read, but the rest might still work."""


def get_token():
    token = os.environ.get("ASANA_TOKEN", "").strip()
    if not token:
        sys.exit(
            "No Asana token found.\n"
            "On GitHub, add it under Settings > Secrets and variables > "
            "Actions as a secret named ASANA_TOKEN."
        )
    return token


def call_asana(url, token):
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            # A bad token breaks everything, so stop right here.
            sys.exit(
                f"Asana rejected the token ({error.code}).\n"
                "Check that the ASANA_TOKEN secret is correct and hasn't "
                "been revoked in Asana under Settings > Apps."
            )
        body = error.read().decode("utf-8", errors="replace")[:300]
        raise AsanaProblem(f"HTTP {error.code} - {body}")
    except urllib.error.URLError as error:
        raise AsanaProblem(str(error.reason))


def fetch_all_tasks(project_id, token):
    """Asana sends 100 at a time, so keep asking until it stops."""
    tasks = []
    url = (
        f"{API_ROOT}/projects/{project_id}/tasks"
        f"?opt_fields={FIELDS_WE_WANT}&limit=100"
    )
    while url:
        payload = call_asana(url, token)
        tasks.extend(payload.get("data", []))
        next_page = payload.get("next_page")
        url = next_page.get("uri") if next_page else None
    return tasks


def values_for(task, field_name):
    """
    Every value a task holds for one field, as a list.

    Most fields hold a single value, so the list has one entry. Asana's
    built-in tags and multi-select fields can hold several at once, which
    is why this always returns a list.
    """
    for field in task.get("custom_fields", []):
        if field.get("name") == field_name:
            multi = field.get("multi_enum_values")
            if multi:
                return [m["name"] for m in multi if m.get("name")]
            value = field.get("display_value")
            return [value] if value not in ("", None) else []

    # Asana's built-in tags live outside custom fields.
    if field_name.strip().lower() in TAG_ALIASES:
        return [t["name"] for t in (task.get("tags") or []) if t.get("name")]

    return []


def tidied_values(task, field_name, spec, seen_keys):
    """Read a field, then apply the spec's ignore and merge settings."""
    ignore = set(spec.get("ignore") or [])
    merge = spec.get("merge") or {}

    out = []
    for value in values_for(task, field_name):
        if value in ignore:
            seen_keys.add(value)
            continue
        if value in merge:
            seen_keys.add(value)
            replacement = merge[value]
            if isinstance(replacement, list):
                out.extend(replacement)
            else:
                out.append(replacement)
        else:
            out.append(value)
    return out


def warn_about_unused(spec, seen_keys, label):
    """Flag merge or ignore entries that never matched anything."""
    configured = set(spec.get("ignore") or []) | set(spec.get("merge") or {})
    stale = sorted(configured - seen_keys)
    for entry in stale:
        print(f"  ! {label}: nothing in Asana matches '{entry}' - "
              "check the spelling, or drop it if the tag is gone")


def field_value(task, field_name):
    """The single value of a field, or None. Used for filtering."""
    found = values_for(task, field_name)
    return found[0] if found else None


def field_number(task, field_name):
    for field in task.get("custom_fields", []):
        if field.get("name") == field_name:
            number = field.get("number_value")
            if number is not None:
                return number
            text = (field.get("display_value") or "").replace(",", "").strip()
            try:
                return float(text)
            except ValueError:
                return 0
    return 0


def field_date(task, field_name):
    """Return a date as YYYY-MM-DD, or None if the task hasn't got one."""
    for field in task.get("custom_fields", []):
        if field.get("name") == field_name:
            stamp = field.get("date_value") or {}
            found = stamp.get("date") or stamp.get("date_time")
            return found[:10] if found else None

    # Fall back to Asana's own built-in due date.
    if field_name.strip().lower() in DUE_DATE_ALIASES:
        due = task.get("due_on")
        return due[:10] if due else None

    return None


def matches_filter(task, conditions):
    for field_name, expected in (conditions or {}).items():
        if expected not in values_for(task, field_name):
            return False
    return True


def within_range(task, window):
    """True if the task's date sits inside the configured window."""
    if not window:
        return True
    stamp = field_date(task, window["field"])
    if not stamp:
        return False  # no date recorded, so it can't be counted
    # YYYY-MM-DD sorts correctly as plain text, so no date maths needed.
    if window.get("from") and stamp < window["from"]:
        return False
    if window.get("to") and stamp > window["to"]:
        return False
    return True


def eligible_tasks(tasks, spec):
    """Apply both filters, in the order a person would expect."""
    rows = [t for t in tasks if matches_filter(t, spec.get("where"))]
    return [t for t in rows if within_range(t, spec.get("between"))]


def tidy_number(value):
    """4068.0 becomes 4068, but 12.5 stays 12.5."""
    return int(value) if float(value).is_integer() else round(float(value), 2)


def project_ids_for(section):
    project = section.get("project")
    if not project:
        return []
    return project if isinstance(project, list) else [project]


def build_section(section, tasks, available):
    """Turn one section of config into finished numbers."""
    figures = []
    for spec in section.get("figures", []):
        # Hand-maintained numbers don't depend on Asana, so they show
        # even when the board behind them isn't connected.
        if "fixed" in spec:
            figures.append({
                "label": spec["label"],
                "value": tidy_number(spec["fixed"]),
            })
            continue

        if not available:
            figures.append({"label": spec["label"], "value": None})
            continue

        rows = eligible_tasks(tasks, spec)
        figure = {"label": spec["label"]}

        if "unique" in spec:
            seen_keys = set()
            found = set()
            for task in rows:
                found.update(tidied_values(task, spec["unique"], spec,
                                           seen_keys))
            warn_about_unused(spec, seen_keys, spec["label"])
            figure["value"] = len(found)
            if spec.get("list"):
                # Sorted so the popup reads alphabetically, and so the
                # file doesn't churn between runs.
                figure["items"] = sorted(found, key=lambda s: s.lower())
        elif "sum" in spec:
            figure["value"] = tidy_number(
                sum(field_number(t, spec["sum"]) for t in rows)
            )
        else:
            figure["value"] = len(rows)

        figures.append(figure)

    breakdowns = []
    if available:
        for spec in section.get("breakdowns", []):
            rows = eligible_tasks(tasks, spec)
            seen_keys = set()
            tally = Counter()
            for task in rows:
                found = tidied_values(task, spec["group_by"], spec, seen_keys)
                if not found:
                    tally["Not set"] += 1
                for value in found:
                    tally[value] += 1
            warn_about_unused(spec, seen_keys, spec["label"])

            if spec.get("order"):
                # Show exactly these categories, in this order, zeros included.
                items = [
                    {"name": name, "value": tally.get(name, 0)}
                    for name in spec["order"]
                ]
            else:
                items = [
                    {"name": name, "value": count}
                    for name, count in tally.most_common()
                ]

            # Colour and relabel using the value as it stands after merging,
            # so these settings don't have to be kept in step with each other.
            rename = spec.get("rename") or {}
            colors = spec.get("colors") or {}
            for item in items:
                asana_value = item["name"]
                if asana_value in colors:
                    item["color"] = colors[asana_value]
                item["name"] = rename.get(asana_value, asana_value)

            breakdowns.append({"label": spec["label"], "items": items})

    return figures, breakdowns


def main():
    token = get_token()

    # Fetch each project once, even if two sections share it.
    cache = {}
    failures = {}
    for section in SECTIONS:
        for project_id in project_ids_for(section):
            if project_id in cache or project_id in failures:
                continue
            print(f"Fetching project {project_id} ...")
            try:
                cache[project_id] = fetch_all_tasks(project_id, token)
                print(f"  got {len(cache[project_id])} tasks")
            except AsanaProblem as problem:
                failures[project_id] = str(problem)
                print(f"  ! could not read it: {problem}")

    if IGNORE_COMPLETED_TASKS:
        for project_id, tasks in cache.items():
            cache[project_id] = [t for t in tasks if not t.get("completed")]

    # Print what each board offers, before any merging. When a number
    # looks wrong, this is the raw truth to compare against.
    print("\nWhat's available on your tasks (raw, before merging):")
    for project_id, tasks in cache.items():
        names = sorted({
            field["name"]
            for task in tasks
            for field in task.get("custom_fields", [])
            if field.get("name")
        })
        tag_names = sorted({
            tag["name"]
            for task in tasks
            for tag in (task.get("tags") or [])
            if tag.get("name")
        })
        print(f"  {project_id}:")
        print("    fields:")
        for name in names:
            print(f"      - {name}")
        if not names:
            print("      (none found)")
        print(f"    tags ({len(tag_names)} distinct):")
        for name in tag_names[:60]:
            print(f"      - {name}")
        if len(tag_names) > 60:
            print(f"      ... and {len(tag_names) - 60} more")
        if not tag_names:
            print("      (none found)")
    print()

    output_sections = []
    for section in SECTIONS:
        ids = project_ids_for(section)
        tasks = []
        note = None
        available = bool(ids)

        if not ids:
            note = "Not connected yet"
        else:
            broken = [pid for pid in ids if pid in failures]
            if broken:
                available = False
                note = "Could not read this board"
            else:
                for project_id in ids:
                    tasks.extend(cache.get(project_id, []))

        figures, breakdowns = build_section(section, tasks, available)
        output_sections.append({
            "name": section["name"],
            "note": note,
            "figures": figures,
            "breakdowns": breakdowns,
        })

        shown = ", ".join(
            f"{f['label']}={'-' if f['value'] is None else f['value']}"
            for f in figures
        )
        print(f"{section['name']}: {shown}")

    result = {
        "title": DASHBOARD_TITLE,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sections": output_sections,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(f"\nWrote {OUTPUT_FILE}")

    if failures:
        print("\nSome projects could not be read:")
        for project_id, reason in failures.items():
            print(f"  {project_id}: {reason}")
        print("A 404 usually means the ID is wrong, or your Asana account "
              "isn't a member of that project.")


if __name__ == "__main__":
    main()
