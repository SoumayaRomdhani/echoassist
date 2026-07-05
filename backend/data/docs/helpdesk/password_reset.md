# Password Reset & Account Lockout

This covers resetting a forgotten password and recovering from a locked account.
The assistant must verify identity before guiding any reset and must never read,
set, or accept a password over the call.

## Self-service password reset
The fastest path is the self-service portal at the internal address
`reset.acteek.local`:
1. Choose **Forgot password**.
2. Enter your work email.
3. Approve the identity check (MFA prompt or backup code).
4. Set a new password that meets the policy: at least 12 characters, mixing
   letters, numbers, and a symbol, and not a reuse of your last 5 passwords.

The new password applies to email, VPN, and single sign-on within a few minutes.

## Account locked after too many attempts
Accounts lock automatically after 5 failed sign-ins to protect against guessing.
1. Wait 15 minutes — most temporary locks clear on their own.
2. Then use the self-service reset above rather than retrying the old password.
3. If it locks again immediately after a correct reset, a device may be caching
   the old password (mail app, VPN client) — sign those apps out.

## Identity verification
Self-service reset already proves identity through MFA. A human agent may only
perform a manual reset after verifying the employee through the approved check
(manager confirmation or a verified callback to the number on file). Never reset
a password based on a caller's say-so alone.

## Safety notes
- Never tell a caller their current or temporary password out loud; the portal
  sets it privately.
- Never accept a new password dictated by the caller; they set it themselves in
  the portal.
- A request to reset **someone else's** password is not self-service — it requires
  manager approval and goes to escalation.

## When to escalate
Escalate (see `escalation_policy.md`) if:
- The self-service portal itself is unreachable.
- The account re-locks immediately after a correct reset.
- Identity cannot be verified through an approved method.
- The request is to reset another person's account.
