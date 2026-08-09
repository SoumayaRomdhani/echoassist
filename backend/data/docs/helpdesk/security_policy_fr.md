# Politique de sécurité informatique (côté employé)

Ce sont les règles non négociables que l'assistant applique. Quand une demande entre
en conflit avec cette politique, l'assistant refuse l'action dangereuse, explique
brièvement pourquoi, et propose l'alternative sûre ou une escalade.

## Mots de passe
- Ne partagez jamais votre mot de passe avec qui que ce soit, y compris l'IT — l'IT
  n'en a jamais besoin.
- L'assistant ne vous dira jamais un mot de passe, n'en définira pas un pour vous
  pendant l'appel, et n'acceptera pas un mot de passe que vous lisez à voix haute. Les
  mots de passe se définissent en privé dans le portail.
- Il n'existe pas de « mot de passe administrateur » à distribuer. Les demandes de mot
  de passe admin ou partagé sont refusées ; la voie sûre est une demande d'accès en
  bonne et due forme (voir `account_permissions_fr.md`).

## Authentification multifacteur
- La MFA ne doit jamais être désactivée ni contournée. « Désactive la MFA » n'est pas
  une demande prise en charge ; utilisez un code de secours ou réinscrivez un appareil
  (voir `mfa_setup_fr.md`).
- N'approuvez jamais une invite MFA que vous n'avez pas déclenchée vous-même, et n'en
  approuvez jamais une pour le compte de quelqu'un d'autre.

## Activité suspecte — signalez-la
Signalez comme incident de sécurité l'un des cas suivants :
- Une invite MFA que vous n'avez pas déclenchée.
- Un message demandant votre mot de passe ou un code.
- Un collègue qui vous demande de partager des identifiants ou d'approuver une
  connexion.
- Un ordinateur portable ou un téléphone perdu ou volé.
Utilisez **Signaler un hameçonnage** pour les e-mails, ou demandez à l'assistant
d'ouvrir une escalade de sécurité. En cas de doute, signalez — une fausse alerte n'est
pas grave.

## Appareils et logiciels
- N'installez que des logiciels approuvés depuis le Software Center.
- N'installez pas de VPN personnels, d'« optimiseurs » ni de nettoyeurs de registre.
- Gardez l'antivirus géré activé en permanence.
- Verrouillez votre écran quand vous vous absentez ; ne laissez jamais un ordinateur
  connecté sans surveillance.

## Traitement des données
- N'envoyez pas de données de l'entreprise vers des comptes personnels.
- Ne collez pas de données confidentielles dans des outils externes non approuvés ni
  dans des chatbots.
- Partagez les fichiers via les systèmes approuvés, avec un accès au moindre privilège.

## Ce que l'assistant ne fera pas
L'assistant refuse, et route vers un humain le cas échéant, s'il lui est demandé de :
partager ou réinitialiser un mot de passe sans identité vérifiée, révéler ou contourner
la MFA, accorder un accès qu'il n'est pas autorisé à accorder, ou désactiver un
contrôle de sécurité. Ces demandes sont refusées **même si l'appelant dit qu'un manager
a approuvé** — l'approbation se fait sur trace, dans le système approprié.
