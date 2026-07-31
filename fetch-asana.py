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
#   "figures"   the big numbers
#                 "sum"   add up a number field across every task
#                         (leave "sum" out entirely to just count tasks)
#                 "where" optional filter, e.g. {"Status": "New"}
#
#   "breakdowns"  the bar charts - group tasks by a field, count each value
#                 "order" optional, forces the categories into this order
#                         and shows them even when the count is zero
#
SECTIONS = [
    {
        "name": "VSI Reports",
        "project": "1208906510346634",
        "figures": [
            {"label": "Performances", "sum": "Number of Sessions"},
            {"label": "Individuals Reached", "sum": "Number in Audience"},
        ],
        "breakdowns": [
            {
                "label": "Tech Status",
                "group_by": "Tech Status",
                "order": ["Yes", "No"],
            },
        ],
    },
    {
        "name": "NV Reports",
        "project": "1212646865573131",
        "figures": [
            {"label": "Lessons", "sum": "Number of Sessions"},
        ],
        "breakdowns": [],
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
    "custom_fields.name",
    "custom_fields.display_value",
    "custom_fields.number_value",
])


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


def field_value(task, field_name):
    for field in task.get("custom_fields", []):
        if field.get("name") == field_name:
            value = field.get("display_value")
            return value if value not in ("", None) else None
    return None


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


def matches_filter(task, conditions):
    for field_name, expected in (conditions or {}).items():
        if field_value(task, field_name) != expected:
            return False
    return True


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
        if not available:
            figures.append({"label": spec["label"], "value": None})
            continue
        rows = [t for t in tasks if matches_filter(t, spec.get("where"))]
        if "sum" in spec:
            total = sum(field_number(t, spec["sum"]) for t in rows)
        else:
            total = len(rows)
        figures.append({"label": spec["label"], "value": tidy_number(total)})

    breakdowns = []
    if available:
        for spec in section.get("breakdowns", []):
            rows = [t for t in tasks if matches_filter(t, spec.get("where"))]
            tally = Counter()
            for task in rows:
                tally[field_value(task, spec["group_by"]) or "Not set"] += 1

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

    # Print every field name found, per project. When a number comes back
    # as zero, this is where you check your spelling.
    print("\nField names available on your tasks:")
    for project_id, tasks in cache.items():
        names = sorted({
            field["name"]
            for task in tasks
            for field in task.get("custom_fields", [])
            if field.get("name")
        })
        print(f"  {project_id}:")
        for name in names:
            print(f"    - {name}")
        if not names:
            print("    (no custom fields found)")
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
