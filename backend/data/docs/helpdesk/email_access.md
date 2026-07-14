# Email & Mailbox Access

Covers Outlook (desktop), webmail, mailbox lockouts, and phishing warnings.
Company email uses single sign-on, so an email problem is sometimes really a
sign-in or MFA problem.

## Start here: identify the failure mode first
Do NOT run a generic checklist. First ask ONE question to learn what exactly
happens, then follow the matching branch:

> "Is it the **Outlook desktop app**, **webmail in a browser**, or **both** — and
> what do you see: an **error**, a **password prompt**, or a **'mailbox full'**
> message?"

- **Outlook desktop only** (webmail works) → branch A
- **Both desktop and webmail fail** → branch B
- **"Mailbox full" / can't send or receive** → branch C
- **A suspicious or phishing email** → branch D

## Branch A — Outlook desktop won't connect (webmail works)
If webmail works but the desktop app does not, the account is fine — it's the
local Outlook profile:
1. Confirm the laptop is online and, if remote, connected to the VPN.
2. Fully quit and reopen Outlook — a background sync can stall after sleep.
3. If it prompts for a password, sign in with single sign-on and approve MFA; do
   not type an old cached password.

## Branch B — both desktop and webmail fail
If neither works, this is an account or sign-in issue, not an Outlook issue:
1. Confirm you can sign in to the company portal at all — if not, see
   `password_reset.md` (possible lockout).
2. Confirm MFA is working — if the phone changed, see `mfa_setup.md`.
3. Try webmail at `mail.acteek.com` once sign-in is confirmed.

## Branch C — "mailbox full" / can't send or receive
- A mailbox that has hit its storage limit stops sending and receiving. Empty
  **Deleted Items** and remove large attachments, then wait a few minutes to
  re-sync.
- A mailbox locked for a security review is released only by the security team —
  that is an escalation, not a self-service step.

## Branch D — suspicious or phishing email
1. Do **not** click links or open attachments in a suspicious message.
2. Use the **Report Phishing** button in Outlook or webmail; it sends the message
   to the security team and removes it from your inbox.
3. If you already clicked or entered credentials, change your password now (see
   `password_reset.md`) and report it as a security event (`security_policy.md`).

## Safety notes
- The assistant never asks for or repeats a mailbox password.
- Never forward a suspicious email to colleagues to "warn" them — report it instead.

## When to escalate
Escalate (see `escalation_policy.md`) if the mailbox is locked for security
review, if webmail and the portal both fail (possible account issue), or if a
phishing message was acted on and credentials may be exposed.
