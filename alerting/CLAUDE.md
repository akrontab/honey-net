# alerting

Alerting detector service for honey-net. Runs on the **log-stack** host as a
separate Docker Compose stack (under `/opt/log-stack/alerting/`). Polls Loki
and the malware-catalog, evaluates detection rules, and writes detection events
as JSONL. Vector forwards those events to `{job="detections"}` in Loki.

See `docs/alerting-plan.md` for the full design and phase roadmap.

## Detection-event contract

```json
{
  "timestamp": "ISO-8601 UTC",
  "rule_id":   "real-ssh-auth-success",
  "severity":  "page | notice | digest",
  "category":  "security-model | novelty | threshold | campaign",
  "entity":    "the notable thing (IP, sha256 prefix, honeypot name, …)",
  "summary":   "human-readable one-liner",
  "context":   { "rule-specific fields" }
}
```

Stream labels in Loki: `{job="detections", severity="…", rule_id="…", category="…"}`.

## Rules (Phase 1)

| Rule ID | Class | Severity | Trigger |
|---|---|---|---|
| `real-ssh-auth-success` | Security-model violation | `page` | Non-operator IP authenticates on `:65022` |
| `sensor-dark` | Security-model violation | `page` | Honeypot has zero events for `SENSOR_DARK_MINS` min |
| `new-sample` | Novelty | `notice` | New SHA-256 ingested into catalog |
| `credential-burst` | Threshold | `notice` | Single IP ≥ `BURST_THRESHOLD` logins in one poll interval |

## Dedup

`page` and `notice` rules that use `dedup=True` suppress re-fires of the same
`(rule_id, entity)` pair within 1 hour (in-memory; resets on service restart).
`new-sample` does not deduplicate — each new SHA is a distinct entity.

## Operator IP allowlist

`operators.json` (repo root) lists operator Tailscale IPs for the
`real-ssh-auth-success` rule. Add your Tailscale IP there before deploying or
you will receive a detection on every management SSH session.

```json
{ "operator_ips": ["100.x.y.z"] }
```

## Deploy

```
python honey.py deploy-detector
# or directly:
python scripts/deploy_detector.py
```

The script reads `state.json` for `LOKI_HOST` (log-stack Tailscale IP) and
`CATALOG_URL` (malware-catalog Tailscale IP), writes `.env` automatically, and
redeploys only the alerting service without touching Loki or Grafana.

## Gotchas

### Sensor-dark fires immediately for undeployed honeypots
The rule checks every honeypot in `honey-net.json`. If a honeypot is listed but
not yet deployed, the sensor-dark rule will fire (and then be suppressed by
1-hour dedup). Either deploy the honeypot or remove it from `honey-net.json`.

### Vector label cardinality
`rule_id` and `category` are Loki stream labels. Avoid adding rules with highly
variable values in those fields — high cardinality degrades Loki performance.

### Detection log is append-only
`/opt/log-stack/alerting/volumes/detector/detections.json` grows indefinitely.
Vector's `device_and_inode` fingerprinting means rotation-safe. The file does
not need manual management within Loki's 30-day retention window.

### LOKI_HOST is the Tailscale IP, not localhost
Loki on log-stack binds to `${TAILSCALE_IP}:3100`, not `0.0.0.0`. Even though
the detector runs on the same host, it must reach Loki via the Tailscale IP.
The deploy script sets `LOKI_HOST` from `state.json` automatically.
