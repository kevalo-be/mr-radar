#!/usr/bin/env python3
# <xbar.title>MR Radar</xbar.title>
# <xbar.version>v1.0.3</xbar.version>
# <xbar.author>Kevin Van Loo</xbar.author>
# <xbar.author.github>kevalo-be/mr-radar</xbar.author.github>
# <xbar.desc>Your open GitLab merge requests</xbar.desc>
# <xbar.dependencies>python3,glab</xbar.dependencies>
# <xbar.abouturl>https://github.com/kevalo-be/mr-radar</xbar.abouturl>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

WINDOWS = sys.platform == "win32"
# SwiftBar runs plugins without Homebrew on the PATH: Apple Silicon, then Intel.
GLAB = (shutil.which("glab") if WINDOWS else shutil.which("glab", path="/opt/homebrew/bin:/usr/local/bin")) or "glab"
CACHE = (pathlib.Path(os.environ.get("LOCALAPPDATA") or pathlib.Path.home() / "AppData/Local") / "mr-radar"
         if WINDOWS else pathlib.Path.home() / "Library/Caches")
STATE = CACHE / "mr-radar.json"
LAST_FETCH = CACHE / "mr-radar-last-fetch.json"  # redraws a toggle click without GitLab
SELF = pathlib.Path(__file__).resolve()
# without CREATE_NO_WINDOW, every glab call from the Windows tray flashes a console window
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}
PEOPLE = pathlib.Path.home() / ".config/mr-radar/people"
PEOPLE_TEMPLATE = """\
# MR Radar shows the open merge requests of the GitLab users below.
# Write one username per line. A # starts a comment.
# jdoe
"""
REPOS = pathlib.Path.home() / ".config/mr-radar/repos"
REPOS_TEMPLATE = """\
# MR Radar lists the open merge requests of the GitLab repositories below.
# They are not counted in the menu bar and send no notifications.
# Write one repository path per line. A # starts a comment.
# my-group/my-project
"""
DASHBOARD = "https://gitlab.com/dashboard/merge_requests?reviewer_username={}"
MY_DASHBOARD = "https://gitlab.com/dashboard/merge_requests?author_username={}"
SETTINGS = pathlib.Path.home() / ".config/mr-radar/settings.json"
ORDER = {"🔴": 0, "🟠": 1, "⚪": 2, "🟢": 3}
RED_AFTER = timedelta(hours=1)
RED_AFTER_CHOICES = {"15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240}  # label: minutes
HELP = [
    "Reviews, followed people and repositories",
    "🔴 Not approved by you, older than the Red after time",
    "🟠 Approved by you, but new commits were pushed since",
    "⚪ Not approved by you, younger than the Red after time",
    "🟢 Approved by you, nothing pushed since",
    "---",
    "My merge requests",
    "🔴 Has open comments",
    "🟠 No open comments, still needs approvals",
    "🟢 No open comments, and approved",
    "---",
    "💬 Number of open comment threads on your merge requests",
    "📁 A followed repository: click to open its merge requests",
    "🔒 Not logged in to GitLab",
    "⚠️ GitLab could not be reached, or a repository was not found",
    "---",
    "Open the README | href=https://github.com/kevalo-be/mr-radar#readme",
]


class NotLoggedIn(Exception):
    pass


def api(path, attempts=3):
    # utf-8: Windows would decode titles and names with its ANSI code page
    try:
        # timeout: a hung glab would block the Windows tray for good, SwiftBar only loses one run
        r = subprocess.run([GLAB, "api", path], capture_output=True, encoding="utf-8", errors="replace",
                           timeout=60, **NO_WINDOW)
    except FileNotFoundError:
        raise RuntimeError("glab is not installed") from None
    if r.returncode:
        if "401" in r.stderr + r.stdout:  # also what glab returns without a token
            raise NotLoggedIn
        if attempts > 1:  # gitlab.com connects time out now and then
            return api(path, attempts - 1)
        raise RuntimeError(" ".join((r.stderr or r.stdout).split()).removeprefix("ERROR ") or "glab api failed")
    return json.loads(r.stdout)


def colour(mr, me, red_after):
    base = f"projects/{mr['project_id']}/merge_requests/{mr['iid']}"
    approved_at = next((a["approved_at"] for a in api(f"{base}/approvals")["approved_by"]
                        if a["user"]["username"] == me), None)
    if not approved_at:
        return "🔴" if is_older(mr["created_at"], red_after) else "⚪"
    last_push = max(v["created_at"] for v in api(f"{base}/versions"))
    return "🟠" if last_push > approved_at else "🟢"


def open_threads(discussions):
    return [d for d in discussions if d["notes"][0]["resolvable"] and not d["notes"][0]["resolved"]]


def mine(mr):
    base = f"projects/{mr['project_id']}/merge_requests/{mr['iid']}"
    # shortcut: counts the first 100 threads only, paginate if an MR ever has more
    threads = open_threads(api(f"{base}/discussions?per_page=100"))
    if threads:
        return "🔴", threads
    return ("🟢" if api(f"{base}/approvals")["approved"] else "🟠"), threads


def listed(path, template):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template, encoding="utf-8")
    # utf-8: Notepad saves utf-8, Windows would read the file with its ANSI code page
    names = (line.split("#")[0].strip().lstrip("@") for line in path.read_text(encoding="utf-8").splitlines())
    return [n for n in names if n]


