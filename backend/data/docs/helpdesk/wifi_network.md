# Wi‑Fi & Network Connectivity

Covers office Wi‑Fi, home connectivity for remote work, and the difference
between a local network problem and a company outage. A Wi‑Fi issue is not the
same as a VPN issue — see `vpn_troubleshooting.md` if you connect to Wi‑Fi fine
but cannot reach internal systems.

## Start here: identify the failure mode first
Do NOT run a generic checklist. First ask ONE question to learn what exactly
happens, then follow the matching branch below:

> "When you try to connect, which of these happens: the **ACTEEK-Corp network
> doesn't appear**, it **rejects your password**, it **connects but has no
> internet**, it **keeps trying and fails**, or do **other networks also fail**?"

- **ACTEEK-Corp does not appear** → branch A
- **Password / credentials rejected** → branch B
- **Connected but no internet / can't reach internal sites** → branch C
- **Spins ("Connecting…") then fails** → branch D
- **Other Wi‑Fi networks also fail** → branch E

Reference: connect to **ACTEEK-Corp** with your single sign-on credentials.
**ACTEEK-Guest** is for visitors only and does not reach internal systems.

## Branch A — ACTEEK-Corp network does not appear
1. Toggle Wi‑Fi off and on, then rescan for networks.
2. Confirm Wi‑Fi is on and airplane mode is off.
3. Move closer to an access point (you may be out of range).
4. Restart the laptop to reset the wireless adapter.
5. Still not listed and colleagues nearby see it → likely an adapter fault on the
   laptop → escalate to the Endpoint team.

## Branch B — password / credentials rejected
1. Re-enter your single sign-on credentials carefully (a saved/old password is the
   usual cause).
2. If your password was recently changed or the account may be locked, this is a
   sign-in issue, not Wi‑Fi — see `password_reset.md`.
3. Confirm you are joining **ACTEEK-Corp**, not ACTEEK-Guest.

## Branch C — connected but no internet / internal sites won't load
1. Confirm the status shows **Connected**, not "Connecting" or "No internet".
2. If you are remote, this is likely a VPN/internal-access issue, not Wi‑Fi — see
   `vpn_troubleshooting.md`.
3. Restart the laptop to refresh the network connection (the safe, supported reset).

## Branch D — spins ("Connecting…") then fails
1. Forget the ACTEEK-Corp network, then reconnect and re-enter your credentials.
2. Confirm Wi‑Fi is on and airplane mode is off.
3. Restart the laptop to reset the wireless adapter.
4. Only you affected after these steps → escalate to the Network team; several
   people on the same floor affected → likely an access-point outage (escalate once).

## Branch E — other networks also fail
If your laptop cannot connect to ANY Wi‑Fi (home, phone hotspot, etc.), the
problem is the device, not corporate Wi‑Fi:
1. Restart the laptop to reset the wireless adapter.
2. If it still fails on every network, escalate to the Endpoint team — the wireless
   adapter or driver likely needs attention.

## Home Wi‑Fi (remote work): weak or dropping signal
1. Move closer to the router or remove obstructions.
2. Restart the home router and modem (unplug 30 seconds, plug back in).
3. Prefer a wired connection for calls if one is available.
4. Test another device — if everything is slow, it is likely your internet
   provider, not the laptop.

## Local problem vs. company outage
- Only your device affected → local: work the matching branch above.
- Several colleagues at the same site affected at once → likely an outage:
  escalate so it is tracked once, not as many separate tickets.

## Safety notes
- Never connect a work laptop to an unknown open network to "just get online" for
  sensitive work; use a trusted network and the VPN.
- Do not share the corporate Wi‑Fi credentials with visitors — point them to
  ACTEEK-Guest.

## When to escalate
Escalate (see `escalation_policy.md`) if the corporate Wi‑Fi is down for several
people, if the network is unreachable after the matching branch and a restart, if
the wireless adapter fails on every network (Endpoint team), or if a remote
employee's home internet works but they still cannot reach company systems (then
it is likely VPN — see `vpn_troubleshooting.md`).
