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

# The name shown at the top of your dashboard.
DASHBOARD_TITLE = "VSI Reports"

# Your Asana projects (boards).
# The key is a short nickname you make up. The value is the project ID.
# To find a project ID: open the project in Asana and look at the address bar.
#   https://app.asana.com/0/1201234567890123/list
#                            ^^^^^^^^^^^^^^^^ this number
PROJECTS = {
    "reports": "PASTE_PROJECT_ID_HERE",
    "second": "PASTE_PROJECT_ID_HERE",
    "third": "PASTE_PROJECT_ID_HERE",
}

# Big numbers across the top of the dashboard.
#
#   "label"    what shows under the number
#   "sum"      add up a number field on every task (leave out to just count tasks)
#   "projects" which nicknames from PROJECTS to include
#   "where"    optional filter, e.g. {"Status": "New"} means only tasks
#              whose "Status" field says "New"
#
HEADLINE_NUMBERS = [
    {
        "label": "Performances",
        "sum": "Performances",
        "projects": ["reports"],
    },
    {
        "label": "Individuals Reached",
        "sum": "Individuals Reached",
        "projects": ["reports"],
    },
    {
        "label": "New Reports",
        "projects": ["reports"],
        "where": {"Status": "New"},
    },
]

# Bar charts. Each one groups tasks by a field and counts how many
# fall into each value.
BREAKDOWNS = [
    {
        "label": "Tech Status",
        "group_by": "Tech Status",
        "projects": ["reports"],
    },
    {
        "label": "Submitted By",
        "group_by": "Submitted By",
        "projects": ["reports"],
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
PLACEHOLDER = "PASTE_PROJECT_ID_HERE"

FIELDS_WE_WANT = ",".join([
    "name",
    "completed",
    "custom_fields.name",
    "custom_fields.display_value",
    "custom_fields.number_value",
])


def get_token():
    token = os.environ.get("ASANA_TOKEN", "").strip()
    if not token:
        sys.exit(
            "No Asana token found.\n"
            "When running on GitHub, add it under Settings > Secrets and "
            "variables > Actions as a secret named ASANA_TOKEN.\n"
            "When running on your own computer, set the ASANA_TOKEN "
            "environment variable first."
        )
    return token


def call_asana(url, token):
    """Ask Asana for one page of results."""
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
        body = error.read().decode("utf-8", errors="replace")
        sys.exit(
            f"Asana refused the request ({error.code}).\n"
            f"URL: {url}\n"
            f"Asana said: {body}\n\n"
            "A 401 usually means the token is wrong or expired.\n"
            "A 404 usually means a project ID is wrong."
        )


def fetch_all_tasks(project_id, token):
    """Asana sends results 100 at a time, so keep asking until it stops."""
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
    """Read one custom field off a task. Returns None if it isn't set."""
    for field in task.get("custom_fields", []):
        if field.get("name") == field_name:
            value = field.get("display_value")
            return value if value not in ("", None) else None
    return None


def field_number(task, field_name):
    """Read a numeric custom field off a task. Returns 0 if it isn't set."""
    for field in task.get("custom_fields", []):
        if field.get("name") == field_name:
            number = field.get("number_value")
            if number is not None:
                return number
            # Fall back to the text version in case the field isn't
            # stored as a true number.
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


def selected_tasks(spec, tasks_by_project):
    chosen = []
    for nickname in spec.get("projects", list(tasks_by_project)):
        if nickname not in tasks_by_project:
            print(f"  ! Warning: no project nicknamed '{nickname}' - skipping")
            continue
        chosen.extend(tasks_by_project[nickname])
    return [t for t in chosen if matches_filter(t, spec.get("where"))]


def tidy_number(value):
    """4068.0 becomes 4068, but 12.5 stays 12.5."""
    return int(value) if float(value).is_integer() else round(float(value), 2)


def main():
    unset = [nick for nick, pid in PROJECTS.items() if pid == PLACEHOLDER]
    if len(unset) == len(PROJECTS):
        sys.exit(
            "No project IDs filled in yet.\n"
            "Open fetch-asana.py and replace PASTE_PROJECT_ID_HERE with the "
            "long number from each project's web address."
        )

    token = get_token()

    tasks_by_project = {}
    for nickname, project_id in PROJECTS.items():
        if project_id == PLACEHOLDER:
            print(f"Skipping '{nickname}' - no project ID set")
            continue
        print(f"Fetching '{nickname}' ({project_id}) ...")
        tasks_by_project[nickname] = fetch_all_tasks(project_id, token)
        print(f"  got {len(tasks_by_project[nickname])} tasks")

    if IGNORE_COMPLETED_TASKS:
        for nickname, tasks in tasks_by_project.items():
            tasks_by_project[nickname] = [
                t for t in tasks if not t.get("completed")
            ]

    # Print every field name we found. Handy when a metric comes back as 0
    # and you need to check the exact spelling.
    discovered = set()
    for tasks in tasks_by_project.values():
        for task in tasks:
            for field in task.get("custom_fields", []):
                if field.get("name"):
                    discovered.add(field["name"])
    print("\nField names available on your tasks:")
    for name in sorted(discovered):
        print(f"  - {name}")
    print()

    headline = []
    for spec in HEADLINE_NUMBERS:
        rows = selected_tasks(spec, tasks_by_project)
        if "sum" in spec:
            total = sum(field_number(t, spec["sum"]) for t in rows)
        else:
            total = len(rows)
        headline.append({"label": spec["label"], "value": tidy_number(total)})
        print(f"{spec['label']}: {tidy_number(total)}")

    breakdowns = []
    for spec in BREAKDOWNS:
        rows = selected_tasks(spec, tasks_by_project)
        tally = Counter()
        for task in rows:
            tally[field_value(task, spec["group_by"]) or "Not set"] += 1
        items = [
            {"name": name, "value": count}
            for name, count in tally.most_common()
        ]
        breakdowns.append({"label": spec["label"], "items": items})
        print(f"{spec['label']}: {len(items)} categories")

    result = {
        "title": DASHBOARD_TITLE,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "headline": headline,
        "breakdowns": breakdowns,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