def repo_mrs(repo):
    """The open MRs of a followed repository, or None when GitLab does not know the path."""
    try:
        # shortcut: the first 100 open MRs only, paginate if a followed repository ever has more
        return api(f"projects/{quote(repo, safe='')}/merge_requests?state=opened&per_page=100")
    except RuntimeError as e:
        if "404" in str(e):
            return None
        raise


def load_settings(path):
    try:
        settings = json.loads(path.read_text())
        return settings if isinstance(settings, dict) else {}
    except (FileNotFoundError, ValueError):  # missing or hand-edited badly
        return {}


def save_setting(path, key, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**load_settings(path), key: value}))


def load_red_after(path):
    try:
        return timedelta(minutes=load_settings(path)["red_after_minutes"])
    except (KeyError, TypeError):
        return RED_AFTER


def save_red_after(path, minutes):
    save_setting(path, "red_after_minutes", int(minutes))


def is_older(gitlab_time, age, now=None):
    # Python 3.9 (macOS /usr/bin/python3) cannot parse the trailing Z
    created = datetime.fromisoformat(gitlab_time.replace("Z", "+00:00"))
    return (now or datetime.now(timezone.utc)) - created > age


def short(title):
    title = title.replace("|", "¦")
    # truncate here: SwiftBar's length= adds a hover tooltip with the full title
    return title[:70] + "…" if len(title) > 70 else title


def tip(text):
    return 'tooltip="' + text.replace('"', "'") + '"'  # a " would end SwiftBar's quoted value


def arg(value):
    # shortcut: a value with a " or ' breaks the line, quote-escape it if such a path ever shows up
    value = str(value)
    return f'"{value}"' if " " in value else value  # SwiftBar splits an unquoted value at a space


def run_self(*params):
    """SwiftBar parameters that run this file with params: the tray calls act() with them instead."""
    return f"bash={arg(SELF)} " + " ".join(f"param{i}={arg(p)}" for i, p in enumerate(params, 1))


def open_file(path):
    if WINDOWS:
        subprocess.Popen(["notepad.exe", str(path)])  # startfile would ask which app opens a file without extension
    else:
        subprocess.run(["/usr/bin/open", "-t", str(path)])


def mr_line(icon, mr):
    return (f"{icon} {short(mr['title'])} | href={mr['web_url']} "
            + tip(f"{mr['references']['full']} · {mr['author']['name']}"))


