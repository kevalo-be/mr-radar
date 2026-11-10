# MR Radar

A macOS menu bar plugin that lists the open GitLab merge requests where you are a reviewer.
It also lists your own open merge requests, with their open comments.
The plugin runs in [SwiftBar](https://github.com/swiftbar/SwiftBar) and refreshes every 2 minutes.

| Icon | Meaning |
|---|---|
| 🔴 | You have not approved the merge request, and it is older than the "Red after" time. The default is 1 hour. |
| 🟠 | You approved the merge request, but new commits were pushed after your approval. |
| ⚪ | You have not approved the merge request, but it is younger than the "Red after" time. |
| 🟢 | You approved the merge request, and nothing was pushed since. |
| 🔒 | You are not logged in to GitLab. |
| ⚠️ | GitLab could not be reached. |

The menu bar shows the number of 🔴 and 🟠 merge requests you review or follow, for example `🔴 2 🟠 1`.
It adds `💬 3` when your own merge requests have 3 open comments. See [My merge requests](#my-merge-requests).
It shows `🟢` when nothing needs your attention.
Draft merge requests are not listed.
Click a merge request to open it in the browser.

You get a macOS notification when a merge request you review or follow turns 🔴 or 🟠.
You also get one notification when you are logged out.

## Install

```sh
brew install glab
brew install --cask swiftbar
glab auth login
git clone https://github.com/kevalo-be/mr-radar.git ~/swiftbar/mr-radar
```

Open SwiftBar and choose `~/swiftbar` as the plugin folder.
SwiftBar also runs plugins in subfolders, so other plugins can sit next to `mr-radar`.
If you already have a plugin folder, clone into that folder instead.
Restart SwiftBar after the clone, because SwiftBar finds a new subfolder only at startup.

The first notification asks for permission for "Script Editor".
macOS shows notifications from scripts under that app name.

To update, run `git pull` in `~/swiftbar/mr-radar`.

## Follow people

MR Radar can also show the open merge requests of people you choose, such as your team.
Put their GitLab usernames in `~/.config/mr-radar/people`, one per line.
A `#` starts a comment.

```
# my team
jdoe
asmith
```

The plugin creates this file on its first run.
The menu item "Edit people…" opens it.
Each user has their own file, so every team keeps its own list.

A merge request of a followed person gets the same icons and notifications as a merge request you review.

## My merge requests

The section "My merge requests" lists your own open merge requests.
An open comment is an unresolved thread, like the "unresolved threads" badge in GitLab.
A merge request with open comments shows their number, for example `💬 2`.

| Icon | Meaning |
|---|---|
| 🔴 | The merge request has open comments. |
| 🟠 | The merge request has no open comments, but it still needs approvals. |
| 🟢 | The merge request has no open comments, and it is approved. |

Your draft merge requests are not listed.
The section is hidden when nothing is left to list.
The menu item "Open my merge requests" opens the GitLab dashboard with your own merge requests.

You get a macOS notification when someone opens a new thread on one of your merge requests.
Threads you open yourself count as open comments, but they do not notify you.

## Red after

The "Red after" submenu sets how old an unapproved merge request must be before it turns 🔴.
The choices are 15m, 30m, 1h, 2h and 4h. The default is 1h.
The plugin saves your choice in `~/.config/mr-radar/settings.json`.

## How it works

The plugin calls the GitLab API through `glab`.
Therefore it uses your existing `glab` login and needs no token of its own.

- The plugin lists open merge requests where you are a reviewer, the open merge requests of the people you follow, and your own open merge requests.
- Your own merge requests appear only in "My merge requests", also when you are their reviewer.
- For each merge request, it reads the approvals.
- If you approved, it compares your approval time with the time of the last push.
- For each of your own merge requests, it reads the threads, and the approvals when no thread is open.

The plugin keeps the merge requests and threads it already notified about in `~/Library/Caches/mr-radar.json`.

## Limitations

- The plugin works with gitlab.com only.
- Some projects remove approvals when new commits are pushed. In those projects, a merge request with new commits shows 🔴 instead of 🟠.
- The "Red after" time counts from the creation of the merge request. A draft that was marked ready after a day turns 🔴 immediately.
- Projects without approval rules count a merge request as approved right away. Your merge request in such a project turns 🟢 as soon as its threads are resolved. This happens even when nobody reviewed it.
- Only the first 100 threads of a merge request are counted.
- When you mark your own draft as ready, its existing threads notify you as new.

## Test

```sh
./mr-radar.2m.py --selftest
```
