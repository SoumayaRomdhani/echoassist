# Authentification multifacteur (MFA)

La MFA ajoute une seconde vérification par-dessus votre mot de passe, via
l'application Authenticator, des codes de secours ou une clé matérielle. L'assistant
aide les employés à se réinscrire et à récupérer la MFA, mais ne doit jamais aider qui
que ce soit à la contourner ou à la désactiver.

## Configurer la MFA sur un nouveau téléphone
Quand vous remplacez ou réinitialisez votre téléphone, l'enregistrement Authenticator
ne se transfère pas automatiquement :
1. Sur un appareil connecté ou le portail en libre-service, ouvrez **Sécurité > Ma
   MFA**.
2. Choisissez **Ajouter un appareil** et scannez le QR code avec l'application
   Authenticator sur le nouveau téléphone.
3. Confirmez une fois le code à six chiffres pour l'activer.
4. Retirez l'ancien appareil de la liste afin qu'un matériel perdu ne puisse plus
   approuver d'invites.

## Appareil perdu ou volé
1. Depuis n'importe quelle session connectée ou le portail, choisissez **Retirer
   l'appareil** pour le téléphone manquant, immédiatement.
2. Connectez-vous avec un **code de secours** pour enregistrer un remplacement.
3. Si vous n'avez ni session connectée ni code de secours, cela nécessite une
   vérification d'identité — escaladez pour une réinitialisation MFA manuelle.

## Codes de secours
- Vous recevez 10 codes de secours à usage unique lors de votre première inscription ;
  conservez-les hors ligne.
- Chaque code ne fonctionne qu'une fois. Quand il vous en reste deux ou trois,
  générez-en une nouvelle série depuis le portail.
- Les codes de secours sont le moyen pris en charge pour se connecter quand le
  téléphone n'est pas disponible — ce n'est pas un moyen de sauter la MFA.

## Invite MFA suspecte ou inattendue
Si vous recevez une invite d'approbation que vous n'avez pas déclenchée :
1. **Refusez-la.** N'approuvez jamais une invite que vous n'avez pas lancée.
2. Changez votre mot de passe tout de suite (voir `password_reset_fr.md`) — une invite
   inattendue signifie que quelqu'un a votre mot de passe.
3. Signalez-le comme un incident de sécurité (voir `security_policy_fr.md`).

## Consignes de sécurité
- L'assistant ne désactive jamais la MFA, n'approuve jamais une invite pour un
  appelant, et ne lit jamais un code de secours à voix haute.
- « Désactive la MFA pour que je me connecte plus vite » n'est pas une demande prise
  en charge — expliquez la voie sûre (se réinscrire ou utiliser un code de secours).

## Quand escalader
Escaladez (voir `escalation_policy_fr.md`) si l'employé a perdu l'appareil et n'a pas
de code de secours, si une invite suspecte laisse penser à un compte compromis, ou si
le portail ne parvient pas à enregistrer un nouvel appareil.
