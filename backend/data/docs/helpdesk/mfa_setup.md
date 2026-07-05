# Multi-Factor Authentication (MFA)

MFA adds a second check on top of your password using the Authenticator app,
backup codes, or a hardware key. The assistant helps employees re-enroll and
recover MFA, but must never help anyone bypass or disable it.

## Setting up MFA on a new phone
When you replace or reset your phone, the Authenticator registration does not
transfer automatically:
1. On a signed-in device or the self-service portal, open **Security > My MFA**.
2. Choose **Add device** and scan the QR code with the Authenticator app on the
   new phone.
3. Confirm the six-digit code once to activate it.
4. Remove the old device from the list so lost hardware cannot approve prompts.

## Lost or stolen device
1. From any signed-in session or the portal, choose **Remove device** for the
   missing phone immediately.
2. Sign in using a **backup code** to register a replacement.
3. If you have no signed-in session and no backup codes, this needs identity
   verification — escalate for a manual MFA reset.

## Backup codes
- You receive 10 one-time backup codes when you first enroll; store them offline.
- Each code works once. When you have two or three left, generate a new set from
  the portal.
- Backup codes are the supported way to sign in when the phone is unavailable —
  they are not a way to skip MFA.

## Suspicious or unexpected MFA prompt
If you get an approval prompt you did not trigger:
1. **Deny** it. Never approve a prompt you did not start.
2. Change your password right away (see `password_reset.md`) — an unexpected
   prompt means someone has your password.
3. Report it as a security event (see `security_policy.md`).

## Safety notes
- The assistant never disables MFA, never approves a prompt for a caller, and
  never reads a backup code aloud.
- "Turn off MFA so I can log in faster" is not a supported request — explain the
  safe path (re-enroll or use a backup code) instead.

## When to escalate
Escalate (see `escalation_policy.md`) if the employee has lost the device and has
no backup codes, if a suspicious prompt suggests a compromised account, or if the
portal cannot register a new device.
