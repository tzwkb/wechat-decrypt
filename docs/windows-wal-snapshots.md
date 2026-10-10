# Windows WAL snapshots

`decrypt_all.py` reads the main database and its `-wal` companion together before
decrypting. It checks the WAL format, generation salts and rolling checksums, and
uses the last committed version of each page. Uncommitted writes and frames left
over from an older WAL generation are excluded. The last commit's database size
controls growth and truncation.

If either file changes while being read, capture retries up to three times. An
invalid or continuously changing WAL fails that database instead of silently
publishing an older main-file-only snapshot. Retry while WeChat is idle. Sources
are only read; output replacement remains atomic.

The synthetic suite checks both checksum byte orders, transaction boundaries,
growth/truncation, stale generations, corruption, and real SQLite WAL recovery.
It also checks native decryption with synthetic encrypted WAL pages. Verification
on a live WeChat account still requires a valid captured account-wide raw key.
