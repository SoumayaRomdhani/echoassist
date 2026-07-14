# Slow or Unresponsive Laptop

A slow laptop usually comes from too many running apps, low disk space, a pending
update, or — less often — malware. Work through the cheap, safe steps first and
escalate only if performance stays bad after them.

## Start here: identify the failure mode first
Do NOT run a generic checklist. First ask ONE question, then follow the matching
branch:

> "Is it slow **all the time**, only in a **specific app** (like video calls or a
> heavy program), or did it **start suddenly** after an update or new software?"

- **Slow all the time** → branch A
- **Only during video calls** → branch B
- **Only one specific app / when it's open** → branch C
- **Started suddenly** → branch D

## Branch A — slow all the time
1. **Restart** — clears memory and finishes pending updates; many "slow for days"
   laptops are simply overdue for a reboot.
2. **Free up disk space** — Windows slows sharply when the system drive is nearly
   full. Check free space on C:, empty the Recycle Bin, clear large Downloads and
   old local copies of files that also live in the cloud. Aim for at least 10% free.
3. **Reduce startup and background apps** — open Task Manager, sort by CPU then
   Memory, close what you are not using (especially extra browser tabs), and in
   the **Startup** tab disable apps you do not need at login (keep security and VPN).
4. **Run the managed malware scan** if it is still slow (see branch D step 2).

## Branch B — only slow during video calls
1. Close other apps and browser tabs before the call.
2. Turn off background blur/effects, which are CPU-heavy on older laptops.
3. Use a wired network or sit closer to the router.

## Branch C — only one specific app is slow
1. Open **Task Manager** and sort by CPU, then Memory, to see if that app is using
   most of the resources.
2. Close other heavy apps and extra browser windows to free resources for it.
3. If only that one app is slow while everything else is fine, note the app name —
   it may need its own fix or an update; escalate with the app name if it persists.

## Branch D — started suddenly (after an update or new software)
1. **Restart** first — a pending update often finishes on reboot.
2. Run the company-managed antivirus **Full Scan** from the system tray icon. Do
   **not** download a third-party "cleaner" or "optimizer" — those are unapproved
   and often unsafe.
3. If it began right after installing something, that software is the likely cause.

## Safety notes
- Never install unapproved optimization or registry-cleaner tools.
- Never disable the managed antivirus to "speed things up".

## When to escalate
Escalate (see `escalation_policy.md`) if the laptop is still slow after a restart,
disk cleanup, and a clean malware scan; if the scan finds something it cannot
remove; or if the disk is failing (loud clicking, frequent freezes). Include the
model, age, and what makes it slow.
