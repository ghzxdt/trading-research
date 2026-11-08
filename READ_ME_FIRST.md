# Corrected research app

Open the **Trading Research Control Panel** desktop shortcut, or **START_APP.cmd**, then click **Open dashboard**. The panel starts the server and opens **http://localhost:8766/monitor.html**. It also provides start/stop/restart, refresh, offline rebuild, logs, and startup repair. See **CONTROL_PANEL_GUIDE.md**. The original app at port 8765 was not edited.

The saved output was built and validated from the existing cached inputs. Use **Refresh data + validate** to download current sources and archive BLS observations. **Rebuild saved data** performs a network-free rebuild. Failed builds preserve the prior complete output. The console log is work/last_refresh.log.

## New tabs

- Original vs corrected: verified frozen original reports, same-input calculations, complete raw/BH/Holm test registry.
- Backtests: original gross, original scenario net, and corrected-next-open scenario net, trade ledger, annual breakdown and execution-cost stress tests.
- Paper monitor: timestamped decisions, pre-entry eligibility checks, frozen experiment configuration and hash-chained append-only log. Offline/replay builds never create a fictional forward record.
- Data quality: freshness, transformation validation, run provenance, missing calibration, and external-vendor limitations.
- Jobs & macro: static versus fetched BLS calendar, archived official release observations, and timestamp-validated imported surprises.

The four existing research tabs remain available with corrected calculations and labels. Backtest costs are explicit assumptions in **monitor_config.json**. Historical ETF proxy fills are not actual Kalshi fills. No strategy is claimed profitable or given a live leveraged position size. Exact broker liquidation calibration and full independent vendor reconciliation remain outstanding.

## Backup and rollback

The entire supplied code/data/report set (83 files, excluding the virtual environment and session metadata) was copied before edits. SHA-256 values were checked against the original and ZIP archive. See **baseline_manifest.json** and **backups/original_20261106T064353Z.zip**.

**START_ORIGINAL.cmd** opens the frozen original reports on port 8767, through a read-only static server. You can inspect the original at any time without replacing the corrected app.

For an actual code/report rollback, close the corrected app server, run `.venv\Scripts\python -B restore_baseline.py` to preview, then add `--apply` to restore. The script verifies the original hashes and creates a ZIP of the current version before restoring. Current market data and paper logs are preserved. Added modules remain on disk but the restored original runners/nav do not invoke them.

## Reproduce and verify

```
.venv\Scripts\python -B -m unittest discover -s tests -v
.venv\Scripts\python -B run_all.py --offline
.venv\Scripts\python -B run_all.py --offline --as-of 2026-11-06T01:00:00-05:00
```

The full output bundle has source/input/output hashes in output/build_manifest.json, plus separate component manifests. Do not edit backup files. Running tests does not place trades.

The included local virtual environment uses the existing installed Python 3.12 base and copied dependencies. If relocating to another computer, create a new virtual environment and install requirements.txt.
