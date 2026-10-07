# Explicit webhook delivery

The webhook adapter is implemented; SMTP remains unimplemented. No send
happens during `run`. An operator must approve the endpoint and the alert
payload's audience, then set RAGDRIFT_WEBHOOK_URL and call:

```sh
PYTHONPATH=src python -m ragdrift deliver --store /persistent/state
```

HTTPS is required, embedded credentials and redirects are rejected. Do not
put secret webhook URLs in a config file or commit. Successful responses
write payload/destination-hash receipts. Failed sends remain retryable;
alerts are retained. The receiver should honor Idempotency-Key because a
network failure can leave delivery uncertain. This is not exactly-once
transport. Delivery uses a nonblocking local POSIX file lock. An overlapping delivery fails before sending; all delivery callers must use this command. This is not a distributed lock: use a local filesystem, not shared/network storage. The broader run/state store is still single-writer and needs persistent backup. Invalid receipt state fails closed; malformed alert files are reported while later valid files can proceed. An acknowledged send whose receipt cannot be saved is reported as uncertain, not successful.

Local tests cover failed retries and success dedup with injected senders,
not an external service. No production destination has been configured.

## Current executable baseline

October 7: the actual sibling suites ran against untouched
rag-governance-demo commit c339ae1 and the existing rag-redteam checkout.
Current demo HEAD imports a host-specific dynamic_credentials module at
import time; that prevents even the extractive backend from loading in a
normal environment. The earlier intact commit is therefore explicit, not
a claimed current-HEAD deployment. Baseline uses the extractive demo and
its policy corpus. It does not measure a real hosted LLM deployment.

A daily schedule must run on persistent infrastructure with baseline/run
state carried between jobs. A cron command in a temporary checkout is not
a durable watch. Schedule activation remains pending that deployment.