def render(me, rows, red_after=RED_AFTER, own=(), hide_approved=False, repos=(), missing=()):
    """rows, repos: lists of (icon, mr), own: list of (icon, open threads, mr),
    missing: repository paths GitLab does not know. Returns SwiftBar output."""
    rows = sorted(rows, key=lambda r: (ORDER[r[0]], r[1]["updated_at"]))
    approved = len({mr["id"] for icon, mr in [*rows, *repos] if icon == "🟢"})  # an MR can be in both lists
    toggle = run_self("--hide-approved", "off" if hide_approved else "on") + " terminal=false refresh=true"
    if hide_approved:
        rows = [r for r in rows if r[0] != "🟢"]
        repos = [r for r in repos if r[0] != "🟢"]
    own = sorted(own, key=lambda r: (ORDER[r[0]], r[2]["updated_at"]))
    count = {c: sum(1 for icon, _ in rows if icon == c) for c in ORDER}
    count["💬"] = sum(len(threads) for _, threads, _ in own)
    lines = [" ".join(f"{c} {count[c]}" for c in ("🔴", "🟠", "💬") if count[c]) or "🟢", "---"]
    lines += [mr_line(icon, mr) for icon, mr in rows]
    if not rows:
        lines.append("Nothing to review")
    if own:
        lines += ["---", "My merge requests"]
    for icon, threads, mr in own:
        n = len(threads)
        suffix = f" 💬 {n}" if n else ""
        lines.append(f"{icon} {short(mr['title'])}{suffix} | href={mr['web_url']} "
                     + tip(f"{mr['references']['full']} · {n} open thread{'' if n == 1 else 's'}"))
    if repos or missing:
        lines += ["---", "Repositories"]
    groups = {}  # keeps the order of the repos file, which main passes on
    for icon, mr in repos:
        groups.setdefault(mr["references"]["full"].split("!")[0], []).append((icon, mr))
    for path, group in groups.items():
        lines.append(f"📁 {path} | href=https://gitlab.com/{path}/-/merge_requests")
        lines += [mr_line(icon, mr) for icon, mr in sorted(group, key=lambda r: (ORDER[r[0]], r[1]["updated_at"]))]
    lines += [f"⚠️ {r}: not found | {run_self('--open', REPOS)} terminal=false" for r in missing]
    lines += ["---", f"Open GitLab dashboard | href={DASHBOARD.format(me)}",
              f"Open my merge requests | href={MY_DASHBOARD.format(me)}",
              f"Edit people… | {run_self('--open', PEOPLE)} terminal=false",
              f"Edit repos… | {run_self('--open', REPOS)} terminal=false",
              (f"Show approved by me ({approved} hidden)" if hide_approved else f"Hide approved by me ({approved})") + f" | {toggle}"]
    minutes = red_after // timedelta(minutes=1)
    label = next((l for l, m in RED_AFTER_CHOICES.items() if m == minutes), f"{minutes}m")
    lines.append(f"Red after: {label}")
    for l, m in RED_AFTER_CHOICES.items():
        lines.append(f"--{l} | {run_self('--red-after', m)} terminal=false refresh=true checked={str(m == minutes).lower()}")
    lines += ["Help"] + ["--" + l for l in HELP]
    lines.append("Refresh | refresh=true")
    return "\n".join(lines)


def thread_news(own, me, known):
    """known: thread ids from the last run, None on the first run. Returns (notifications, thread ids)."""
    ids, texts = [], []
    for _, threads, mr in own:
        others = [d["id"] for d in threads if d["notes"][0]["author"]["username"] != me]
        ids += others
        n = 0 if known is None else len(set(others) - set(known))
        if n:
            texts.append((f"{'New comment' if n == 1 else f'{n} new comments'}: {mr['title']}", mr["web_url"]))
    return texts, ids


def notify(text, href=None):
    if WINDOWS:
        from win11toast import notify as toast
        try:  # a string on_click opens the URL through Windows, also after MR Radar restarts
            # without a link, win11toast's template makes a click launch a bare "http:"
            toast(title="MR Radar", body=text, on_click=href or "https://gitlab.com")
        except Exception:  # shortcut: a failing toast is dropped silently, log it if toasts go missing
            pass
        return
    # SwiftBar sends the alert, so a click opens href; an osascript alert would open Script Editor
    params = {"plugin": "mr-radar", "title": "MR Radar", "body": text, **({"href": href} if href else {})}
    subprocess.run(["/usr/bin/open", "-g", "swiftbar://notify?" + urlencode(params, quote_via=quote)])


def mark_rerender(path):
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return  # nothing fetched yet: SwiftBar's refresh fetches
    path.write_text(json.dumps({**data, "rerender": True}))


def rerender(path, hide_approved):
    """The menu from the last fetch when a toggle click asked for it, else None: fetch from GitLab."""
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return None
    if not data.get("rerender"):
        return None
    path.write_text(json.dumps({**data, "rerender": False}))
    return render(data["me"], data["rows"], timedelta(minutes=data["red_after_minutes"]), data["own"], hide_approved,
                  data.get("repos", []), data.get("missing", []))


def main():
    hide_approved = load_settings(SETTINGS).get("hide_approved") is True
    print(rerender(LAST_FETCH, hide_approved) or fetch(hide_approved))


