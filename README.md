# trash30

A trash folder for files you are not sure about. Things you put in stay for 30
days, then a purge removes them. Standard library only, one file of code.

```
pip install git+https://github.com/decentralizeallengineering/trash30
```

## 30-second tour

```
$ trash30 put ~/notes/old-draft.md "maybe needed for the report"
/home/you/notes/old-draft.md -> /home/you/.trash30/2026-11-13/home/you/notes/old-draft.md
$ trash30 list
date        purge       size  original                       why
2026-11-13  2026-12-14  1204  /home/you/notes/old-draft.md   maybe needed for the report
$ trash30 restore ~/notes/old-draft.md
/home/you/.trash30/2026-11-13/home/you/notes/old-draft.md -> /home/you/notes/old-draft.md
$ trash30 purge --dry-run      # prints what a purge would remove; run purge daily from cron or a timer
```

## Why not `rm` or a desktop trash

- A put is one `rename` into `<root>/<date>/<original absolute path>`. No copy, so it is
  instant and keeps permissions. Same filesystem only; otherwise it refuses.
- `purge` judges age by the date in the folder name, never by file mtime, so old files
  moved in today are kept for 30 days.
- `purge` cannot follow a link out of the trash. A link inside an old folder is
  unlinked, not entered. A date folder that is itself a link is unlinked. If the trash
  root is a link, or belongs to another user, purge refuses to run.
- `--never PATTERN` marks paths that must never go in (a path, a prefix or a glob).
  `put` refuses such a path, anything under it, and any folder that holds one.
- Folders left read-only (test runs do this) are opened for you so the purge finishes.

## Options

| option | environment | default |
|---|---|---|
| `--root DIR` | `TRASH30_ROOT` | `~/.trash30` |
| `--days N` | `TRASH30_DAYS` | `30` |
| `--never PATTERN` (repeat) | `TRASH30_NEVER` (separated by `:`) | none |
| `--log FILE` | `TRASH30_LOG` | none; each purge appends one row |

Commands: `put PATH [WHY ...]`, `list`, `restore PATH [DATE]`, `purge [--dry-run]`.
Restore refuses if the original path exists again. The index is `<root>/INDEX.tsv`.

Use it from Python: `from trash30 import Can; Can("~/.trash30", days=30).put("x.txt", "why")`.

## Tests

```
pip install -e ".[test]" && pytest
```

Licence: Apache-2.0.
