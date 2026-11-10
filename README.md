# MR Radar

A macOS menu bar plugin that lists the open GitLab merge requests where you are a reviewer.
The plugin runs in [SwiftBar](https://github.com/swiftbar/SwiftBar) and refreshes every 2 minutes.

| Icon | Meaning |
|---|---|
| 🔴 | You have not approved the merge request, and it is older than 1 hour. |
| 🟠 | You approved the merge request, but new commits were pushed after your approval. |
| ⚪ | You have not approved the merge request, but it is younger than 1 hour. |
| 🟢 | You approved the merge request, and nothing was pushed since. |
| 🔒 | You are not logged in to GitLab. |
| ⚠️ | GitLab could not be reached. |

The menu bar shows the number of 🔴 and 🟠 merge requests, for example `🔴 2 🟠 1`.
It shows `🟢` when nothing needs your attention.
Draft merge requests are not listed.
Click a merge request to open it in the browser.

You get a macOS notification when a merge request turns 🔴 or 🟠.
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

## How it works

The plugin calls the GitLab API through `glab`.
Therefore it uses your existing `glab` login and needs no token of its own.

- The plugin lists open merge requests where you are a reviewer, plus the open merge requests of the people you follow.
- For each merge request, it reads the approvals.
- If you approved, it compares your approval time with the time of the last push.

The plugin keeps the merge requests it already notified about in `~/Library/Caches/mr-radar.json`.

## Limitations

- The plugin works with gitlab.com only.
- Some projects remove approvals when new commits are pushed. In those projects, a merge request with new commits shows 🔴 instead of 🟠.
- The 1-hour rule counts from the creation of the merge request. A draft that was marked ready after a day turns 🔴 immediately.

## Test

```sh
./mr-radar.2m.py --selftest
```
