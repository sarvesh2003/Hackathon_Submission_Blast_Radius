"""Byte-exact unified-diff parser and applier (no git, no patch binary).

Lines are split on b"\\n" only, so "\\r" stays part of a line's content.
Anything we cannot parse or apply exactly raises PatchError; callers then
fall back to the most conservative answer.
"""

from __future__ import annotations

import re

_HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(Exception):
    pass


class Hunk:
    __slots__ = ("old_start", "old_len", "new_start", "new_len", "old", "new", "old_lines", "new_lines", "ins_after")

    def __init__(self, old_start, old_len, new_start, new_len):
        self.old_start = old_start
        self.old_len = old_len
        self.new_start = new_start
        self.new_len = new_len
        self.old = []  # old-side lines, each with its b"\n" (or without, at EOF)
        self.new = []
        self.old_lines = []  # 1-based old line numbers of removed lines
        self.new_lines = []  # 1-based new line numbers of added lines
        self.ins_after = []  # for each added line: the old line number it follows (0 = file start)


class FilePatch:
    __slots__ = ("old_path", "new_path", "hunks", "binary", "new_file", "deleted", "renamed", "mode_only", "old_mode", "new_mode")

    def __init__(self):
        self.old_path = None  # repo-relative, None for /dev/null
        self.new_path = None
        self.hunks = []
        self.binary = False
        self.new_file = False
        self.deleted = False
        self.renamed = False
        self.mode_only = False
        self.old_mode = None
        self.new_mode = None

    @property
    def path(self):
        return self.new_path or self.old_path

    def __repr__(self):
        return f"FilePatch({self.old_path!r}->{self.new_path!r}, hunks={len(self.hunks)}, bin={self.binary})"


def _strip_prefix(p: bytes) -> str | None:
    p = p.split(b"\t", 1)[0]
    if p == b"/dev/null":
        return None
    if p.startswith(b'"'):
        raise PatchError("quoted path")
    if p[:2] in (b"a/", b"b/"):
        p = p[2:]
    return p.decode("utf-8")


def parse(data: bytes) -> list[FilePatch]:
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    files: list[FilePatch] = []
    cur: FilePatch | None = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith(b"diff --git "):
            cur = FilePatch()
            files.append(cur)
            m = re.match(rb"^diff --git a/(\S+) b/(\S+)$", line)
            if not m:
                raise PatchError("bad diff --git line")
            cur.old_path = m.group(1).decode("utf-8")
            cur.new_path = m.group(2).decode("utf-8")
            i += 1
            continue
        if line.startswith(b"--- ") and i + 1 < n and lines[i + 1].startswith(b"+++ "):
            if cur is None or cur.hunks:
                cur = FilePatch()
                files.append(cur)
            cur.old_path = _strip_prefix(line[4:])
            cur.new_path = _strip_prefix(lines[i + 1][4:])
            if cur.old_path is None:
                cur.new_file = True
            if cur.new_path is None:
                cur.deleted = True
            i += 2
            continue
        if line.startswith(b"@@"):
            if cur is None:
                raise PatchError("hunk before header")
            m = _HUNK.match(line)
            if not m:
                raise PatchError("bad hunk header")
            os_, ol, ns, nl = m.groups()
            h = Hunk(int(os_), 1 if ol is None else int(ol), int(ns), 1 if nl is None else int(nl))
            cur.hunks.append(h)
            i += 1
            o_left, n_left = h.old_len, h.new_len
            o_no, n_no = h.old_start if h.old_len else h.old_start + 1, h.new_start if h.new_len else h.new_start + 1
            last = None  # which sides the previous line belonged to
            while i < n and (o_left > 0 or n_left > 0 or (i < n and lines[i].startswith(b"\\"))):
                l = lines[i]
                if l.startswith(b"\\"):
                    # "\ No newline at end of file": the previous line has no terminator
                    if last is None:
                        raise PatchError("stray no-newline marker")
                    if "o" in last and h.old:
                        h.old[-1] = h.old[-1][:-1]
                    if "n" in last and h.new:
                        h.new[-1] = h.new[-1][:-1]
                    last = None
                    i += 1
                    continue
                if o_left == 0 and n_left == 0:
                    break
                tag, body = l[:1], l[1:] + b"\n"
                if tag == b" " or l == b"":
                    if l == b"":
                        body = b"\n"
                    h.old.append(body)
                    h.new.append(body)
                    o_left -= 1
                    n_left -= 1
                    o_no += 1
                    n_no += 1
                    last = "on"
                elif tag == b"-":
                    h.old.append(body)
                    h.old_lines.append(o_no)
                    o_left -= 1
                    o_no += 1
                    last = "o"
                elif tag == b"+":
                    h.new.append(body)
                    h.new_lines.append(n_no)
                    h.ins_after.append(o_no - 1)
                    n_left -= 1
                    n_no += 1
                    last = "n"
                else:
                    raise PatchError("bad hunk line")
                if o_left < 0 or n_left < 0:
                    raise PatchError("hunk overflow")
                i += 1
            if o_left or n_left:
                raise PatchError("truncated hunk")
            continue
        if line == b"-- ":
            break  # git format-patch signature
        if cur is not None:
            if line.startswith(b"new file mode"):
                cur.new_file = True
                cur.new_mode = line.split()[-1]
            elif line.startswith(b"deleted file mode"):
                cur.deleted = True
            elif line.startswith(b"rename from ") or line.startswith(b"copy from "):
                cur.renamed = True
            elif line.startswith(b"old mode"):
                cur.old_mode = line.split()[-1]
            elif line.startswith(b"new mode"):
                cur.new_mode = line.split()[-1]
            elif line.startswith(b"Binary files") or line.startswith(b"GIT binary patch"):
                cur.binary = True
            elif line.startswith((b"index ", b"similarity index", b"dissimilarity index", b"rename to ", b"copy to ")):
                pass
            elif line.strip() == b"":
                pass
            else:
                raise PatchError(f"unexpected line {i + 1}")
        elif line.strip() and not line.startswith((b"From ", b"Subject", b"Date", b"commit ", b"Author")):
            # preamble text before the first diff is tolerated only if it is not diff-like
            pass
        i += 1
    for f in files:
        if f.deleted:
            f.new_path = None
        if f.new_file:
            f.old_path = None
        if not f.hunks and not f.binary and not f.new_file and not f.deleted and not f.renamed:
            f.mode_only = True
    if not files:
        raise PatchError("empty patch")
    return files


