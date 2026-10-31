# Deployment

Production runs `main` on the production machine.
Steps 1-3 run in your own clone of the repository; step 4 is done by the production machine's owner.

## 1. Create a feature branch

```bash
git fetch origin
git switch -c feat/<name> origin/main
```

## 2. Commit and push

```bash
git add <files>
git commit
git push -u origin feat/<name>
```

## 3. Merge into main

Open a pull request from `feat/<name>` into `main` on GitHub, review it, and merge it.

## 4. Deploy (on the production machine)

In the production worktree:

```bash
git pull
uv sync
```

If the change touches `schedule()` in `apps/data/pipeline.py`, also run:

```bash
.venv/bin/python apps/data/pipeline.py schedule
```

## 5. Delete the merged branch

```bash
git switch -c feat/<next-task> origin/main
git branch -d feat/<name>
git push origin --delete feat/<name>
```
