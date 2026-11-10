#!/usr/bin/env python3
# <swiftbar.title>MR Radar</swiftbar.title>
# <swiftbar.desc>Open GitLab merge requests where you are a reviewer.</swiftbar.desc>
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
ORDER = {"🔴": 0, "🟠": 1, "⚪": 2, "🟢": 3}
RED_AFTER = timedelta(hours=1)


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


def colour(mr, me):
    base = f"projects/{mr['project_id']}/merge_requests/{mr['iid']}"
    approved_at = next((a["approved_at"] for a in api(f"{base}/approvals")["approved_by"]
                        if a["user"]["username"] == me), None)
    if not approved_at:
        return "🔴" if is_older(mr["created_at"], RED_AFTER) else "⚪"
    last_push = max(v["created_at"] for v in api(f"{base}/versions"))
    return "🟠" if last_push > approved_at else "🟢"


def people(path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PEOPLE_TEMPLATE)
    names = (line.split("#")[0].strip().lstrip("@") for line in path.read_text().splitlines())
    return [n for n in names if n]


def is_older(gitlab_time, age, now=None):
    # Python 3.9 (macOS /usr/bin/python3) cannot parse the trailing Z
    created = datetime.fromisoformat(gitlab_time.replace("Z", "+00:00"))
    return (now or datetime.now(timezone.utc)) - created > age


def render(me, rows):
    """rows: list of (icon, mr). Returns SwiftBar output."""
    rows = sorted(rows, key=lambda r: (ORDER[r[0]], r[1]["updated_at"]))
    count = {c: sum(1 for icon, _ in rows if icon == c) for c in ORDER}
    lines = [" ".join(f"{c} {count[c]}" for c in ("🔴", "🟠") if count[c]) or "🟢", "---"]
    for icon, mr in rows:
        title = mr["title"].replace("|", "¦")
        lines.append(f"{icon} {title} | href={mr['web_url']} length=70")
        lines.append(f"--{mr['references']['full']} · {mr['author']['name']} | href={mr['web_url']}")
    if not rows:
        lines.append("Nothing to review")
    lines += ["---", f"Open GitLab dashboard | href={DASHBOARD.format(me)}",
              f"Edit people… | bash=/usr/bin/open param1=-t param2={PEOPLE} terminal=false",
              "Refresh | refresh=true"]
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
            rows = list(zip(pool.map(lambda m: colour(m, me), mrs), mrs))
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

    print(render(me, rows))
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
    assert render("me", []).splitlines()[0] == "🟢"
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "sub/people"
        assert people(path) == [], "a new people file holds only comments"
        path.write_text("alice\n  @bob  # team lead\n\n# carol\n")
        assert people(path) == ["alice", "bob"], people(path)
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
