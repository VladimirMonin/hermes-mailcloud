---
applyTo: "src/**/*.py,tests/**/*.py,schemas/**/*.json"
name: "LOG.Observability"
description: "Read before changing diagnostics, redaction, output channels, logging handlers, debug, support export or telemetry."
---

# LOG — Safe, useful diagnostics

Owner: [observability policy](../docs/foundation/observability-policy.md).
Verification: [testing instruction](TEST.quality_gates.instructions.md).
This is an adaptation of the complete Project Foundation Kit logging procedure;
existing project privacy and output contracts remain authoritative.

1. Start from the scenario and actual producer. Name the fact being explained:
   start, result, important refusal/skip, partial outcome or resource cleanup.
   Do not equate request, acceptance, completed effect, persistence and delivery.
2. Reuse the existing envelope, sanitizer and output owner. Keep the application
   callable without a terminal; only the output adapter writes to stdout/stderr.
   JSON stdout remains one machine-readable envelope, never mixed with log lines.
   Do not make diagnostics a second state store or a product retry controller.
3. Select safe technical fields from the policy: operation, stage/reason/outcome,
   typed error/exit code, counts, attempts and durations with units. Establish
   source/type, not just a friendly field name. Preserve known zeroes and safe
   adjacent numbers; omit unknowns or use null only where the contract permits.
4. Never emit credentials, headers/cookies, raw provider streams, file contents,
   configuration bodies, exception chains or raw public URLs. Use `output.py`
   sanitization and existing URL fingerprints before any relevant serialization.
   DEBUG does not waive privacy. Do not serialize the whole request/result for
   convenience, and do not fall back to raw text if filtering fails. Repeated
   sanitization must be idempotent for supported data, including direct results
   before serialization. A redaction marker is untrusted input: it never skips
   the remaining sensitive value or another credential in the same message.
5. Avoid repetitive ticks and do not sample away the required terminal result.
   Before adding a persistent sink, specify its private location, owner, size,
   rotation/retention, cleanup and bounded I/O-failure behavior. No persistent
   diagnostic file or new telemetry framework is required merely by this policy.
6. Before test import/collection, isolate config/home/journal/backend roots. On
   synthetic inputs, exercise the real producer → sanitizer → formatter → output.
   Parse nonempty structured output and verify meaningful fields AND absence of
   forbidden sentinels. Inspect stdout/stderr separately. For a persistent sink,
   read bytes after flush/drain; caplog alone is not that proof.
7. Record actual command, raw exit, observation and limits in the private handoff.
   A structural Markdown check is not runtime/privacy PASS. Recheck affected
   surfaces after changing shared serialization/filtering; preserve applicable
   unchanged evidence. Update the policy only for a real channel/contract change.

Local collection, storage, support export and external analytics are separate
permissions. No hidden transmission, automatic support bundle or widened content
capture is authorized by diagnostics work. Credentials stay protected even in DEV.
