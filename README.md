# Face baseline

Scheduled scanning was removed at the user’s request. The application now scans
only on a manual web/API request. `/etc/cron.d/face-baseline` and the installed
wrapper have been removed; no scheduler or automatic resubmission remains.

The resident service and startup registration remain in utilities Compose.
Business source: `/home/yuwk/code/face-baseline`. Existing run logs are retained.
