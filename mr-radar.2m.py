#!/usr/bin/env python3
# <xbar.title>MR Radar</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.author>Kevin Van Loo</xbar.author>
# <xbar.author.github>kevalo-be</xbar.author.github>
# <xbar.desc>Lists the open GitLab merge requests you review or follow, with notifications.</xbar.desc>
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
from urllib.parse import quote

# SwiftBar runs plugins without Homebrew on the PATH: Apple Silicon, then Intel.
GLAB = shutil.which("glab", path="/opt/homebrew/bin:/usr/local/bin") or "glab"
STATE = pathlib.Path.home() / "Library/Caches/mr-radar.json"
PEOPLE = pathlib.Path.home() / ".config/mr-radar/people"
PEOPLE_TEMPLATE = """\
# MR Radar shows the open merge requests of the GitLab users below.
# Write one username per line. A # starts a comment.
# jdoe
"""
DASHBOARD = "https://gitlab.com/dashboard/merge_requests?reviewer_username={}"
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


def people(path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PEOPLE_TEMPLATE)
    names = (line.split("#")[0].strip().lstrip("@") for line in path.read_text().splitlines())
    return [n for n in names if n]


def load_red_after(path):
    try:
        return timedelta(minutes=json.loads(path.read_text())["red_after_minutes"])
    except (FileNotFoundError, ValueError, KeyError, TypeError):  # missing or hand-edited badly
        return RED_AFTER


def save_red_after(path, minutes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"red_after_minutes": int(minutes)}))


def is_older(gitlab_time, age, now=None):
    # Python 3.9 (macOS /usr/bin/python3) cannot parse the trailing Z
    created = datetime.fromisoformat(gitlab_time.replace("Z", "+00:00"))
    return (now or datetime.now(timezone.utc)) - created > age


def render(me, rows, red_after=RED_AFTER):
    """rows: list of (icon, mr). Returns SwiftBar output."""
    rows = sorted(rows, key=lambda r: (ORDER[r[0]], r[1]["updated_at"]))
    count = {c: sum(1 for icon, _ in rows if icon == c) for c in ORDER}
    lines = [" ".join(f"{c} {count[c]}" for c in ("🔴", "🟠") if count[c]) or "🟢", "---"]
    for icon, mr in rows:
        title = mr["title"].replace("|", "¦")
        if len(title) > 70:  # truncate here: SwiftBar's length= adds a hover tooltip with the full title
            title = title[:70] + "…"
        lines.append(f"{icon} {title} | href={mr['web_url']}")
        lines.append(f"--{mr['references']['full']} · {mr['author']['name']} | href={mr['web_url']}")
    if not rows:
        lines.append("Nothing to review")
    lines += ["---", f"Open GitLab dashboard | href={DASHBOARD.format(me)}",
              f"Edit people… | bash=/usr/bin/open param1=-t param2={PEOPLE} terminal=false"]
    minutes = red_after // timedelta(minutes=1)
    label = next((l for l, m in RED_AFTER_CHOICES.items() if m == minutes), f"{minutes}m")
    lines.append(f"Red after: {label}")
    for l, m in RED_AFTER_CHOICES.items():
        lines.append(f"--{l} | bash={pathlib.Path(__file__).resolve()} param1=--red-after param2={m} "
                     f"terminal=false refresh=true checked={str(m == minutes).lower()}")
    lines.append("Refresh | refresh=true")
    return "\n".join(lines)


def notify(text):
    subprocess.run(["osascript", "-e",
                    f'display notification {json.dumps(text, ensure_ascii=False)} with title "MR Radar"'])


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {"seen": [], "logged_in": True}
    try:
        me = api("user")["username"]
        filters = [f"reviewer_username={me}"] + [f"author_username={quote(p)}" for p in people(PEOPLE) if p != me]
        with ThreadPoolExecutor(4) as pool:
            found = [m for page in pool.map(
                lambda f: api(f"merge_requests?scope=all&state=opened&{f}&per_page=100"), filters) for m in page]
            # an MR by a followed person can also have you as reviewer: keep it once
            mrs = [m for m in {m["id"]: m for m in found}.values() if not m["draft"]]
            red_after = load_red_after(SETTINGS)
            rows = list(zip(pool.map(lambda m: colour(m, me, red_after), mrs), mrs))
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

    print(render(me, rows, red_after))
    todo = {f"{mr['id']}{icon}": (icon, mr["title"]) for icon, mr in rows if icon in ("🔴", "🟠")}
    for key in todo.keys() - set(state["seen"]):
        icon, title = todo[key]
        notify(f"{'Review' if icon == '🔴' else 'New commits'}: {title}")
    STATE.write_text(json.dumps({"seen": list(todo), "logged_in": True}))


def selftest():
    mr = lambda i, t, u: {"id": i, "title": t, "updated_at": u, "web_url": "u",
                          "references": {"full": "g/p!1"}, "author": {"name": "A"}}
    out = render("me", [("🟢", mr(1, "done", "1")), ("⚪", mr(4, "fresh", "4")),
                        ("🔴", mr(2, "a|b", "2")), ("🟠", mr(3, "pushed", "3"))])
    lines = out.splitlines()
    assert lines[0] == "🔴 1 🟠 1", "fresh MRs must not count in the menu bar: " + lines[0]
    assert [l[0] for l in lines[2:9:2]] == ["🔴", "🟠", "⚪", "🟢"], lines
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    assert is_older("2026-11-09T10:59:00.000Z", RED_AFTER, now)
    assert not is_older("2026-11-09T11:30:00.000Z", RED_AFTER, now)
    assert "a¦b |" in lines[2], "a pipe in a title must not break the SwiftBar line"
    long = render("me", [("🔴", mr(5, "x" * 80, "5"))]).splitlines()[2]
    assert long == f"🔴 {'x' * 70}… | href=u", "a long title is cut without a hover tooltip: " + long
    assert render("me", []).splitlines()[0] == "🟢"
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "sub/people"
        assert people(path) == [], "a new people file holds only comments"
        path.write_text("alice\n  @bob  # team lead\n\n# carol\n")
        assert people(path) == ["alice", "bob"], people(path)
        settings = pathlib.Path(tmp) / "sub/settings.json"
        assert load_red_after(settings) == RED_AFTER, "no settings file means the 1-hour default"
        save_red_after(settings, "30")
        assert load_red_after(settings) == timedelta(minutes=30)
        settings.write_text("{oops")
        assert load_red_after(settings) == RED_AFTER, "a broken settings file falls back to the default"
    menu = render("me", [], timedelta(minutes=30)).splitlines()
    assert "Red after: 30m" in menu, menu
    assert [l for l in menu if "checked=true" in l] == [next(l for l in menu if l.startswith("--30m"))]
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--red-after" in sys.argv:  # clicked in the "Red after" submenu
        save_red_after(SETTINGS, sys.argv[sys.argv.index("--red-after") + 1])
    else:
        main()
