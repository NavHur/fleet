# Screenshots

Before and after images for a PR whose diff changes what a user sees. Images live on the repo's `pr-assets` branch, one folder per PR branch, so they stay out of the PR's diff and size.

## 1. Capture

Shoot the same pages and states twice: **before** from the base, **after** from the head.

- **Web app**: run it (the project's dev or preview command, or its run skill) and capture with `shots`, which writes desktop and phone JPEGs (`shots --help` for sign-in, waits, and clicks):

  ```sh
  shots --out /tmp/pr-shots/after --base-url http://localhost:5173 /settings /settings/billing
  ```

- **Before**: point `shots` at a deployed build of the base (production or its preview URL) when one exists. Otherwise add a worktree at the base (`git worktree add --detach /tmp/pr-base origin/<base>`), run it on another port, capture into `/tmp/pr-shots/before`, then `git worktree remove /tmp/pr-base`.
- **Anything else** (Godot, native, mobile): use the project's own capture route: a capture script or skill in the repo, or T3's preview and `device_screenshot` tools.
- **New UI with no before**: capture the after only and say so.

Open each image and keep the ones that show the changed region. Crop or recapture with `--wait-for` or `--click` when the change sits below the fold or behind a dialog.

## 2. Host

Commit the images to `pr-assets` from a throwaway worktree, leaving the PR branch untouched. Push follows the owner rule in Pedro's Git instructions: a `PedroNavHur` repo pushes without asking; for any other owner, ask Pedro before the push.

```sh
branch=$(git branch --show-current)
assets=$(mktemp -d)/assets
if git ls-remote --exit-code origin pr-assets >/dev/null; then
  git fetch origin pr-assets && git worktree add --detach "$assets" FETCH_HEAD
else
  git worktree add --detach "$assets" && git -C "$assets" checkout --orphan pr-assets && git -C "$assets" rm -rfq .
fi
mkdir -p "$assets/$branch" && cp -R /tmp/pr-shots/before /tmp/pr-shots/after "$assets/$branch/"
git -C "$assets" add -A && git -C "$assets" commit -m "chore(pr-assets): screenshots for $branch"
git -C "$assets" push origin HEAD:pr-assets
git worktree remove --force "$assets"
```

Re-running for the same branch overwrites its folder; images already embedded in older PR bodies keep pointing at the same path.

## 3. Embed

Link each image through `blob/…?raw=true`, which renders in private repos for anyone who can read the repo (`raw.githubusercontent.com` renders only in public ones):

```markdown
- **Before:** ![settings, desktop, before](https://github.com/<owner>/<repo>/blob/pr-assets/<branch>/before/settings-desktop.jpg?raw=true)
  **After:** ![settings, desktop, after](https://github.com/<owner>/<repo>/blob/pr-assets/<branch>/after/settings-desktop.jpg?raw=true)
```

Pair each before with its after on adjacent lines, desktop first, and add the phone pair when the layout changes at that width. Before publishing the body, confirm each embedded path exists: `gh api "repos/<owner>/<repo>/contents/<branch>/after/settings-desktop.jpg?ref=pr-assets" --jq .size`.
