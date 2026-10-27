# Standalone Cron Jobs

Put non-workstream cron jobs in this directory as `*.yaml` files. These files
are the source of truth; Redis is only the active scheduler runtime and can be
rebuilt from these declarations at server startup.

Example:

```yaml
id: daily_ar_aging
name: daily_ar_aging
skill_name: ar_aging_report
cron: "0 8 * * 1-5"
user_id: service:cron
enabled: true
description: "Run AR aging report every weekday morning"
params:
  customer_segment: all
tags:
  - finance
  - ar
```

Required fields: `skill_name`, `cron`, and `user_id`. `id` and `name` default to
the filename stem when omitted.
