# Point-in-time employment inputs

Online full refresh retrieves only the official BLS Employment Situation page and BLS calendar. Source bodies are archived under data/employment/snapshots/ with SHA-256 content identifiers. Automatic values are **unreviewed observations**, not certified initial-release vintages and not directional trading signals. Missing fields remain unavailable. A failed request retains the previous snapshot and exposes the failure.

To analyze economic surprises, supply these optional CSV files; use ISO timestamps with explicit offsets or Z:

**data/employment/releases.csv**

`reference_period,metric,actual,available_at,source,vintage`

**data/employment/expectations.csv**

`reference_period,metric,consensus,available_at,source`

Use the same units for actual and consensus. Metrics might be payroll_change (people), unemployment_rate (percent), wage_change_mom_pct (percent). Preserve each initial/revised vintage in separate rows. A consensus observed at or after release availability is rejected. Do not populate historical initial releases using today's revised series.

No consensus service, historical vendor archive, or account liquidation-price feed has been fabricated. Weekly claims, JOLTS and ADP are not included in the current automatic source coverage.

Paper decisions are separate: data/monitor/experiment_lock.json freezes rules/costs on the first online refresh; data/monitor/paper_events.jsonl records decisions and subsequently observed outcomes. Editing monitor_config.json changes retrospective scenario tests but does not rewrite an existing forward experiment.
