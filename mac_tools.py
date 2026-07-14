"""Explicit, bounded macOS actions for Jarvis."""

from __future__ import annotations

import platform
import subprocess
import time
from datetime import datetime
from urllib.parse import urlparse

import psutil


APP_ALIASES = {
    "chrome": "Google Chrome", "google chrome": "Google Chrome",
    "github": "GitHub Desktop", "github desktop": "GitHub Desktop",
    "code": "Visual Studio Code", "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code", "finder": "Finder",
}

APP_PROCESS_NAMES = {
    "Visual Studio Code": ["Visual Studio Code", "Code"],
    "Google Chrome": ["Google Chrome", "Chrome"],
}


def canonical_application_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    return APP_ALIASES.get(cleaned.lower(), cleaned.title().replace("Github", "GitHub"))


def application_exists(name: str) -> bool:
    result = subprocess.run(
        ["/usr/bin/open", "-Ra", canonical_application_name(name)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
    )
    return result.returncode == 0


def _run(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
    return result.stdout.strip()


def _apple(script: str, *args: str) -> str:
    return _run(["/usr/bin/osascript", "-e", script, "--", *map(str, args)])


def open_application(name: str) -> dict:
    name = canonical_application_name(name)
    subprocess.run(["/usr/bin/open", "-a", name], check=True, timeout=20)
    # The process can be alive with every window closed. A standard reopen event
    # restores its normal window without launching a duplicate instance.
    subprocess.run(
        [
            "/usr/bin/osascript", "-l", "JavaScript", "-e",
            "function run(argv) { const app = Application(argv[0]); app.reopen(); app.activate(); }", name,
        ],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if name == "GitHub Desktop":
        window_count = _apple(
            "on run argv\ntell application \"System Events\" to tell process (item 1 of argv) to return count of windows\nend run",
            name,
        )
        if window_count.strip() == "0":
            # GitHub Desktop can remain alive after its last window is closed and
            # ignores the standard reopen event. It has no unsaved editor state,
            # so a normal quit/relaunch is the bounded repair for an explicit
            # request to open or operate it.
            subprocess.run(
                ["/usr/bin/osascript", "-l", "JavaScript", "-e", "Application('GitHub Desktop').quit()"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            stopped = False
            for _ in range(20):
                running = _apple(
                    "on run argv\ntell application \"System Events\" to return exists (first application process whose name is item 1 of argv)\nend run",
                    name,
                )
                if running.strip().lower() == "false":
                    stopped = True
                    break
                time.sleep(0.25)
            if not stopped:
                return {
                    "ok": False, "application": name, "frontmost": False,
                    "error_code": "application_window_unavailable", "retryable": True,
                    "error": "GitHub Desktop is running without a window and did not exit cleanly for relaunch.",
                }
            subprocess.run(["/usr/bin/open", "-a", name], check=True, timeout=20)
    script = """on run argv
tell application "System Events"
  repeat 20 times
    repeat with appName in argv
      if exists (first application process whose name is appName) then
        set frontmost of (first application process whose name is appName) to true
        return "frontmost"
      end if
    end repeat
    delay 0.1
  end repeat
end tell
return "opened"
end run"""
    status = _apple(script, *APP_PROCESS_NAMES.get(name, [name]))
    return {"ok": True, "application": name, "frontmost": status == "frontmost"}


def quit_application(name: str) -> dict:
    """Request a normal macOS quit and verify the process actually exits."""
    name = canonical_application_name(name)
    if not name:
        return {"ok": False, "error_code": "missing_application", "requires_user": True, "error": "An application name is required."}
    _run([
        "/usr/bin/osascript", "-l", "JavaScript", "-e",
        "function run(argv) { Application(argv[0]).quit(); return 'requested'; }", name,
    ])
    script = """on run argv
set appName to item 1 of argv
tell application "System Events"
  repeat 30 times
    if not (exists (first application process whose name is appName)) then return "closed"
    delay 0.1
  end repeat
end tell
return "still_running"
end run"""
    status = _apple(script, name)
    if status == "closed":
        return {"ok": True, "application": name, "closed": True}
    return {
        "ok": False,
        "application": name,
        "closed": False,
        "error_code": "unsaved_changes_dialog",
        "requires_user": True,
        "error": f"{name} is still open, possibly because it is waiting for an unsaved-changes dialog.",
    }


def frontmost_application() -> str:
    return _apple(
        'tell application "System Events" to return name of first application process whose frontmost is true'
    ).strip()


def open_url(url: str, browser: str = "Safari") -> dict:
    """Navigate a browser semantically instead of typing into its UI."""
    url = url.strip()
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"ok": False, "error_code": "invalid_url", "requires_user": True, "error": "Only valid http and https URLs are allowed."}
    browser = "Safari" if browser.strip().lower() in {"", "default", "the browser", "browser"} else canonical_application_name(browser)
    subprocess.run(["/usr/bin/open", "-a", browser, url], check=True, timeout=20)
    activation = open_application(browser)
    return {"ok": True, "url": url, "browser": browser, "frontmost": activation["frontmost"]}


def set_system_volume(level: int) -> dict:
    level = max(0, min(100, int(level)))
    _apple("on run argv\nset volume output volume (item 1 of argv as integer)\nend run", str(level))
    return {"ok": True, "volume": level}


def clipboard(action: str, text: str = "") -> dict:
    if action == "read":
        return {"ok": True, "text": _run(["/usr/bin/pbpaste"])[:12000]}
    subprocess.run(["/usr/bin/pbcopy"], input=text, text=True, check=True, timeout=10)
    return {"ok": True, "characters": len(text)}


def system_status() -> dict:
    battery = psutil.sensors_battery()
    disk = psutil.disk_usage("/")
    return {
        "ok": True,
        "computer": platform.node(),
        "macos": platform.mac_ver()[0],
        "architecture": platform.machine(),
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": disk.percent,
        "battery_percent": battery.percent if battery else None,
        "power_connected": battery.power_plugged if battery else None,
    }


def notify(title: str, message: str) -> dict:
    script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
    _apple(script, title, message)
    return {"ok": True}


def create_reminder(title: str, list_name: str = "Reminders") -> dict:
    script = """on run argv
tell application "Reminders"
  if exists list (item 2 of argv) then
    set targetList to list (item 2 of argv)
  else
    set targetList to first list
  end if
  make new reminder at end of reminders of targetList with properties {name:item 1 of argv}
end tell
end run"""
    _apple(script, title, list_name)
    return {"ok": True, "title": title, "list": list_name}


def create_note(title: str, body: str, folder: str = "Notes") -> dict:
    script = """on run argv
tell application "Notes"
  if exists folder (item 3 of argv) of default account then
    set targetFolder to folder (item 3 of argv) of default account
  else
    set targetFolder to first folder of default account
  end if
  make new note at targetFolder with properties {name:item 1 of argv, body:item 2 of argv}
end tell
end run"""
    _apple(script, title, body, folder)
    return {"ok": True, "title": title, "folder": folder}


def create_calendar_event(title: str, start: str, duration_minutes: int, calendar: str) -> dict:
    start_at = datetime.fromisoformat(start)
    script = """on run argv
set startDate to current date
set year of startDate to item 2 of argv as integer
set month of startDate to item 3 of argv as integer
set day of startDate to item 4 of argv as integer
set hours of startDate to item 5 of argv as integer
set minutes of startDate to item 6 of argv as integer
set seconds of startDate to 0
set endDate to startDate + ((item 7 of argv as integer) * minutes)
tell application "Calendar"
  if exists calendar (item 8 of argv) then
    set targetCalendar to calendar (item 8 of argv)
  else
    set targetCalendar to first calendar whose writable is true
  end if
  tell targetCalendar
    make new event with properties {summary:item 1 of argv, start date:startDate, end date:endDate}
  end tell
end tell
end run"""
    _apple(
        script,
        title,
        str(start_at.year),
        str(start_at.month),
        str(start_at.day),
        str(start_at.hour),
        str(start_at.minute),
        str(max(1, int(duration_minutes))),
        calendar,
    )
    return {"ok": True, "title": title, "start": start_at.isoformat(), "calendar": calendar}


def create_email_draft(to: str, subject: str, body: str) -> dict:
    script = """on run argv
tell application "Mail"
  set draftMessage to make new outgoing message with properties {subject:item 2 of argv, content:item 3 of argv, visible:true}
  tell draftMessage to make new to recipient at end of to recipients with properties {address:item 1 of argv}
  activate
end tell
end run"""
    _apple(script, to, subject, body)
    return {"ok": True, "to": to, "subject": subject, "status": "draft_opened_not_sent"}


def find_contact(name: str) -> dict:
    script = """on run argv
tell application "Contacts"
  set matches to every person whose name contains item 1 of argv
  set output to ""
  repeat with p in matches
    set output to output & name of p
    if (count of emails of p) > 0 then set output to output & " | " & value of first email of p
    if (count of phones of p) > 0 then set output to output & " | " & value of first phone of p
    set output to output & linefeed
  end repeat
  return output
end tell
end run"""
    return {"ok": True, "matches": _apple(script, name)[:12000]}


def find_files(query: str) -> dict:
    output = _run(["/usr/bin/mdfind", query])
    return {"ok": True, "paths": output.splitlines()[:20]}


def shortcuts(action: str, name: str = "") -> dict:
    if action == "list":
        names = _run(["/usr/bin/shortcuts", "list"]).splitlines()
        return {"ok": True, "shortcuts": names[:100]}
    if not name.strip():
        return {"ok": False, "error": "A shortcut name is required."}
    _run(["/usr/bin/shortcuts", "run", name])
    return {"ok": True, "shortcut": name}
