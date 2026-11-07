# InfluxDB 3 Core line protocol reference

A point contains a table, tags, fields, and an optional timestamp. Check escaping, field types, and timestamp precision when individual writes fail or land outside the query window. Repeated writes with the same point identity can update an existing point.

[Original source](https://docs.influxdata.com/influxdb3/core/reference/line-protocol/)
