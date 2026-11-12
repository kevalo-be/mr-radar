# MR Radar

A macOS menu bar plugin that lists the open GitLab merge requests where you are a reviewer.
It also lists your own open merge requests, with their open comments.
The plugin runs in [SwiftBar](https://github.com/swiftbar/SwiftBar) and refreshes every 2 minutes.
On Windows, MR Radar runs in the system tray. See [Windows](#windows).

| Icon | Meaning |
|---|---|
| 🔴 | You have not approved the merge request, and it is older than the "Red after" time. The default is 1 hour. |
| 🟠 | You approved the merge request, but new commits were pushed after your approval. |
| ⚪ | You have not approved the merge request, but it is younger than the "Red after" time. |
| 🟢 | You approved the merge request, and nothing was pushed since. |
| 🔒 | You are not logged in to GitLab. |
| ⚠️ | GitLab could not be reached. |

The "Help" submenu in the menu lists these icons too.

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

The first notification asks for permission for "SwiftBar".
Allow it, because SwiftBar sends the notifications of MR Radar.
Click a notification to open its merge request.

To update, run `git pull` in `~/swiftbar/mr-radar`.

## Windows

On Windows, MR Radar is a program in the system tray, with the same menu as on macOS.

1. Install `glab` and log in, in PowerShell:

   ```powershell
   winget install GLab.GLab
   glab auth login
   ```

2. Download `mr-radar.exe` from the [latest release](https://github.com/kevalo-be/mr-radar/releases/latest).
3. Start `mr-radar.exe`. Windows SmartScreen may warn that the program is unknown, because the program is not signed. Click "More info", then "Run anyway".

A coloured circle appears in the system tray. Windows may hide it behind the `^` arrow. Drag it onto the taskbar to keep it visible.

| Circle | Meaning |
|---|---|
| Red with a number | The number of 🔴 and 🟠 merge requests, at least one of them 🔴. |
| Orange with a number | The number of 🟠 merge requests. |
| Green | Nothing needs your attention. |
| Grey with `!` | You are not logged in to GitLab. |
| Yellow with `?` | GitLab could not be reached. |

Hover over the circle to see the counts, for example `🔴 2 🟠 1 💬 3`.
Right-click the circle to open the menu.

To start MR Radar when you log in, press Windows+R, type `shell:startup`, and put a shortcut to `mr-radar.exe` in the folder that opens.

The people and repos files are in `C:\Users\<you>\.config\mr-radar`. "Edit people…" and "Edit repos…" open them in Notepad.

Windows differs from macOS in these points:

- Menu items have no tooltip with the project and the author.
- Notifications may show "Python" as the app name, because MR Radar does not register an app name with Windows.
- To update, download the new `mr-radar.exe` and replace the old one. Quit MR Radar first, with "Quit MR Radar" in its menu.

To run from source instead of the `.exe`, install Python 3.12 and run `pip install pystray pillow win11toast`. Then start `pythonw mr-radar.2m.py --tray`.

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

## Follow repositories

MR Radar can also list the open merge requests of GitLab repositories you choose.
Put the repository paths in `~/.config/mr-radar/repos`, one per line.
A path is the part of the repository URL after `gitlab.com/`.

```
# backend repositories
my-group/backend
my-group/sub-group/api
```

The plugin creates this file on its first run.
The menu item "Edit repos…" opens it.

The merge requests appear in the section "Repositories", with the same icons as a merge request you review.
They are grouped per repository under a `📁 <path>` line, in the order of the file. Click that line to open the merge requests of the repository in GitLab.
They are not counted in the menu bar, and they send no notifications.
Therefore a busy repository with many bot merge requests does not flood your menu bar.
A merge request you review, or one of a followed person, also shows under its repository. It counts and notifies only in the main list.
Uncheck "Also show reviews under repositories" to show such a merge request only in the main list.
"Hide approved by me" also hides the 🟢 merge requests in this section.
A path that GitLab does not know shows `⚠️ <path>: not found`.

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

## Hide approved by me

The menu item "Hide approved by me" hides the 🟢 merge requests: you approved them, and nothing was pushed since.
The item shows how many merge requests it hides, for example `Hide approved by me (3)`.
While they are hidden, the item reads `Show approved by me (3 hidden)`.
Click it to show them again.
🟠 merge requests stay visible, because they have new commits to look at.
"My merge requests" is not affected.
The plugin saves the choice in `~/.config/mr-radar/settings.json`.

## How it works

The plugin calls the GitLab API through `glab`.
Therefore it uses your existing `glab` login and needs no token of its own.

- The plugin lists open merge requests where you are a reviewer, the open merge requests of the people and repositories you follow, and your own open merge requests.
- Your own merge requests appear only in "My merge requests", also when you are their reviewer.
- For each merge request, it reads the approvals.
- If you approved, it compares your approval time with the time of the last push.
- For each of your own merge requests, it reads the threads, and the approvals when no thread is open.

The plugin keeps the merge requests and threads it already notified about in `~/Library/Caches/mr-radar.json`.
It keeps the result of the last GitLab fetch in `~/Library/Caches/mr-radar-last-fetch.json`.
A click on "Hide approved by me" redraws the menu from that file, so the menu updates immediately.

## Limitations

- The plugin works with gitlab.com only.
- Some projects remove approvals when new commits are pushed. In those projects, a merge request with new commits shows 🔴 instead of 🟠.
- The "Red after" time counts from the creation of the merge request. A draft that was marked ready after a day turns 🔴 immediately.
- Projects without approval rules count a merge request as approved right away. Your merge request in such a project turns 🟢 as soon as its threads are resolved. This happens even when nobody reviewed it.
- Only the first 100 threads of a merge request are counted.
- Only the first 100 open merge requests of a followed repository are listed.
- When you mark your own draft as ready, its existing threads notify you as new.

## Test

```sh
./mr-radar.2m.py --selftest
```

## Release the Windows program

GitHub Actions builds `mr-radar.exe` on Windows. The workflow is `.github/workflows/windows-exe.yml`.
Push a tag that starts with `v` to publish a release with the program:

```sh
git tag v1.0.0
git push origin v1.0.0
```

The workflow runs the self-test, builds the program, runs the self-test again inside the program, and attaches `mr-radar.exe` to the release.
You can also start the workflow by hand on the Actions tab. That run keeps the program as a download on the run page, without a release.
