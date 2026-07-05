# VPN Troubleshooting

The corporate VPN (GlobalConnect) gives employees secure access to internal
systems from outside the office. Most VPN problems fall into three buckets:
sign-in failures, connection drops, and "connected but nothing loads".

## First questions to narrow it down
Before running steps, confirm one thing at a time:
- Are you getting an **error message**, or does it just hang?
- Does it fail at **sign-in**, or after you are already connected?
- Are you on **home Wi‑Fi, a hotspot, or a public network**?

Ask only one of these at a time; you rarely need all three.

## Symptom: "Authentication failed" at sign-in
1. Confirm the username is your full work email, not just the short name.
2. Re-type the password manually — a saved/expired password is the most common cause.
3. Approve the MFA prompt within 30 seconds; a timed-out prompt reads as an auth failure.
4. If the password was recently changed, sign out of the VPN client fully and sign back in.

If authentication still fails after a confirmed-correct password and a fresh MFA
approval, the account may be locked — see `password_reset.md`.

## Symptom: connection drops every few minutes
1. Switch from Wi‑Fi to a wired connection if possible.
2. Move closer to the router or disable other bandwidth-heavy apps.
3. Update the GlobalConnect client to the latest version from the Software Center.
4. Restart the laptop to clear a stale network adapter state.

## Symptom: connected, but internal sites do not load
1. Confirm the status icon shows **Connected**, not **Connecting**.
2. Try the internal portal by its full address, not a bookmark.
3. Flush DNS: restart the laptop, which is the safe, supported reset.
4. Confirm you are not on a network that blocks VPN traffic (some hotels/cafés do).

## Safety notes
- Never disable the VPN client's certificate checks, even if a prompt suggests it.
- Do not install a personal or third-party VPN to "get around" the corporate one.

## When to escalate
Escalate to the network team (see `escalation_policy.md`) if:
- Authentication fails after the password and MFA are confirmed correct.
- The connection drops repeatedly on a known-good wired network.
- Multiple people on the same site report the VPN is down at the same time (possible outage).
Include the exact error text, the network type, and the client version in the ticket.
