"""trash30: a trash folder that empties itself after N days and never follows a link out of the trash.

    trash30 put PATH [WHY ...]     move PATH to <root>/<YYYY-MM-DD>/<original absolute path>
    trash30 list                   items in the trash with their purge date
    trash30 restore PATH [DATE]    move the newest trashed copy of PATH (or the one from DATE) back
    trash30 purge [--dry-run]      remove date folders older than --days, judged by folder name

Options (also environment): --root / TRASH30_ROOT (default ~/.trash30), --days / TRASH30_DAYS (default 30),
--never PATTERN (repeatable) / TRASH30_NEVER (os.pathsep separated), --log FILE / TRASH30_LOG.
A --never pattern is a path, a path prefix or a glob; "put" refuses a path that matches one, sits under one or holds one.
Index file <root>/INDEX.tsv columns: date, original path, size in bytes, why, stored path ("-" on a restore row).
"""
import argparse
import datetime
import fnmatch
import os
import re
import shutil
import sys
from pathlib import Path

__version__ = "0.1.0"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TrashError(Exception):
    pass


def _size(p):
    if os.path.islink(p) or not os.path.isdir(p):
        return os.lstat(p).st_size
    n = 0
    for d, _, fs in os.walk(p):  # os.walk does not follow links to folders
        for f in fs:
            try:
                n += os.lstat(os.path.join(d, f)).st_size
            except OSError:
                pass
    return n


