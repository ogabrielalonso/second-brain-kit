# brain-kit services on Windows (Task Scheduler)

Windows has no direct equivalent of launchd's `KeepAlive` (auto-restart a crashed
long-running process) or of a systemd `.timer` tied to a `.service`. The mapping below
gets equivalent behavior with `schtasks`, with one documented deviation (the daemon).
Read this after Phase 1 of the installer if the owner's machine is Windows.

Fill in the same three values used by the launchd/systemd templates before running any
command below:

- `{{PYTHON}}`: absolute path to python3.exe (e.g. `%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe`)
- `{{KIT_DIR}}`: absolute path to the kit checkout (default `%USERPROFILE%\.brain\kit`)
- `{{BRAIN_HOME}}`: absolute path to `%USERPROFILE%\.brain`

Run every `schtasks /create` command below from an elevated PowerShell prompt once, at
install time. Re-running with the same `/TN` updates the task in place.

## 1. Daemon (retrieval server)

Task Scheduler has no built-in "restart forever" flag like launchd's `KeepAlive`. The
closest approximation is a logon trigger plus "restart the task every N minutes if it
fails", configured on the task's Settings tab (not exposed by `schtasks /create` flags,
set it once in the Task Scheduler GUI after creation, or via the `/RI` restart-interval
flag together with a task that self-exits on daemon crash). **Deviation from the
launchd/systemd behavior**: this is a supervised restart on a timer, not a true
process-level keep-alive; report this to the owner as a known platform gap, do not
silently claim parity.

```powershell
schtasks /create /TN "BrainKit\Daemon" /TR "\"{{PYTHON}}\" \"{{KIT_DIR}}\scripts\brain_daemon.py\"" /SC ONLOGON /RL LIMITED /F
```

## 2. Daily pipeline (05:00 primary, 12:00 retry)

Two triggers on the same task, matching the launchd two-entry `StartCalendarInterval`
and the systemd two-line `OnCalendar`. `brain_daily.py` is idempotent per day, so the
12:00 run is a free retry, not a duplicate pipeline.

```powershell
schtasks /create /TN "BrainKit\Daily" /TR "\"{{PYTHON}}\" \"{{KIT_DIR}}\scripts\brain_daily.py\"" /SC DAILY /ST 05:00 /RL LIMITED /F
schtasks /create /TN "BrainKit\DailyRetry" /TR "\"{{PYTHON}}\" \"{{KIT_DIR}}\scripts\brain_daily.py\"" /SC DAILY /ST 12:00 /RL LIMITED /F
```

## 3. Weekly pipeline (Saturdays, 05:00)

```powershell
schtasks /create /TN "BrainKit\Weekly" /TR "\"{{PYTHON}}\" \"{{KIT_DIR}}\scripts\brain_weekly_auto.py\"" /SC WEEKLY /D SAT /ST 05:00 /RL LIMITED /F
```

## 4. Aging audit (day 1 of every month, 05:30)

```powershell
schtasks /create /TN "BrainKit\Aging" /TR "\"{{PYTHON}}\" \"{{KIT_DIR}}\scripts\brain_aging.py\"" /SC MONTHLY /D 1 /ST 05:30 /RL LIMITED /F
```

## 5. Watchdog (every 6 hours)

```powershell
schtasks /create /TN "BrainKit\Watchdog" /TR "\"{{PYTHON}}\" \"{{KIT_DIR}}\scripts\brain_watchdog.py\"" /SC HOURLY /MO 6 /ST 00:05 /RL LIMITED /F
```

## Logs

None of the scripts above receive a Task Scheduler-level stdout redirect by default
(`schtasks` has no direct equivalent of `StandardOutPath`). Each script already writes
its own internal log under `{{BRAIN_HOME}}\logs\<job>.log`; that is sufficient on
Windows and keeps parity with the "log hygiene" rule (never let two different writers
share one log file) without adding a second, redundant capture file.

## Verifying

```powershell
schtasks /query /TN "BrainKit\Daemon" /V /FO LIST
```

Run once by hand to confirm the command line is correct before trusting the schedule:

```powershell
schtasks /run /TN "BrainKit\Daily"
```
