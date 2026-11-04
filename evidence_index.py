"""Bounded, report-local full-text index of original FFDC log lines."""

import hashlib
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path


INDEX_VERSION = "1"
MAX_FILES = 600
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_LINE_CHARS = 4000


def _snapshot(paths, root):
    files = []
    for path in paths:
        stat = path.stat()
        files.append((path, str(path.relative_to(root)), stat.st_size, stat.st_mtime_ns))
    files.sort(key=lambda row: (row[2], row[1]))
    digest = hashlib.sha256()
    for _, name, size, mtime in files:
        digest.update(f"{name}\0{size}\0{mtime}\n".encode("utf-8"))
    return files, digest.hexdigest()


def _metadata(db):
    try:
        return dict(db.execute("SELECT key, value FROM metadata"))
    except sqlite3.DatabaseError:
        return {}


def ensure_index(root, paths, lines, secret):
    """Build lazily; replace the index when original files change."""
    root = Path(root)
    target = root.parent / "evidence-index.sqlite3"
    if target.is_symlink():
        raise ValueError("Evidence index path is not safe.")
    files, fingerprint = _snapshot(paths, root)
    if target.is_file():
        try:
            with closing(sqlite3.connect(target)) as db:
                meta = _metadata(db)
                if meta.get("version") == INDEX_VERSION and meta.get("fingerprint") == fingerprint:
                    return target, meta
        except sqlite3.DatabaseError:
            pass

    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    indexed_bytes = 0
    indexed_files = 0
    limited = len(files) > MAX_FILES
    try:
        with closing(sqlite3.connect(temporary)) as db:
            with db:
                db.execute("CREATE VIRTUAL TABLE evidence USING fts5(path, text, line UNINDEXED, tokenize='unicode61')")
                db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                for path, name, size, _ in files[:MAX_FILES]:
                    if indexed_bytes >= MAX_TOTAL_BYTES:
                        limited = True
                        break
                    file_bytes = 0
                    indexed_files += 1
                    if size > MAX_FILE_BYTES:
                        limited = True
                    for number, text, length in lines(path):
                        if file_bytes + length > MAX_FILE_BYTES or indexed_bytes + length > MAX_TOTAL_BYTES:
                            limited = True
                            break
                        file_bytes += length
                        indexed_bytes += length
                        if secret.search(text):
                            continue
                        if len(text) > MAX_LINE_CHARS:
                            limited = True
                        db.execute("INSERT INTO evidence(path, text, line) VALUES (?, ?, ?)",
                                   (name, text[:MAX_LINE_CHARS], number))
                meta = {
                    "version": INDEX_VERSION,
                    "fingerprint": fingerprint,
                    "files_available": str(len(files)),
                    "files_indexed": str(indexed_files),
                    "bytes_indexed": str(indexed_bytes),
                    "limited": str(int(limited)),
                }
                db.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", meta.items())
        os.replace(temporary, target)
        return target, meta
    finally:
        temporary.unlink(missing_ok=True)


def search_index(index_path, terms, match_all=False, limit=20):
    phrases = ['"' + term.replace('"', '""') + '"' for term in terms]
    query = (" AND " if match_all else " OR ").join(phrases)
    with closing(sqlite3.connect(index_path)) as db:
        rows = db.execute(
            "SELECT path, line, text FROM evidence WHERE text MATCH ? ORDER BY rank LIMIT 240",
            (query,),
        ).fetchall()
    results, per_file = [], {}
    for path, line, content in rows:
        if per_file.get(path, 0) >= 3:
            continue
        per_file[path] = per_file.get(path, 0) + 1
        results.append({"path": path, "line": int(line), "text": content,
                        "text_truncated": len(content) >= MAX_LINE_CHARS})
        if len(results) >= limit:
            break
    return results
