# GitLab postmortem of the 31 January 2017 database outage

While investigating replication lag, an operator accidentally removed data on the primary database. The team restored service from an earlier snapshot and lost later changes. The postmortem illustrates the difference between a configured backup process and a recoverable backup.

[Original source](https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/)
