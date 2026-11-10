# PostgreSQL 17 write-ahead log settings

WAL settings govern durability, checkpoints, and archiving. Compare write latency with checkpoint frequency, WAL volume, and storage capacity. An archiving failure or lagging consumer can require separate investigation when WAL occupies unexpected disk space.

[Original source](https://www.postgresql.org/docs/17/runtime-config-wal.html)
