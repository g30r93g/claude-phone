"""Meetings from the Mac's Calendar app (EventKit), so any account synced there works: Google, iCloud,
Exchange. Read-only. The first read asks macOS for calendar access for the process that runs the daemon."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import log

lg = log.get("diary")
_store = None


@dataclass(frozen=True)
class Meeting:
    key: str  # event id + start: a recurring meeting's occurrences share an id
    title: str
    start: datetime
    end: datetime
    people: tuple[str, ...]  # other attendees, by name


def access() -> bool:
    """True once macOS has granted calendar access; asks (and waits up to a minute) the first time."""
    global _store
    import EventKit
    if _store is None:
        _store = EventKit.EKEventStore.alloc().init()
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeEvent)
    if status in (EventKit.EKAuthorizationStatusAuthorized, getattr(EventKit, "EKAuthorizationStatusFullAccess", 3)):
        return True
    if status != EventKit.EKAuthorizationStatusNotDetermined:
        return False
    done, result = threading.Event(), []

    def cb(granted, err):
        result.append(bool(granted))
        done.set()
    if hasattr(_store, "requestFullAccessToEventsWithCompletion_"):
        _store.requestFullAccessToEventsWithCompletion_(cb)
    else:
        _store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeEvent, cb)
    done.wait(60)
    if result and result[0]:
        _store = EventKit.EKEventStore.alloc().init()  # a store made before the grant sees no calendars
        return True
    return False


def calendars() -> list[str]:
    import EventKit
    return [c.title() for c in _store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)] if access() else []


def _dt(ns) -> datetime:
    return datetime.fromtimestamp(ns.timeIntervalSince1970()).astimezone()


def meetings(start: datetime, end: datetime, only: list[str] | None = None) -> list[Meeting]:
    """Timed events overlapping start..end, minus all-day, cancelled and declined ones, by start time."""
    import EventKit
    from Foundation import NSDate
    if not access():
        return []
    cals = [c for c in _store.calendarsForEntityType_(EventKit.EKEntityTypeEvent) if not only or c.title() in only]
    if not cals:
        return []
    pred = _store.predicateForEventsWithStartDate_endDate_calendars_(
        NSDate.dateWithTimeIntervalSince1970_(start.timestamp()), NSDate.dateWithTimeIntervalSince1970_(end.timestamp()), cals)
    out = []
    for e in _store.eventsMatchingPredicate_(pred) or []:
        if e.isAllDay() or e.status() == EventKit.EKEventStatusCanceled:
            continue
        people, declined = [], False
        for a in e.attendees() or []:
            if a.isCurrentUser():
                declined = a.participantStatus() == EventKit.EKParticipantStatusDeclined
            elif a.participantType() == EventKit.EKParticipantTypePerson and a.name():
                people.append(str(a.name()))
        if declined:
            continue
        s = _dt(e.startDate())
        out.append(Meeting(f"{e.eventIdentifier()}@{s.isoformat()}", str(e.title() or "Meeting"), s, _dt(e.endDate()),
                           tuple(people)))
    return sorted(out, key=lambda m: m.start)


def summary(m: Meeting) -> tuple[str, str]:
    """(title, text) for the phone's screen: "15:00 Board review" / "with Sarah, Dan +2" / "DND until 15:30"."""
    first = [p.split()[0] if "@" not in p else p.split("@")[0] for p in m.people]
    who = ""
    if first:
        who = "with " + ", ".join(first[:2]) + (f" +{len(first) - 2}" if len(first) > 2 else "") + "\n"
    return f"{m.start:%H:%M} {m.title}", f"{who}DND until {m.end:%H:%M}"


def window(now: datetime, warn: timedelta, only: list[str] | None = None) -> list[Meeting]:
    """Meetings in progress or starting within `warn`."""
    return [m for m in meetings(now - timedelta(hours=12), now + warn, only) if m.end > now and m.start - warn <= now]