def split_keep(content: bytes) -> list[bytes]:
    """Split on b"\\n", keeping terminators; the last piece may lack one."""
    out = content.split(b"\n")
    res = [x + b"\n" for x in out[:-1]]
    if out[-1]:
        res.append(out[-1])
    return res


def apply_file(content: bytes | None, fp: FilePatch) -> bytes | None:
    """Apply one file's hunks to `content` (None when the file is new)."""
    if fp.binary:
        raise PatchError("binary patch")
    if fp.deleted:
        if fp.hunks and content is not None:
            # verify the deletion matches what is there
            old = b"".join(fp.hunks[0].old) if len(fp.hunks) == 1 else None
            if old is not None and old != content:
                raise PatchError("delete content mismatch")
        return None
    lines = [] if content is None else split_keep(content)
    out: list[bytes] = []
    pos = 0  # index into lines
    for h in fp.hunks:
        start = h.old_start - 1 if h.old_len else h.old_start
        if start < pos or start + len(h.old) > len(lines) or lines[start : start + len(h.old)] != h.old:
            raise PatchError(f"hunk does not apply at {h.old_start}")
        out.extend(lines[pos:start])
        out.extend(h.new)
        pos = start + len(h.old)
    out.extend(lines[pos:])
    return b"".join(out)


def apply_to_tree(files: list[FilePatch], read) -> dict[str, bytes | None]:
    """Return {path: new bytes or None (deleted)} for every touched path.

    `read(path)` returns the pristine bytes or None when the file does not exist.
    """
    result: dict[str, bytes | None] = {}
    for fp in files:
        if fp.mode_only:
            continue
        src = fp.old_path
        old = None if src is None else (result[src] if src in result else read(src))
        if src is not None and old is None:
            raise PatchError(f"missing file {src}")
        if fp.new_file and fp.new_path is not None and read(fp.new_path) is not None:
            raise PatchError(f"new file exists {fp.new_path}")
        new = apply_file(old, fp) if (fp.hunks or fp.deleted or fp.new_file) else old
        if fp.renamed and src is not None and src != fp.new_path:
            result[src] = None
        if fp.new_path is not None:
            result[fp.new_path] = new if new is not None else b""
        elif src is not None:
            result[src] = None
    return result
