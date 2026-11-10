#!/usr/bin/env python3
# <xbar.title>MR Radar</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.author>Kevin Van Loo</xbar.author>
# <xbar.author.github>kevalo-be</xbar.author.github>
# <xbar.desc>Lists the open GitLab merge requests you review, follow or author, with notifications.</xbar.desc>
# <xbar.dependencies>python3,glab</xbar.dependencies>
# <xbar.abouturl>https://github.com/kevalo-be/mr-radar</xbar.abouturl>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

# SwiftBar runs plugins without Homebrew on the PATH: Apple Silicon, then Intel.
GLAB = shutil.which("glab", path="/opt/homebrew/bin:/usr/local/bin") or "glab"
STATE = pathlib.Path.home() / "Library/Caches/mr-radar.json"
LAST_FETCH = pathlib.Path.home() / "Library/Caches/mr-radar-last-fetch.json"  # redraws a toggle click without GitLab
PEOPLE = pathlib.Path.home() / ".config/mr-radar/people"
PEOPLE_TEMPLATE = """\
# MR Radar shows the open merge requests of the GitLab users below.
# Write one username per line. A # starts a comment.
# jdoe
"""
DASHBOARD = "https://gitlab.com/dashboard/merge_requests?reviewer_username={}"
MY_DASHBOARD = "https://gitlab.com/dashboard/merge_requests?author_username={}"
SETTINGS = pathlib.Path.home() / ".config/mr-radar/settings.json"
ORDER = {"🔴": 0, "🟠": 1, "⚪": 2, "🟢": 3}
RED_AFTER = timedelta(hours=1)
RED_AFTER_CHOICES = {"15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240}  # label: minutes


class NotLoggedIn(Exception):
    pass


def api(path, attempts=3):
    r = subprocess.run([GLAB, "api", path], capture_output=True, text=True)
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


def people(path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PEOPLE_TEMPLATE)
    names = (line.split("#")[0].strip().lstrip("@") for line in path.read_text().splitlines())
    return [n for n in names if n]


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


def render(me, rows, red_after=RED_AFTER, own=(), hide_approved=False):
    """rows: list of (icon, mr), own: list of (icon, open threads, mr). Returns SwiftBar output."""
    rows = sorted(rows, key=lambda r: (ORDER[r[0]], r[1]["updated_at"]))
    approved = sum(1 for icon, _ in rows if icon == "🟢")
    toggle = (f"bash={pathlib.Path(__file__).resolve()} param1=--hide-approved "
              f"param2={'off' if hide_approved else 'on'} terminal=false refresh=true")
    if hide_approved:
        rows = [r for r in rows if r[0] != "🟢"]
    own = sorted(own, key=lambda r: (ORDER[r[0]], r[2]["updated_at"]))
    count = {c: sum(1 for icon, _ in rows if icon == c) for c in ORDER}
    count["💬"] = sum(len(threads) for _, threads, _ in own)
    lines = [" ".join(f"{c} {count[c]}" for c in ("🔴", "🟠", "💬") if count[c]) or "🟢", "---"]
    for icon, mr in rows:
        lines.append(f"{icon} {short(mr['title'])} | href={mr['web_url']} "
                     + tip(f"{mr['references']['full']} · {mr['author']['name']}"))
    if not rows:
        lines.append("Nothing to review")
    if own:
        lines += ["---", "My merge requests"]
    for icon, threads, mr in own:
        n = len(threads)
        suffix = f" 💬 {n}" if n else ""
        lines.append(f"{icon} {short(mr['title'])}{suffix} | href={mr['web_url']} "
                     + tip(f"{mr['references']['full']} · {n} open thread{'' if n == 1 else 's'}"))
    lines += ["---", f"Open GitLab dashboard | href={DASHBOARD.format(me)}",
              f"Open my merge requests | href={MY_DASHBOARD.format(me)}",
              f"Edit people… | bash=/usr/bin/open param1=-t param2={PEOPLE} terminal=false",
              (f"Show approved by me ({approved} hidden)" if hide_approved else f"Hide approved by me ({approved})") + f" | {toggle}"]
    minutes = red_after // timedelta(minutes=1)
    label = next((l for l, m in RED_AFTER_CHOICES.items() if m == minutes), f"{minutes}m")
    lines.append(f"Red after: {label}")
    for l, m in RED_AFTER_CHOICES.items():
        lines.append(f"--{l} | bash={pathlib.Path(__file__).resolve()} param1=--red-after param2={m} "
                     f"terminal=false refresh=true checked={str(m == minutes).lower()}")
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
    return render(data["me"], data["rows"], timedelta(minutes=data["red_after_minutes"]), data["own"], hide_approved)


def main():
    hide_approved = load_settings(SETTINGS).get("hide_approved") is True
    menu = rerender(LAST_FETCH, hide_approved)
    if menu:
        print(menu)
        return
    state = json.loads(STATE.read_text()) if STATE.exists() else {"seen": [], "logged_in": True}
    try:
        me = api("user")["username"]
        filters = [f"reviewer_username={me}"] + [f"author_username={quote(p)}" for p in people(PEOPLE) if p != me]
        with ThreadPoolExecutor(4) as pool:
            pages = list(pool.map(lambda f: api(f"merge_requests?scope=all&state=opened&{f}&per_page=100"),
                                  filters + [f"author_username={me}"]))
            # an MR by a followed person can also have you as reviewer: keep it once
            found = {m["id"]: m for page in pages[:-1] for m in page if m["author"]["username"] != me}
            mrs = [m for m in found.values() if not m["draft"]]
            own = [m for m in pages[-1] if not m["draft"]]
            red_after = load_red_after(SETTINGS)
            rows = list(zip(pool.map(lambda m: colour(m, me, red_after), mrs), mrs))
            own_rows = [(icon, threads, m) for (icon, threads), m in zip(pool.map(mine, own), own)]
    except NotLoggedIn:
        print(f"🔒 MR\n---\nNot logged in to GitLab\nLog in… | bash={GLAB} param1=auth param2=login "
              "terminal=true refresh=true")
        if state["logged_in"]:
            notify("Not logged in to GitLab")
        STATE.write_text(json.dumps({**state, "logged_in": False}))
        return
    except Exception as e:  # offline, GitLab down: show it, keep the state for the next run
        print(f"⚠️ MR\n---\n{str(e).splitlines()[0][:80]}\nRefresh | refresh=true")
        return

    print(render(me, rows, red_after, own_rows, hide_approved))
    LAST_FETCH.write_text(json.dumps({"me": me, "rows": rows, "own": own_rows,
                                      "red_after_minutes": red_after // timedelta(minutes=1)}))
    todo = {f"{mr['id']}{icon}": (icon, mr) for icon, mr in rows if icon in ("🔴", "🟠")}
    for key in todo.keys() - set(state["seen"]):
        icon, mr = todo[key]
        notify(f"{'Review' if icon == '🔴' else 'New commits'}: {mr['title']}", mr["web_url"])
    texts, thread_ids = thread_news(own_rows, me, state.get("threads"))
    for text, href in texts:
        notify(text, href)
    STATE.write_text(json.dumps({"seen": list(todo), "threads": thread_ids, "logged_in": True}))


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
    assert "My merge requests" not in render("me", []), "no section without MRs of your own"
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
        assert people(path) == [], "a new people file holds only comments"
        path.write_text("alice\n  @bob  # team lead\n\n# carol\n")
        assert people(path) == ["alice", "bob"], people(path)
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
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--red-after" in sys.argv:  # clicked in the "Red after" submenu
        save_red_after(SETTINGS, sys.argv[sys.argv.index("--red-after") + 1])
    elif "--hide-approved" in sys.argv:  # clicked "Hide approved by me"
        save_setting(SETTINGS, "hide_approved", sys.argv[sys.argv.index("--hide-approved") + 1] == "on")
        mark_rerender(LAST_FETCH)  # SwiftBar's refresh=true then redraws from the last fetch
    else:
        main()
