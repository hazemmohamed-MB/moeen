"""Inspect and manage stored events from the command line (until the dashboard exists).

Usage (from the project root):
    python scripts/events.py                     # latest 20 events
    python scripts/events.py --open              # only open events (MONITORING / NEW)
    python scripts/events.py show 12             # one event with details and status history
    python scripts/events.py assist 12 --note "helped up"   # record assistance
    python scripts/events.py resolve 12 --note "false alarm during demo"
    python scripts/events.py --db data/other.db  # another database file
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moeen.config import ConfigError, load_config  # noqa: E402
from moeen.database import (Database, DatabaseError, EventNotFound, EventRepository,  # noqa: E402
                            InvalidStatusTransition)
from moeen.database.timestamps import to_local_display  # noqa: E402


def fmt_duration(sec: float | None) -> str:
    return "-" if sec is None else f"{sec:6.1f}s"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="list", choices=["list", "show", "assist", "resolve"])
    parser.add_argument("event_id", nargs="?", type=int)
    parser.add_argument("--db", help="database file (default: database.path from config)")
    parser.add_argument("--open", action="store_true", help="list only open events")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--note", help="note stored with a status change")
    args = parser.parse_args()

    try:
        path = Path(args.db) if args.db else load_config().database.path_resolved()
        repo = EventRepository(Database(path))
    except (ConfigError, DatabaseError) as exc:
        print(f"Error: {exc}")
        return 4 if isinstance(exc, ConfigError) else 6

    try:
        if args.command == "list":
            events = repo.list_events(limit=args.limit, open_only=args.open)
            print(f"{path}  ({repo.count_events()} events, {repo.count_events(open_only=True)} open)")
            if not events:
                print("no events")
            for e in events:
                print(f"#{e.id:<4} {to_local_display(e.created_at)}  {e.event_type.value:<10} "
                      f"{e.severity.value:<6} score {e.score:.2f}  {fmt_duration(e.duration_seconds)}  "
                      f"{e.status.value:<19} {e.resolution or ''}")
            return 0
        if args.event_id is None:
            parser.error(f"'{args.command}' needs an event id")
        if args.command == "assist":
            e = repo.record_assistance(args.event_id, note=args.note)
            print(f"#{e.id} -> {e.status.value}")
            return 0
        if args.command == "resolve":
            e = repo.resolve_event(args.event_id, resolution="MANUAL", note=args.note)
            print(f"#{e.id} -> {e.status.value}")
            return 0
        e = repo.get_event(args.event_id)
        print(json.dumps(e.to_dict(), indent=2))
        print("status history:")
        for h in repo.status_history(e.id):
            frm = h.from_status.value if h.from_status else "(created)"
            print(f"  {to_local_display(h.changed_at)}  {frm} -> {h.to_status.value}  {h.note or ''}")
        return 0
    except (EventNotFound, InvalidStatusTransition, ValueError) as exc:
        print(f"Error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
