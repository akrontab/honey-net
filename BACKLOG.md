# Backlog

Ideas and features to implement. Tell Claude "implement the next backlog item" to work through these one at a time. When starting on a new item plan first and prompt for any infomration needed for implementation. Then once all information is collected, start implementation.

## Pending

- [x] Create dashboard for normalized logs
  - [x] Refactor the campaign dashboard (download panels now use `{job="events"}`, covers all honeypots)
  - [x] General log for detections and file downloads (`normalized-events.json`, uid `normalized-events`)
- [x] Tailscale clean up scripts for old machines that are no longer on the network. Sync with terraform state
- [x] User segmentation on all hosts. STOP RUNNING EVERYTHING AS ROOT!
  - [x] Docker is run with a non-root user on honeypot container hosts
  - [x] Log-stack docker processes are run with a non-root user
  - [x] Malware catalog docker processes are run with non-root users
  - [x] Remote managemnt of hosts (ssh) still uses root and still uses key based auth
  - [x] non-root users should not be accessed directly with ssh. Allows for easy auditing and intrusion detection
- [ ] Nice to have later: multiple operators with thier own user accounts with sudo access for host management. Maintain keybased logins

## Maybes

- [ ] Multiple cloud provider support with terraform

## Done

- [x] Backup and restore scripts for logs, inbox, and malware catalog (`scripts/backup.py`, `scripts/restore.py`)
