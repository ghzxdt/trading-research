# Trading Research control panel

Double-click the **Trading Research Control Panel** desktop shortcut. You can also double-click **START_APP.cmd** in this folder. The control panel opens without a command window. Repeated launches bring the existing panel forward.

## Everyday use

1. Click **Open dashboard**. The app starts the local server if necessary, then opens the dashboard in your usual browser.
2. Click **Run / Refresh data** when you want current market data and a full validated rebuild. It starts the server as needed. Watch the status or click **View logs**.
3. Check the saved-market-data date. A running server does not imply fresh financial data. The date is rechecked against the current session clock when you open the panel.

A Windows scheduled task, **Trading Research Evening Refresh**, also runs the refresh on weekday evenings. It waits until Cboe has posted the day's VIX close, because a refresh between 4:30 PM ET and that posting logs the day's paper decisions as data-blocked. Its log is `work\scheduled_refresh.log`. Opening the panel or dashboard does not download market data or place trades.

## Other buttons

| Control | Behavior |
|---|---|
| Start app | Start or reuse this app's local dashboard server without opening a browser tab. |
| Stop app | Gracefully stop this app's identified server. Preserve all data and reports. |
| Restart app | Stop and start the local server. This is the normal meaning of reset. |
| Rebuild saved data | Recalculate all pages from saved inputs without downloading data or creating forward paper decisions. |
| Repair startup | Clear a leftover build lock only if its owning process is definitely stopped. Refuse uncertain or active ownership. |
| View logs | Open a live local log viewer; details stay on this computer. |
| Open app folder | Open the app folder in File Explorer. |

Stop/restart refuse while a refresh or an active build is writing. The panel does not force-kill unrelated programs or erase records. Closing the control panel leaves the dashboard running; click **Stop app** first if you want it stopped.

## Troubleshooting

- If another program occupies port 8766, the panel reports the conflict and refuses to stop that program.
- If a refresh fails, the previous complete dashboard remains available. Read the log for the actual failing source or validation check.
- **Restart app** does not fix blocked external sources, invalid vendor data, or missing consensus history. Those limitations remain visible.
- If the machine was restarted, just open this panel and click **Open dashboard**. No terminal steps are needed.

The existing **Trading Research Dashboard** desktop URL shortcut is still a direct browser link. Use the new **Trading Research Control Panel** shortcut when you also need to start or manage the local app.

## Version preservation

The original supplied app remains in its unchanged source folder and hash-verified backup. The working version from before desktop controls is additionally preserved at **backups/before_desktop_controls_v1.zip**. This upgrade changes how the app is launched and managed; it does not change the backtest rules or cost assumptions.