class Can:
    def __init__(self, root=None, days=30, never=(), log=None, today=None):
        self.root = Path(os.path.abspath(os.path.expanduser(str(root or "~/.trash30"))))
        self.days = int(days)
        self.never = list(never)
        self.log = log
        self._today = today

    @property
    def index(self):
        return self.root / "INDEX.tsv"

    def today(self):
        return self._today or datetime.date.today()

    def purge_day(self, d):
        return (datetime.date.fromisoformat(d) + datetime.timedelta(days=self.days + 1)).isoformat()

    def _never(self, path):
        s = str(path)
        for pat in self.never:
            if "/" not in pat:
                if fnmatch.fnmatch(os.path.basename(s), pat):
                    return pat
            elif s == pat or s.startswith(pat.rstrip("/") + "/") or fnmatch.fnmatch(s, pat):
                return pat
        return None

    def _holds_never(self, p):
        for pat in self.never:
            if "/" in pat and not any(c in pat for c in "*?[") and pat.startswith(str(p) + "/"):
                return pat
        if p.is_dir() and not p.is_symlink():
            for d, ds, fs in os.walk(p):
                for n in ds + fs:
                    hit = self._never(Path(d, n))
                    if hit:
                        return hit
        return None

    def rows(self):
        if not self.index.exists():
            return []
        return [l.split("\t") for l in self.index.read_text().splitlines() if l.strip()]

    def _add(self, *cols):
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.index, "a") as f:
            f.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in cols) + "\n")

    def put(self, path, why="-"):
        p = Path(os.path.abspath(path))
        if not os.path.lexists(p):
            raise TrashError(f"no such path: {p}")
        if p == p.parent or p == Path.home() or p == self.root or self.root in p.parents or p in self.root.parents:
            raise TrashError(f"refused: {p} is the trash root, inside it, holds it, or is a top folder")
        hit = self._never(p) or self._holds_never(p)
        if hit:
            raise TrashError(f"refused: {p} matches never entry {hit}")
        self.root.mkdir(parents=True, exist_ok=True)
        if os.lstat(p).st_dev != os.stat(self.root).st_dev:
            raise TrashError(f"refused: {p} is on another filesystem than {self.root}")
        d = self.today().isoformat()
        dest = self.root / d / str(p).lstrip("/")
        n = 1
        while os.path.lexists(dest):
            dest = self.root / d / (str(p).lstrip("/") + f".{n}")
            n += 1
        sz = _size(p)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.rename(p, dest)  # renames a link itself, never its target
        self._add(d, p, sz, why, dest)
        return dest

    def listing(self):
        out = []
        for r in self.rows():
            if len(r) >= 5 and r[4] != "-" and os.path.lexists(r[4]):
                out.append((r[0], self.purge_day(r[0]), r[2], r[1], r[3]))
        return out

    def restore(self, path, date=None):
        p = Path(os.path.abspath(path))
        if os.path.lexists(p):
            raise TrashError(f"refused: {p} exists; move it away first")
        rows = [r for r in self.rows() if len(r) >= 5 and r[1] == str(p) and r[4] != "-" and os.path.lexists(r[4]) and (date is None or r[0] == date)]
        if not rows:
            raise TrashError(f"not in the can: {p}")
        r = rows[-1]
        p.parent.mkdir(parents=True, exist_ok=True)
        os.rename(r[4], p)
        up = Path(r[4]).parent
        while up != self.root and self.root in up.parents and not any(up.iterdir()):
            up.rmdir()
            up = up.parent
        self._add(self.today().isoformat(), p, r[2], "restored from " + r[4], "-")
        return Path(r[4])

    @staticmethod
    def _writable(top):
        # Folders left read-only block rmtree; open each real folder for the owner. Links are skipped, so no chmod leaves the tree.
        os.chmod(top, os.stat(top).st_mode | 0o700)
        for d, ds, _ in os.walk(top):
            for n in ds:
                q = os.path.join(d, n)
                if not os.path.islink(q):
                    os.chmod(q, os.stat(q).st_mode | 0o700)

    def purge(self, dry=False):
        """Return a list of (action, path, bytes). Date folders older than days go; links are unlinked, never followed."""
        if self.root.is_symlink() or (self.root.exists() and self.root.stat().st_uid != os.getuid()):
            raise TrashError(f"refused: trash path {str(self.root)!r} is a link or not owned by you")
        if not self.root.is_dir():
            return []
        cut = self.today() - datetime.timedelta(days=self.days)
        done = []
        for f in sorted(self.root.iterdir()):
            if not DATE.match(f.name) or not (f.is_dir() or f.is_symlink()):
                if not re.match(r"^INDEX.*\.tsv$", f.name):
                    done.append(("left alone", f, 0))
                continue
            try:
                d = datetime.date.fromisoformat(f.name)
            except ValueError:
                continue
            if d >= cut:
                continue
            if f.is_symlink():
                if not dry:
                    f.unlink()
                done.append(("would unlink link" if dry else "unlinked link", f, 0))
                continue
            sz = _size(f)
            if dry:
                done.append(("would purge", f, sz))
                continue
            self._writable(f)
            shutil.rmtree(f)  # rmtree unlinks links inside and never descends into them
            self._log(f"purged {f} ({sz} bytes)")
            done.append(("purged", f, sz))
        return done

    def _log(self, msg):
        if self.log:
            with open(self.log, "a") as fh:
                fh.write(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\t" + msg + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="trash30", description="A trash folder that empties itself after N days.")
    ap.add_argument("--root", default=os.environ.get("TRASH30_ROOT"))
    ap.add_argument("--days", type=int, default=int(os.environ.get("TRASH30_DAYS", "30")))
    ap.add_argument("--never", action="append", default=[p for p in os.environ.get("TRASH30_NEVER", "").split(os.pathsep) if p])
    ap.add_argument("--log", default=os.environ.get("TRASH30_LOG"))
    ap.add_argument("--version", action="version", version="trash30 " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("put")
    s.add_argument("path")
    s.add_argument("why", nargs="*")
    sub.add_parser("list")
    s = sub.add_parser("restore")
    s.add_argument("path")
    s.add_argument("date", nargs="?")
    s = sub.add_parser("purge")
    s.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    can = Can(a.root, a.days, a.never, a.log)
    try:
        if a.cmd == "put":
            dest = can.put(a.path, " ".join(a.why) or "-")
            print(f"{a.path} -> {dest}")
        elif a.cmd == "list":
            print("date\tpurge\tsize\toriginal\twhy")
            for r in can.listing():
                print("\t".join(r))
        elif a.cmd == "restore":
            print(f"{can.restore(a.path, a.date)} -> {a.path}")
        else:
            for act, p, sz in can.purge(a.dry_run):
                print(f"{act}\t{p}\t{sz}")
    except TrashError as e:
        print("trash30: " + str(e), file=sys.stderr)
        return 2
    return 0