def fetch(hide_approved):
    """Calls GitLab, sends the notifications, saves the state, and returns the menu text."""
    CACHE.mkdir(parents=True, exist_ok=True)  # %LOCALAPPDATA%\mr-radar does not exist on a new Windows install
    state = json.loads(STATE.read_text()) if STATE.exists() else {"seen": [], "logged_in": True}
    try:
        me = api("user")["username"]
        filters = [f"reviewer_username={me}"] + [f"author_username={quote(p)}"
                                                 for p in listed(PEOPLE, PEOPLE_TEMPLATE) if p != me]
        repos = listed(REPOS, REPOS_TEMPLATE)
        with ThreadPoolExecutor(4) as pool:
            pages = list(pool.map(lambda f: api(f"merge_requests?scope=all&state=opened&{f}&per_page=100"),
                                  filters + [f"author_username={me}"]))
            repo_pages = list(pool.map(repo_mrs, repos))
            # an MR by a followed person can also have you as reviewer: keep it once
            found = {m["id"]: m for page in pages[:-1] for m in page if m["author"]["username"] != me}
            mrs = [m for m in found.values() if not m["draft"]]
            own = [m for m in pages[-1] if not m["draft"]]
            # an MR in the main list shows under its repository too, it counts and notifies in the main list only
            in_repos = {m["id"]: m for page in repo_pages if page for m in page
                        if m["author"]["username"] != me and not m["draft"]}
            missing = [r for r, page in zip(repos, repo_pages) if page is None]
            red_after = load_red_after(SETTINGS)
            rows = list(zip(pool.map(lambda m: colour(m, me, red_after), mrs), mrs))
            repo_rows = list(zip(pool.map(lambda m: colour(m, me, red_after), in_repos.values()), in_repos.values()))
            own_rows = [(icon, threads, m) for (icon, threads), m in zip(pool.map(mine, own), own)]
    except NotLoggedIn:
        if state["logged_in"]:
            notify("Not logged in to GitLab")
        STATE.write_text(json.dumps({**state, "logged_in": False}))
        return (f"🔒 MR\n---\nNot logged in to GitLab\nLog in… | bash={arg(GLAB)} param1=auth param2=login "
                "terminal=true refresh=true")
    except Exception as e:  # offline, GitLab down: show it, keep the state for the next run
        reason = (str(e).splitlines() or [type(e).__name__])[0][:80].replace("|", "¦")  # a | would start fake params
        return f"⚠️ MR\n---\n{reason}\nRefresh | refresh=true"

    menu = render(me, rows, red_after, own_rows, hide_approved, repo_rows, missing)
    LAST_FETCH.write_text(json.dumps({"me": me, "rows": rows, "own": own_rows, "repos": repo_rows, "missing": missing,
                                      "red_after_minutes": red_after // timedelta(minutes=1)}))
    todo = {f"{mr['id']}{icon}": (icon, mr) for icon, mr in rows if icon in ("🔴", "🟠")}
    for key in todo.keys() - set(state["seen"]):
        icon, mr = todo[key]
        notify(f"{'Review' if icon == '🔴' else 'New commits'}: {mr['title']}", mr["web_url"])
    texts, thread_ids = thread_news(own_rows, me, state.get("threads"))
    for text, href in texts:
        notify(text, href)
    STATE.write_text(json.dumps({"seen": list(todo), "threads": thread_ids, "logged_in": True}))
    return menu


def selftest():
    mr = lambda i, t, u: {"id": i, "title": t, "updated_at": u, "web_url": "u",
                          "references": {"full": "g/p!1"}, "author": {"name": "A"}}
    out = render("me", [("🟢", mr(1, "done", "1")), ("⚪", mr(4, "fresh", "4")),
                        ("🔴", mr(2, "a|b", "2")), ("🟠", mr(3, "pushed", "3"))])
    lines = out.splitlines()
    assert lines[0] == "🔴 1 🟠 1", "fresh MRs must not count in the menu bar: " + lines[0]
    assert [l[0] for l in lines[2:6]] == ["🔴", "🟠", "⚪", "🟢"], lines
    assert lines[6] == "---", "an MR has a tooltip, not a submenu line under it: " + lines[6]
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    assert is_older("2026-11-09T10:59:00.000Z", RED_AFTER, now)
    assert not is_older("2026-11-09T11:30:00.000Z", RED_AFTER, now)
    assert "a¦b |" in lines[2], "a pipe in a title must not break the SwiftBar line"
    long = render("me", [("🔴", mr(5, "x" * 80, "5"))]).splitlines()[2]
    assert long == f'🔴 {"x" * 70}… | href=u tooltip="g/p!1 · A"', \
        "a long title is cut, and the tooltip names project and author instead of the full title: " + long
    quoted = {**mr(5, "q", "5"), "author": {"name": 'A "B"'}}
    assert render("me", [("🔴", quoted)]).splitlines()[2].endswith("tooltip=\"g/p!1 · A 'B'\""), \
        "a quote in a name must not end the tooltip"
    assert render("me", []).splitlines()[0] == "🟢"
    note = lambda resolvable, resolved: {"notes": [{"resolvable": resolvable, "resolved": resolved}]}
    threads = [note(True, False), note(True, True), note(False, False)]
    assert open_threads(threads) == threads[:1], "only resolvable, unresolved threads are open"
    own = [("🟢", [], mr(6, "approved", "6")), ("🔴", threads[:1] * 2, mr(7, "x" * 80, "7"))]
    menu = render("me", [("🔴", mr(2, "a", "2")), ("🟠", mr(3, "b", "3"))], RED_AFTER, own).splitlines()
    assert menu[0] == "🔴 1 🟠 1 💬 2", menu[0]
    section = menu[menu.index("My merge requests") + 1:]
    assert section[0] == f'🔴 {"x" * 70}… 💬 2 | href=u tooltip="g/p!1 · 2 open threads"', \
        "the thread count follows the cut title: " + section[0]
    assert section[1] == '🟢 approved | href=u tooltip="g/p!1 · 0 open threads"', \
        "no 💬 suffix without open threads: " + section[1]
    assert render("me", [], RED_AFTER, own).splitlines()[0] == "💬 2"
    assert '· 1 open thread"' in render("me", [], RED_AFTER, [("🔴", threads[:1], mr(8, "c", "8"))])
    assert render("me", [], RED_AFTER, own[:1]).splitlines()[0] == "🟢"
    assert "My merge requests" not in render("me", []).splitlines(), "no section without MRs of your own"
    by = lambda i, who: {"id": i, "notes": [{"author": {"username": who}}]}
    news = [("🔴", [by("t1", "bob"), by("t2", "me")], mr(9, "mine", "9")),
            ("🔴", [by("t3", "bob"), by("t4", "ann")], mr(10, "other", "10"))]
    assert thread_news(news, "me", None) == ([], ["t1", "t3", "t4"]), "the first run only remembers the threads"
    assert thread_news(news, "me", ["t1"]) == ([("2 new comments: other", "u")], ["t1", "t3", "t4"])
    assert thread_news(news, "me", ["t3", "t4"]) == ([("New comment: mine", "u")], ["t1", "t3", "t4"]), \
        "your own thread t2 never notifies"
    assert thread_news(news, "me", ["t1", "t3", "t4"])[0] == []
    assert len(thread_news(news, "me", [])[0]) == 2, "an empty list is a run without threads, not a first run"
    assert "Open my merge requests | href=https://gitlab.com/dashboard/merge_requests?author_username=me" in menu
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "sub/people"
        assert listed(path, PEOPLE_TEMPLATE) == [], "a new people file holds only comments"
        path.write_text("alice\n  @bob  # team lead\n\n# carol\n")
        assert listed(path, PEOPLE_TEMPLATE) == ["alice", "bob"], listed(path, PEOPLE_TEMPLATE)
        repos = pathlib.Path(tmp) / "sub/repos"
        assert listed(repos, REPOS_TEMPLATE) == [], "a new repos file holds only comments"
        repos.write_text("grp/sub/proj  # backend\n")
        assert listed(repos, REPOS_TEMPLATE) == ["grp/sub/proj"]
        settings = pathlib.Path(tmp) / "sub/settings.json"
        assert load_red_after(settings) == RED_AFTER, "no settings file means the 1-hour default"
        save_red_after(settings, "30")
        assert load_red_after(settings) == timedelta(minutes=30)
        save_setting(settings, "hide_approved", True)
        assert load_settings(settings) == {"red_after_minutes": 30, "hide_approved": True}, \
            "saving one setting keeps the others: " + settings.read_text()
        settings.write_text("{oops")
        assert load_red_after(settings) == RED_AFTER, "a broken settings file falls back to the default"
        assert load_settings(settings) == {}
    menu = render("me", [], timedelta(minutes=30)).splitlines()
    assert "Red after: 30m" in menu, menu
    assert [l for l in menu if "checked=true" in l] == [next(l for l in menu if l.startswith("--30m"))]
    mixed = [("🟢", mr(1, "done", "1")), ("🟢", mr(2, "done too", "2")), ("🟠", mr(3, "pushed", "3"))]
    shown = render("me", mixed).splitlines()
    assert any(l.startswith("Hide approved by me (2) |") and "param2=on" in l for l in shown), "the label counts what it hides"
    hidden = render("me", mixed, hide_approved=True).splitlines()
    assert hidden[2].startswith("🟠") and hidden[3] == "---", "🟢 is hidden without a line of its own: " + str(hidden[:4])
    assert not any(l.startswith("🟢") for l in hidden[2:]), hidden
    assert any(l.startswith("Show approved by me (2 hidden) |") and "param2=off" in l for l in hidden), hidden
    assert render("me", mixed[:2], hide_approved=True).splitlines()[2] == "Nothing to review"
    with tempfile.TemporaryDirectory() as tmp:
        last = pathlib.Path(tmp) / "last-fetch.json"
        mark_rerender(last)
        assert not last.exists() and rerender(last, True) is None, "without a fetch, a click leaves the fetch to SwiftBar"
        last.write_text(json.dumps({"me": "me", "rows": mixed, "own": [], "red_after_minutes": 60}))
        assert rerender(last, True) is None, "a scheduled run fetches from GitLab"
        mark_rerender(last)
        quick = rerender(last, True).splitlines()
        assert "Show approved by me (2 hidden)" in "\n".join(quick), "a click redraws with the new setting: " + str(quick)
        assert rerender(last, True) is None, "only the run right after the click skips GitLab"
    in_repo = lambda path, i, icon, t: (icon, {**mr(i, t, str(i)), "references": {"full": f"{path}!{i}"}})
    repo = [in_repo("z/second", 22, "🟢", "second done"), in_repo("a/first", 21, "🟢", "first done"),
            in_repo("z/second", 23, "🔴", "second red")]
    with_repos = render("me", [("🟠", mr(3, "b", "3"))], RED_AFTER, (), False, repo, ["gone/proj"]).splitlines()
    assert with_repos[0] == "🟠 1", "repository MRs do not count in the menu bar: " + with_repos[0]
    section = [l.split(" |")[0] for l in with_repos[with_repos.index("Repositories") + 1:]][:6]
    assert section == ["📁 z/second", "🔴 second red", "🟢 second done", "📁 a/first", "🟢 first done",
                       "⚠️ gone/proj: not found"], "grouped in file order, sorted by colour inside: " + str(section)
    assert "📁 z/second | href=https://gitlab.com/z/second/-/merge_requests" in with_repos
    assert 'tooltip="z/second!23 · A"' in with_repos[with_repos.index("📁 z/second | href=https://gitlab.com/z/second/-/merge_requests") + 1]
    hidden_repos = render("me", [], RED_AFTER, (), True, repo).splitlines()
    assert not any("done" in l for l in hidden_repos), "hide approved by me also hides repository MRs"
    assert not any(l.startswith("📁 a/first") for l in hidden_repos), "a repository with only hidden MRs has no header"
    assert any(l.startswith("Show approved by me (2 hidden)") for l in hidden_repos), hidden_repos
    both = render("me", [repo[0]], RED_AFTER, (), True, repo).splitlines()
    assert any(l.startswith("Show approved by me (2 hidden)") for l in both), "an MR in both lists counts once"
    assert "Repositories" not in render("me", []).splitlines(), "no section without repositories"
    plain = render("me", []).splitlines()
    help_lines = plain[plain.index("Help") + 1:plain.index("Refresh | refresh=true")]
    assert all(l.startswith("--") for l in help_lines), "help is one submenu: " + str(help_lines)
    assert all(any(l.startswith("--" + icon) for l in help_lines) for icon in ["🔴", "🟠", "⚪", "🟢", "💬", "📁", "🔒", "⚠️"]), \
        "help explains every icon"
    assert "-----" in help_lines, "--- separators become ----- inside the submenu"
    assert arg("/a b/people") == '"/a b/people"', "a path with a space, such as a Windows user folder, stays one value"
    assert arg("/a/people") == "/a/people"
    assert run_self("--red-after", 15) == f"bash={arg(SELF)} param1=--red-after param2=15"
    assert f"Edit people… | bash={arg(SELF)} param1=--open param2={arg(PEOPLE)} terminal=false" in plain
    assert f"Edit repos… | bash={arg(SELF)} param1=--open param2={arg(REPOS)} terminal=false" in plain
    assert f"⚠️ gone/proj: not found | bash={arg(SELF)} param1=--open param2={arg(REPOS)} terminal=false" in with_repos
    opened, real_open = [], globals()["open_file"]
    globals()["open_file"] = opened.append
    try:
        assert act(["mr-radar.2m.py", "--open", "/p"]) is True and opened == ["/p"], opened
    finally:
        globals()["open_file"] = real_open
    assert act(["mr-radar.2m.py"]) is False, "no menu command means a normal run"

    full = render("me", [("🔴", mr(2, "a|b", "2"))], RED_AFTER, own, False, repo, ["gone/proj"])
    bar, items = parse_menu(full)
    assert bar == ["🔴 1 💬 2"], bar
    flat = []
    walk = lambda nodes: [flat.append(n) or (walk(n["children"]) if n else None) for n in nodes]
    walk(items)
    body = full.splitlines()[2:]
    assert len(flat) == len(body), f"every line after the first --- becomes one item: {len(flat)} vs {len(body)}"
    assert sum(n is None for n in flat) == sum(1 for l in body if l in ("---", "-----")), "separators survive"
    first = items[0]
    assert first["title"] == "🔴 a¦b" and first["params"]["tooltip"] == "g/p!1 · A" and first["params"]["href"] == "u", first
    red = next(n for n in items if n and n["title"].startswith("Red after"))
    assert [c["title"] for c in red["children"]] == list(RED_AFTER_CHOICES), red
    assert [c["params"]["checked"] for c in red["children"]].count("true") == 1
    help_menu = next(n for n in items if n and n["title"] == "Help")
    assert len(help_menu["children"]) == len(HELP) and help_menu["children"][5] is None, "--- in Help is a separator"
    assert all(n is None or not n["title"].startswith("-") for n in flat), "no item keeps a -- prefix"
    windows = parse_menu('x\n---\nEdit people… | bash="C:\\Users\\A B\\mr-radar.exe" param1=--open '
                         'param2="C:\\Users\\A B\\.config\\mr-radar\\people" terminal=false')[1][0]["params"]
    assert windows["bash"] == "C:\\Users\\A B\\mr-radar.exe" and windows["param2"].endswith("A B\\.config\\mr-radar\\people"), \
        "a Windows path with spaces and backslashes survives: " + str(windows)

    def first_action(title):
        return action_for(next(n for n in flat if n and n["title"].startswith(title))["params"])
    assert first_action("🔴 a¦b") == ("url", "u")
    assert first_action("15m") == ("act", [str(SELF), "--red-after", "15"])
    real_self = globals()["SELF"]
    spaced_self = pathlib.Path("/Users/A B/mr-radar.2m.py")  # a Windows user folder often has a space
    globals()["SELF"] = spaced_self
    try:
        spaced = parse_menu(render("me", [], timedelta(minutes=30)))[1]
        red_spaced = next(n for n in spaced if n and n["title"].startswith("Red after"))["children"][1]
        # str(): Windows writes this path with backslashes
        assert action_for(red_spaced["params"]) == ("act", [str(spaced_self), "--red-after", "30"]), \
            "render, parse and action_for round-trip a path with a space: " + str(red_spaced["params"])
    finally:
        globals()["SELF"] = real_self
    assert first_action("Hide approved by me") == ("act", [str(SELF), "--hide-approved", "on"])
    assert first_action("Edit repos") == ("act", [str(SELF), "--open", str(REPOS)])
    assert first_action("Refresh") == ("refresh", None)
    assert first_action("My merge requests") == (None, None), "a section header does nothing"
    login = parse_menu(f"🔒 MR\n---\nLog in… | bash={arg(GLAB)} param1=auth param2=login terminal=true refresh=true")
    assert action_for(login[1][0]["params"]) == ("login", None)

    assert icon_spec("🔴 4 🟠 3 💬 2") == ("#d93025", "7")
    assert icon_spec("🟠 2 💬 3") == ("#f29900", "2")
    assert icon_spec("💬 3") == ("#1e8e3e", ""), "open threads on your own MRs alone do not colour the icon"
    assert icon_spec("🟢") == ("#1e8e3e", "")
    assert icon_spec("🔴 120") == ("#d93025", "99")
    assert icon_spec("🔒 MR") == ("#80868b", "!") and icon_spec("⚠️ MR")[1] == "?"
    if WINDOWS:  # the .exe must bundle the tray libraries, which macOS never imports
        import pystray, PIL, win11toast  # noqa: F401
    print("selftest ok")


def act(args):
    """Runs the menu command in args. Returns False when args hold none."""
    if "--red-after" in args:  # clicked in the "Red after" submenu
        save_red_after(SETTINGS, args[args.index("--red-after") + 1])
    elif "--hide-approved" in args:  # clicked "Hide approved by me"
        save_setting(SETTINGS, "hide_approved", args[args.index("--hide-approved") + 1] == "on")
        mark_rerender(LAST_FETCH)  # SwiftBar's refresh=true then redraws from the last fetch
    elif "--open" in args:  # clicked "Edit people…", "Edit repos…" or a repository that was not found
        open_file(args[args.index("--open") + 1])
    else:
        return False
    return True


PARAM = re.compile(r"""(\w+)=("[^"]*"|'[^']*'|\S+)""")


def parse_menu(text):
    """SwiftBar menu text as (menu bar lines, items) for the Windows tray.
    An item is a dict with title, params and children. A separator is None."""
    lines = text.splitlines()
    split = lines.index("---") if "---" in lines else len(lines)
    items = []
    levels = [items]  # levels[d] is the list that takes items at submenu depth d
    for line in lines[split + 1:]:
        if len(line) >= 3 and not line.strip("-") and len(line) % 2:  # ---, -----, …: a separator
            depth = min((len(line) - 3) // 2, len(levels) - 1)
            levels[depth].append(None)
            del levels[depth + 1:]
            continue
        depth = 0
        while line.startswith("--", depth * 2):
            depth += 1
        depth = min(depth, len(levels) - 1)
        title, _, rest = line[depth * 2:].partition(" | ")
        params = {k: v[1:-1] if v[0] in "\"'" else v for k, v in PARAM.findall(rest)}
        item = {"title": title, "params": params, "children": []}
        levels[depth].append(item)
        del levels[depth + 1:]
        levels.append(item["children"])
    return lines[:split], items


def action_for(params):
    """What a click on a parsed menu item does in the tray: (kind, value), or (None, None)."""
    if "href" in params:
        return "url", params["href"]
    if params.get("bash") == str(SELF):
        return "act", [str(SELF)] + [params[f"param{i}"] for i in range(1, 10) if f"param{i}" in params]
    if params.get("bash") == GLAB and params.get("param1") == "auth":
        return "login", None
    if params.get("refresh") == "true":
        return "refresh", None
    return None, None


def icon_spec(summary):
    """The tray icon for a menu bar line such as 🔴 4 🟠 3 💬 2: (colour, text in the circle)."""
    if summary.startswith("⏳"):
        return "#80868b", ""
    if summary.startswith("🔒"):
        return "#80868b", "!"
    if summary.startswith("⚠️"):
        return "#f9ab00", "?"
    counts = {icon: int(n) for icon, n in re.findall(r"(🔴|🟠) (\d+)", summary)}
    colour = "#d93025" if "🔴" in counts else "#f29900" if "🟠" in counts else "#1e8e3e"
    total = sum(counts.values())
    return colour, str(min(total, 99)) if total else ""


def tray():
    """The Windows system tray: the SwiftBar menu, parsed into a pystray menu, refreshed every 2 minutes."""
    import ctypes
    import threading
    import webbrowser

    import pystray
    from PIL import Image, ImageDraw, ImageFont

    # one tray per user: a second start, e.g. Startup folder plus a double-click, would send every alert twice
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    instance = kernel32.CreateMutexW(None, False, "mr-radar")  # noqa: F841 - held until the process ends
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return

    current = {"text": "⏳ MR\n---\nLoading merge requests…"}
    wake = threading.Event()

    def image(summary):
        colour, label = icon_spec(summary)
        picture = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(picture)
        draw.ellipse((2, 2, 62, 62), fill=colour)
        try:
            font = ImageFont.truetype("arialbd.ttf", 40 if len(label) < 2 else 32)
        except OSError:
            font = ImageFont.load_default(size=36)
        draw.text((32, 33), label, fill="white", font=font, anchor="mm")
        return picture

    def show(text):
        if text == current["text"]:  # rebuilding the menu while it is open can make it vanish
            return
        current["text"] = text
        summary = text.splitlines()[0]
        icon.icon = image(summary)
        icon.title = summary[:127]  # Windows cuts the tray hover text at 127 characters
        icon.update_menu()

    def refresh_loop():
        while True:
            hide_approved = load_settings(SETTINGS).get("hide_approved") is True
            try:
                show(rerender(LAST_FETCH, hide_approved) or fetch(hide_approved))
            except Exception as e:  # keep the tray alive, and show why the refresh failed
                reason = (str(e).splitlines() or [type(e).__name__])[0][:80].replace("|", "¦")
                show(f"⚠️ MR\n---\n{reason}\nRefresh | refresh=true")
            wake.wait(120)
            wake.clear()

    def run(kind, value):
        if kind == "url":
            webbrowser.open(value)
        elif kind == "act":
            act(value)
            wake.set()  # a toggle redraws from the last fetch, "Red after" fetches again
        elif kind == "login":
            login = subprocess.Popen([GLAB, "auth", "login"], creationflags=subprocess.CREATE_NEW_CONSOLE)
            threading.Thread(target=lambda: (login.wait(), wake.set()), daemon=True).start()  # refresh after the login
        elif kind == "refresh":
            wake.set()

    def to_item(node):
        if node is None:
            return pystray.Menu.SEPARATOR
        title = node["title"].replace("&", "&&")  # a single & marks a keyboard shortcut in a Windows menu
        if node["children"]:
            return pystray.MenuItem(title, pystray.Menu(*[to_item(c) for c in node["children"]]))
        kind, value = action_for(node["params"])
        if kind is None:
            return pystray.MenuItem(title, None, enabled=False)
        checked = (lambda _item: True) if node["params"].get("checked") == "true" else None
        return pystray.MenuItem(title, lambda _icon, _item: run(kind, value), checked=checked)

    def items():
        yield from (to_item(node) for node in parse_menu(current["text"])[1])
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Quit MR Radar", lambda icon, _item: icon.stop())

    icon = pystray.Icon("mr-radar", image("⏳"), "MR Radar", pystray.Menu(items))
    icon.run(setup=lambda icon: (setattr(icon, "visible", True),
                                 threading.Thread(target=refresh_loop, daemon=True).start()))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--tray" in sys.argv or getattr(sys, "frozen", False):  # the Windows .exe starts the tray
        tray()
    elif not act(sys.argv):
        main()
