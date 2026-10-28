#!/usr/bin/env python3
"""
Pulls task data out of Asana, counts things up, and writes data.json.

You only need to edit the CONFIGURATION section below. Everything under
"machinery" can be left alone.
"""

import csv
import difflib
import io
import json
import os
import re
import sys
import unicodedata
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
#   "status"    optional, for a section with no project yet. Replaces the
#               grey "No connection" label with a yellow one saying this,
#               e.g. "In progress".
#
#   "figures"   the big numbers, shown left to right in the order listed.
#               Pick ONE of these five:
#                 "sum"     add up a number field across every task
#                 "unique"  count how many different values appear in a
#                           field - use for "how many students", not
#                           "how many lessons". Give a list of fields,
#                           e.g. ["Tags", "Hospital/Facility"], to pool
#                           them - a value found in both counts once.
#                 "fixed"   a number you type in and maintain by hand.
#                           Asana is never asked about it.
#                 "sheet"   count the names in the first column of a
#                           Google Sheet - paste the sheet's link. The
#                           sheet must be shared as "Anyone with the link
#                           can view". Asana is never asked about it.
#                 (none)    just count the tasks
#
#               Add "list": True to a "unique" figure and the card becomes
#               clickable, opening a popup listing the values it counted.
#
#               Or add "table" to a "unique" figure for a popup table with
#               one row per value counted. List the columns to show, using
#               the exact Asana column names, e.g.
#                 "table": ["Student", "Location", "Instrument"]
#               If a student's tasks hold more than one value for a column
#               (two instruments, say), the row shows all of them.
#
#               "link_text" changes the words at the bottom of a clickable
#               card, e.g. "View enrollment". Leave it out for "View list".
#
#               "flip_names": True turns "Last, First" into "First Last"
#               for display. It happens first, so write any "ignore" or
#               "merge" names the way the dashboard shows them.
#
#               "match_names": True also folds near-miss spellings of a
#               name into the version entered as "Last, First" - so
#               "Nathan Choi" counts under "Choi, Nathanial", and "Elena
#               Ariza" under "Ariza, Elena Stephanie". It ignores accents,
#               capitals and middle initials, and accepts short forms and
#               small typos. A name with extra words (a note in brackets,
#               a second person) is left alone so it stands out to fix.
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
# toward every tag it carries. Write "Name" to use the task's own name.
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
                "label": "Partner Organizations",
                # Older reports name the facility in a tag; newer ones use
                # the Hospital/Facility column. Both are read, and a name
                # that appears in both is counted once.
                "unique": ["Tags", "Hospital/Facility"],
                "list": True,
                # Not a facility - left out of the count entirely.
                "ignore": ["Other"],
                "merge": {
                    # Counted as one facility, shown by the short name.
                    "Salastina / Huntington / UCLA": "Salastina",
                    # Misspelled old tag - counted under the correct name.
                    "Cedar Sinai LA": "Cedars-Sinai LA",
                    # Art Pharmacy renamed itself SocialRx - one partner.
                    "Art Pharmacy": "Art Pharmacy/SocialRx",
                    "Other - SocialRx": "Art Pharmacy/SocialRx",
                },
            },
            {
                "label": "Musicians",
                # The task name is the musician. Older entries were typed
                # in by hand, so some read "Last, First" and some "First
                # Last" - flipping makes them match so each counts once.
                "unique": "Name",
                "list": True,
                "link_text": "Artist roster",
                "flip_names": True,
                # Near-miss spellings count under the "Last, First" one.
                "match_names": True,
                "ignore": [
                    # Not a musician - a task holding the starting totals.
                    "Starting count from Google Sheet",
                    # A duo - each is listed on their own.
                    "Emily and Kaitlin Webster-Zuber",
                ],
                "merge": {
                    # Spelled many ways by hand - all one musician.
                    "Julia Vai": "Julia Varsovie",
                    "Julia Vari": "Julia Varsovie",
                    # Shown by her full name.
                    "Bernardo Marcondes": "Bernardo Marcondes Rodrigues",
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
                # Clicking the card opens a table, one row per student.
                "table": ["Student", "Location", "Instrument"],
                "link_text": "View enrollment",
            },
            {
                "label": "Instructors",
                # The task name is the instructor, written "Last, First".
                "unique": "Name",
                "between": {
                    "field": "Lesson Date",
                    "from": "2026-09-01",
                    "to": "2027-06-30",
                },
                "list": True,
                "link_text": "Instructor roster",
                # Shown as "First Last" on the dashboard.
                "flip_names": True,
                "merge": {
                    # Same person, entered two ways.
                    "Sam Budish": "Samuel Budish",
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
        "name": "MFTF Metrics",
        # Board isn't built yet. Paste the project ID here when it is,
        # then replace each "REPLACE ME" with the real field name.
        "project": None,
        # Shown as a yellow label next to the heading until then.
        "status": "In progress",
        "figures": [
            {"label": "Students", "sum": "REPLACE ME"},
            {
                "label": "Facilities",
                # Read from the MFTF Facility List sheet, so the count
                # follows any edits made there.
                "sheet": "https://docs.google.com/spreadsheets/d/"
                         "1rtCDNVIW034Dzp9IlNk6irWLwCnmMvhNdgknovEpLno/"
                         "edit?usp=sharing",
                # Not a facility - left out of the count entirely.
                "ignore": ["Other"],
                "list": True,
                "link_text": "Our facilities",
            },
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
NAME_ALIASES = {"name", "task name"}


class AsanaProblem(Exception):
    """One project couldn't be read, but the rest might still work."""


class SheetProblem(Exception):
    """A Google Sheet couldn't be read; only its own figure is affected."""


def sheet_csv_url(link):
    """Turn a normal Google Sheets link into its plain-text download link."""
    found = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", link)
    if not found:
        return link  # already a direct download link
    url = (f"https://docs.google.com/spreadsheets/d/{found.group(1)}"
           "/export?format=csv")
    tab = re.search(r"[#&?]gid=(\d+)", link)
    if tab:
        url += f"&gid={tab.group(1)}"
    return url


def fetch_sheet_names(link):
    """Every non-blank entry in the first column of a Google Sheet."""
    request = urllib.request.Request(
        sheet_csv_url(link), headers={"User-Agent": "pmhu-dashboard"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            kind = response.headers.get("Content-Type", "")
            text = response.read().decode("utf-8-sig", errors="replace")
    except urllib.error.HTTPError as error:
        raise SheetProblem(f"HTTP {error.code}")
    except urllib.error.URLError as error:
        raise SheetProblem(str(error.reason))

    # A private sheet answers with Google's sign-in page, not the data.
    if "csv" not in kind and text.lstrip().startswith("<"):
        raise SheetProblem(
            "Google sent a sign-in page instead of the sheet. In the sheet, "
            "click Share and set General access to 'Anyone with the link'."
        )

    names = []
    for row in csv.reader(io.StringIO(text)):
        if row and row[0].strip():
            names.append(row[0].strip())
    return names


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

    # So does the task's own name.
    if field_name.strip().lower() in NAME_ALIASES:
        name = (task.get("name") or "").strip()
        return [name] if name else []

    return []


def flipped(name):
    """'Henderson, Luke' becomes 'Luke Henderson'. Anything else is kept."""
    name = " ".join(name.split())  # tidy stray or doubled spaces
    parts = name.split(",")
    if len(parts) != 2:
        return name
    last, first = parts[0].strip(), parts[1].strip()
    return f"{first} {last}" if first and last else name


def tidied_values(task, field_name, spec, seen_keys):
    """Read a field, then apply the spec's ignore and merge settings."""
    return tidied(values_for(task, field_name), spec, seen_keys)


def tidied(values, spec, seen_keys):
    """Apply the spec's flip_names, ignore and merge settings to values."""
    ignore = set(spec.get("ignore") or [])
    merge = spec.get("merge") or {}

    out = []
    for value in values:
        if spec.get("flip_names"):
            value = flipped(value)
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


def name_key(name):
    """A name with accents, capitals, dots and extra spaces stripped."""
    plain = unicodedata.normalize("NFKD", name)
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return " ".join(plain.replace(".", " ").casefold().split())


def name_words(name):
    """The words of a name, leaving out single-letter middle initials."""
    return [word for word in name_key(name).split() if len(word) > 1]


def same_word(a, b):
    """Equal, a short form (Matt / Matthew), or a small typo."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 3 and long_.startswith(short):
        return True
    return (len(short) >= 5 and
            difflib.SequenceMatcher(None, a, b).ratio() >= 0.85)


def fits_inside(small, big):
    """
    Every word of `small` matches a word of `big`, in order, and the first
    names match. "Elena Ariza" fits inside "Elena Stephanie Ariza"; "Emily
    and Kaitlin Webster-Zuber" does not fit inside "Emily Webster-Zuber".
    """
    s, b = name_words(small), name_words(big)
    if not s or not b or not same_word(s[0], b[0]):
        return False
    matched = 0
    for word in b:
        if matched < len(s) and same_word(s[matched], word):
            matched += 1
    return matched == len(s)


def match_names(counts, trusted):
    """
    Decide which spelling each name counts under. Returns
    {name as found: name to count it as}.
    """
    def rank(name):
        return (name in trusted,
                name not in (name.lower(), name.upper()),
                counts[name],
                len(name))

    # 1. The same name apart from accents, capitals, dots or spacing.
    groups = {}
    for name in counts:
        groups.setdefault(name_key(name), []).append(name)
    chosen = {}
    for variants in groups.values():
        head = max(variants, key=rank)
        for variant in variants:
            chosen[variant] = head
            if variant in trusted:
                trusted = trusted | {head}

    def redirect(old, new):
        for variant, target in chosen.items():
            if target == old:
                chosen[variant] = new

    def heads():
        return sorted(set(chosen.values()), key=rank)

    # 2. A typed-in name that fits inside exactly one trusted name.
    anchors = [h for h in heads() if h in trusted]
    for head in heads():
        if head in trusted:
            continue
        fits = [a for a in anchors if fits_inside(head, a)]
        if len(fits) == 1:
            redirect(head, fits[0])

    # 3. Two typed-in names with no trusted version that match word for
    #    word (Nathan Choi / Nathanial Choi). The more-used one wins.
    for head in heads():
        if head in trusted or head not in chosen.values():
            continue
        words = len(name_words(head))
        fits = [other for other in heads()
                if other != head and other not in trusted
                and len(name_words(other)) == words
                and fits_inside(head, other)]
        if len(fits) == 1 and rank(fits[0]) > rank(head):
            redirect(head, fits[0])

    return chosen


def same_name_any_case(counts):
    """
    Treat "matthew aucoin" and "Matthew Aucoin" as one person, shown the
    way it's most often typed with normal capitals.
    """
    groups = {}
    for name, count in counts.items():
        groups.setdefault(name.casefold(), []).append((name, count))
    merged = Counter()
    for variants in groups.values():
        best = max(
            variants,
            key=lambda v: (v[0] not in (v[0].lower(), v[0].upper()), v[1]),
        )[0]
        merged[best] = sum(count for _, count in variants)
    return merged


def build_table(tasks, spec, key_fields):
    """
    One row per value counted, for the popup table.

    A column that is the counted field shows that value itself. Any other
    column gathers what that value's tasks hold - so a student taught two
    instruments shows both - joined with commas.
    """
    columns = spec["table"]
    gathered = {}
    for task in tasks:
        keys = set()
        for field_name in key_fields:
            keys.update(tidied_values(task, field_name, spec, set()))
        for key in keys:
            cells = gathered.setdefault(key, {c: set() for c in columns})
            for column in columns:
                if column not in key_fields:
                    cells[column].update(values_for(task, column))

    for column in columns:
        if column in key_fields:
            continue
        if gathered and not any(cells[column] for cells in gathered.values()):
            print(f"  ! {spec['label']}: table column '{column}' is empty - "
                  "check the name matches the Asana column exactly")

    rows = []
    for key in sorted(gathered, key=lambda s: s.lower()):
        rows.append([
            key if column in key_fields
            else ", ".join(sorted(gathered[key][column], key=str.lower))
            for column in columns
        ])
    return {"columns": columns, "rows": rows}


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

        # Neither do Google Sheet lists.
        if "sheet" in spec:
            figure = {"label": spec["label"], "value": None}
            try:
                seen_keys = set()
                found = set(tidied(fetch_sheet_names(spec["sheet"]), spec,
                                   seen_keys))
                warn_about_unused(spec, seen_keys, spec["label"])
                figure["value"] = len(found)
                if spec.get("list"):
                    figure["items"] = sorted(found, key=lambda s: s.lower())
                if spec.get("link_text"):
                    figure["link_text"] = spec["link_text"]
            except SheetProblem as problem:
                print(f"  ! {spec['label']}: could not read the sheet - "
                      f"{problem}")
            figures.append(figure)
            continue

        if not available:
            figures.append({"label": spec["label"], "value": None})
            continue

        rows = eligible_tasks(tasks, spec)
        figure = {"label": spec["label"]}

        if "unique" in spec:
            # One field name or a list of them; values are pooled.
            field_names = spec["unique"]
            if not isinstance(field_names, list):
                field_names = [field_names]
            seen_keys = set()
            found = Counter()
            # Names entered "Last, First", or named as a merge target,
            # are the trusted spellings that near-misses fold into.
            trusted = set()
            merge_targets = set()
            for target in (spec.get("merge") or {}).values():
                merge_targets.update(target if isinstance(target, list)
                                     else [target])
            for field_name in field_names:
                from_this_field = Counter()
                for task in rows:
                    for raw in values_for(task, field_name):
                        for value in tidied([raw], spec, seen_keys):
                            from_this_field[value] += 1
                            if (" ".join(raw.split()).count(",") == 1
                                    or value in merge_targets):
                                trusted.add(value)
                if not from_this_field:
                    print(f"  ! {spec['label']}: nothing found in "
                          f"'{field_name}' - check the field name matches "
                          "Asana exactly")
                found.update(from_this_field)
            warn_about_unused(spec, seen_keys, spec["label"])
            if spec.get("match_names"):
                chosen = match_names(found, trusted)
                folded = {v: c for v, c in chosen.items() if v != c}
                for variant in sorted(folded, key=str.lower):
                    print(f"  ~ {spec['label']}: counting '{variant}' as "
                          f"'{folded[variant]}'")
                merged = Counter()
                for name, count in found.items():
                    merged[chosen[name]] += count
                found = merged
                # Kept in the data file (not shown on the page) so the
                # matches can be checked.
                figure["matched"] = dict(sorted(folded.items()))
            elif spec.get("flip_names"):
                found = same_name_any_case(found)
            figure["value"] = len(found)
            if spec.get("list"):
                # Sorted so the popup reads alphabetically, and so the
                # file doesn't churn between runs.
                figure["items"] = sorted(found, key=lambda s: s.lower())
            if spec.get("table"):
                figure["table"] = build_table(rows, spec, field_names)
            if spec.get("link_text"):
                figure["link_text"] = spec["link_text"]
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
        note_color = None
        available = bool(ids)

        if not ids:
            if section.get("status"):
                note = section["status"]
                note_color = "yellow"
            else:
                note = "No connection"
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
            "note_color": note_color,
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
