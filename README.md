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
git clone <this repository> ~/mr-radar
```

Open SwiftBar and choose `~/mr-radar` as the plugin folder.

The first notification asks for permission for "Script Editor".
macOS shows notifications from scripts under that app name.

To update, run `git pull` in `~/mr-radar`.

## How it works

The plugin calls the GitLab API through `glab`.
Therefore it uses your existing `glab` login and needs no token of its own.

- The plugin lists open merge requests where you are a reviewer.
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
