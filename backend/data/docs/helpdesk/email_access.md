# Email & Mailbox Access

Covers Outlook (desktop), webmail, mailbox lockouts, and phishing warnings.
Company email uses single sign-on, so an email problem is sometimes really a
sign-in or MFA problem.

## Symptom: Outlook will not connect
1. Confirm the laptop is online and, if working remotely, connected to the VPN.
2. Fully quit and reopen Outlook — a background sync can stall after sleep.
3. If it prompts for a password, sign in with single sign-on and approve MFA;
   do not type an old cached password.
4. Try **webmail** at `mail.acteek.com` in a browser. If webmail works but the
   desktop app does not, the issue is the local profile, not the account.

## Symptom: webmail also fails
If neither the desktop app nor webmail works, this is an account or sign-in
issue, not an Outlook issue:
1. Confirm you can sign in to the portal at all — if not, see `password_reset.md`.
2. Confirm MFA is working — if the phone changed, see `mfa_setup.md`.

## Mailbox locked or "full" 
- A mailbox that has hit its storage limit stops sending and receiving. Empty
  **Deleted Items** and large attachments, then wait a few minutes to re-sync.
- A mailbox locked for a security review is released only by the security team;
  this is an escalation, not a self-service step.

## Phishing and suspicious email
1. Do **not** click links or open attachments in a suspicious message.
2. Use the **Report Phishing** button in Outlook or webmail; this sends it to
   the security team and removes it from your inbox.
3. If you already clicked or entered credentials, change your password now (see
   `password_reset.md`) and report it as a security event (`security_policy.md`).

## Safety notes
- The assistant never asks for or repeats a mailbox password.
- Never forward a suspicious email to colleagues to "warn" them — report it instead.

## When to escalate
Escalate (see `escalation_policy.md`) if the mailbox is locked for security
review, if webmail and the portal both fail (possible account issue), or if a
phishing message was acted on and credentials may be exposed.
