# PostgreSQL 17 continuous archiving and point-in-time recovery

Point-in-time recovery depends on a usable base backup and a continuous run of archived WAL through the target time. Check that archives are available and test restores before treating backup jobs as proof of recoverability. Restore into a separate instance when validating the procedure.

[Original source](https://www.postgresql.org/docs/17/continuous-archiving.html)
