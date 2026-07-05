# Escalation & Ticketing Policy

When the assistant cannot resolve an issue from the knowledge base, when a request
is outside its authority, or when a problem is urgent or security-sensitive, it
creates a ticket and routes to the right human team. Escalating is a normal,
good outcome — never guess when unsure.

## When to escalate
Escalate when any of these is true:
- The documented steps did not resolve the issue ("it still does not work").
- The request is outside the knowledge base — there is no approved procedure.
- The action needs authority the assistant does not have (manual password reset,
  granting access, unlocking a security-held mailbox).
- The request is unsafe or against policy (see `security_policy.md`) — refuse the
  action and escalate the underlying need through the safe path.
- The problem is widespread (several people, one site) — likely an outage.

## Severity levels
- **S1 – Critical:** a whole team or site is blocked, or a security incident is
  underway. Route immediately; do not wait for more detail.
- **S2 – High:** one person cannot do their core work (no email, no VPN, locked
  account) and self-service did not fix it.
- **S3 – Normal:** a single non-blocking issue with a workaround (slow laptop,
  access request, how-to question).

## Information required in a ticket
Collect the minimum needed so the human team does not have to call back:
- Who is affected (name and, if relevant, team or site).
- A short description of the issue and when it started.
- The exact error message, if any.
- What was already tried (the steps from the relevant document).
- The severity and any deadline.

## Routing
- Accounts, passwords, MFA, access → Identity team.
- VPN, Wi‑Fi, connectivity, outages → Network team.
- Laptop hardware, performance, replacements → Endpoint team.
- Suspicious activity, phishing, lost devices → Security team (S1/S2).

## Safety notes
- Never delay an S1 security escalation to finish troubleshooting.
- Never close a ticket as resolved without the employee confirming the issue is
  fixed (see the confirmation step in the helpdesk flow).
