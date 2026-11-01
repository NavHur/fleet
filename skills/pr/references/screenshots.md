# Screenshots

Before and after images for a PR whose diff changes what a user sees. Images live on the repo's `pr-assets` branch, one folder per PR branch, so they stay out of the PR's diff and size.

## 1. Capture

Shoot the same pages and states twice: **before** from the base, **after** from the head.

Work in a folder of your own: other agents on the host capture too, and `pr-assets` uploads everything in the folders it is given.

```sh
shots_dir=$(mktemp -d) && mkdir "$shots_dir/before" "$shots_dir/after"
```

- **Web app**: serve the head's production build the way `~/.config/host-validation.md` says for this machine (on devbox, `preview-worktree start` in the PR's worktree, which prints the port), or with the project's run skill, and capture with T3's preview tools. They drive a headless browser on this machine, so they reach its `127.0.0.1` and need no one at the T3 app:
  1. `preview_open` the page with `open=false` and `reuseExistingTab=false`; keep the returned `tabId` for every later call. For a fresh session, pass `profileId: "incognito"`; for one that is already signed in, pass that profile's id from the list `preview_open` and `preview_status` return.
  2. Sign in when the app needs it. With a cookie, such as the `Cookie:` line a preview's `signin` command prints, open the app's origin first, set it with `preview_evaluate` (`document.cookie = "NAME=VALUE; Path=/; Secure; SameSite=Lax"`; `Secure` works on `127.0.0.1` and `localhost`), then `preview_navigate` to the page.
  3. Size the tab with `preview_resize` (`freeform`): desktop 1440×900, then phone 390×844 when the layout changes at that width.
  4. Reach the changed state: `preview_act` clicks, types, or scrolls (dismiss notices, open collapsed sections), targeting a CSS `selector` such as `summary`, or `locator='aria-ref=<ref>'` from a `preview_snapshot`; `preview_wait_for` confirms the state, such as `details[open]`. A navigation resets the page, so redo this step after each one; a resize keeps it.
  5. `preview_snapshot` with `save=true` writes a PNG and returns its `screenshotPath`. Copy it into `$shots_dir/after` under a name that says what it shows, such as `settings-desktop.png`. Images may come out at 2x, or scaled down to 1280 wide for a wider tab; both are fine.
  6. `t3_preview_close` the tab when done.
- **Before**: repeat against a deployed build of the base (production or its preview URL) when one exists. Otherwise add a worktree at the base (`git worktree add --detach "$shots_dir/base" origin/<base>`), serve it the same way (on devbox, `preview-worktree start "$shots_dir/base"`, which gives it its own port), capture into `$shots_dir/before` under the same names, then stop it (`preview-worktree stop "$shots_dir/base"`) and `git worktree remove --force "$shots_dir/base"`.
- **Anything else** (Godot, native, mobile): use the project's own capture route: a capture script or skill in the repo, or T3's `device_screenshot`.
- **New UI with no before**: capture the after only and say so.

Open each image and keep the ones that show the changed region. Recapture after scrolling, a taller `preview_resize`, or another `preview_act` when the change sits below the fold or behind a dialog.

## 2. Host

From the PR's checkout, push the folders with `pr-assets`, which prints one embed link per image:

```sh
pr-assets "$shots_dir/before" "$shots_dir/after" && rm -rf "$shots_dir"
```

It writes `<branch>/before/` and `<branch>/after/` on origin's `pr-assets` branch, creating the branch when the repo has none, without touching the PR branch or the working tree. Re-running for the same branch replaces its folders; images already embedded in older PR bodies keep pointing at the same path. Pass `--branch <name>` from a detached HEAD. Push follows the branch rule in Pedro's Git instructions: a `pr-assets` branch he or his agents created pushes without asking; one a coworker created needs his say first.

Host images nowhere else: not in a gist, not on a branch named `pr-assets/<x>` (GitHub refuses one next to `pr-assets`), not through the contents API.

## 3. Embed

Embed the links `pr-assets` printed. They go through `blob/…?raw=true`, which renders in private repos for anyone who can read the repo; `raw.githubusercontent.com` renders only in public ones, so never rewrite them to it:

```markdown
- **Before:** ![settings, desktop, before](https://github.com/<owner>/<repo>/blob/pr-assets/<branch>/before/settings-desktop.png?raw=true)
  **After:** ![settings, desktop, after](https://github.com/<owner>/<repo>/blob/pr-assets/<branch>/after/settings-desktop.png?raw=true)
```

Pair each before with its after on adjacent lines, desktop first, and add the phone pair when the layout changes at that width. Embed only links `pr-assets` printed: it exits non-zero unless the push landed, so a printed link exists.
