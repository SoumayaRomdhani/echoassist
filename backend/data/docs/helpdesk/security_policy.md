# IT Security Policy (Employee-Facing)

These are the non-negotiable rules the assistant enforces. When a request
conflicts with this policy, the assistant refuses the unsafe action, explains
why briefly, and offers the safe alternative or an escalation.

## Passwords
- Never share your password with anyone, including IT — IT never needs it.
- The assistant will never tell you a password, set one for you over the call,
  or accept a password you read aloud. Passwords are set privately in the portal.
- There is no "admin password" to hand out. Requests for an administrator or
  shared password are refused; the safe path is a proper access request
  (see `account_permissions.md`).

## Multi-factor authentication
- MFA must never be disabled or bypassed. "Turn off MFA" is not a supported
  request; use a backup code or re-enroll a device instead (see `mfa_setup.md`).
- Never approve an MFA prompt you did not personally trigger, and never approve
  one on someone else's behalf.

## Suspicious activity — report it
Report any of the following as a security event:
- An MFA prompt you did not start.
- A message asking for your password or a code.
- A colleague asking you to share credentials or approve a login.
- A lost or stolen laptop or phone.
Use **Report Phishing** for email, or ask the assistant to raise a security
escalation. When in doubt, report — a false alarm is fine.

## Devices and software
- Install only approved software from the Software Center.
- Do not install personal VPNs, "optimizers", or registry cleaners.
- Keep the managed antivirus enabled at all times.
- Lock your screen when you step away; never leave a signed-in laptop unattended.

## Data handling
- Do not email company data to personal accounts.
- Do not paste confidential data into unapproved external tools or chatbots.
- Share files through approved systems with least-privilege access.

## What the assistant will not do
The assistant refuses, and routes to a human when appropriate, if asked to:
share or reset a password without verified identity, reveal or bypass MFA, grant
access it is not authorized to grant, or disable a security control. These are
refused even if the caller says a manager approved it — approval happens on record
in the proper system.
