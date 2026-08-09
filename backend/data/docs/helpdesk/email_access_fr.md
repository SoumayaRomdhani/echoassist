# Accès à la messagerie et à la boîte mail

Couvre Outlook (bureau), le webmail, les blocages de boîte mail et les alertes de
hameçonnage. La messagerie d'entreprise utilise l'authentification unique, donc un
problème de messagerie est parfois en réalité un problème de connexion ou de MFA.

## Commencez ici : identifiez d'abord le mode d'échec
Ne déroulez PAS une liste générique. Posez d'abord UNE question pour savoir ce qui se
passe exactement, puis suivez la branche correspondante :

> « Est-ce l'**application Outlook (bureau)**, le **webmail dans un navigateur**, ou
> **les deux** — et que voyez-vous : une **erreur**, une **demande de mot de passe**,
> ou un message **« boîte pleine »** ? »

- **Outlook bureau seulement** (le webmail marche) → branche A
- **Le bureau et le webmail échouent tous les deux** → branche B
- **« Boîte pleine » / impossible d'envoyer ou de recevoir** → branche C
- **Un e-mail suspect ou de hameçonnage** → branche D

## Branche A — Outlook bureau ne se connecte pas (le webmail marche)
Si le webmail marche mais pas l'application, le compte est bon — c'est le profil
Outlook local :
1. Vérifiez que l'ordinateur est en ligne et, à distance, connecté au VPN.
2. Quittez complètement puis rouvrez Outlook — une synchronisation en arrière-plan
   peut se bloquer après une mise en veille.
3. S'il demande un mot de passe, connectez-vous avec l'authentification unique et
   validez la MFA ; ne saisissez pas un ancien mot de passe en cache.

## Branche B — le bureau et le webmail échouent tous les deux
Si aucun des deux ne marche, c'est un problème de compte ou de connexion, pas
d'Outlook :
1. Vérifiez que vous pouvez vous connecter au portail de l'entreprise — sinon, voir
   `password_reset_fr.md` (blocage possible).
2. Vérifiez que la MFA fonctionne — si le téléphone a changé, voir `mfa_setup_fr.md`.
3. Essayez le webmail à `mail.acteek.com` une fois la connexion confirmée.

## Branche C — « boîte pleine » / impossible d'envoyer ou recevoir
- Une boîte qui a atteint sa limite de stockage cesse d'envoyer et de recevoir. Videz
  les **Éléments supprimés** et retirez les grosses pièces jointes, puis attendez
  quelques minutes que ça se resynchronise.
- Une boîte bloquée pour revue de sécurité n'est débloquée que par l'équipe sécurité —
  c'est une escalade, pas une étape en libre-service.

## Branche D — e-mail suspect ou de hameçonnage
1. Ne cliquez **pas** sur les liens et n'ouvrez pas les pièces jointes d'un message
   suspect.
2. Utilisez le bouton **Signaler un hameçonnage** dans Outlook ou le webmail ; il
   envoie le message à l'équipe sécurité et le retire de votre boîte.
3. Si vous avez déjà cliqué ou saisi des identifiants, changez votre mot de passe
   maintenant (voir `password_reset_fr.md`) et signalez-le comme incident de sécurité
   (`security_policy_fr.md`).

## Consignes de sécurité
- L'assistant ne demande ni ne répète jamais un mot de passe de boîte mail.
- Ne transférez jamais un e-mail suspect à des collègues pour les « prévenir » —
  signalez-le à la place.

## Quand escalader
Escaladez (voir `escalation_policy_fr.md`) si la boîte est bloquée pour revue de
sécurité, si le webmail et le portail échouent tous les deux (problème de compte
possible), ou si un message de hameçonnage a été suivi d'effet et que des identifiants
peuvent être exposés.
