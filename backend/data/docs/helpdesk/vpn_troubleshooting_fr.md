# Dépannage du VPN

Le VPN d'entreprise (GlobalConnect) donne aux employés un accès sécurisé aux systèmes
internes depuis l'extérieur du bureau. La plupart des problèmes de VPN tiennent en
trois cas : échecs de connexion, coupures de connexion, et « connecté mais rien ne
charge ».

## Premières questions pour cerner le problème
Avant de lancer des étapes, confirmez une seule chose à la fois :
- Avez-vous un **message d'erreur**, ou est-ce que ça reste bloqué ?
- Est-ce que ça échoue **à la connexion**, ou une fois que vous êtes déjà connecté ?
- Êtes-vous en **Wi-Fi à domicile, en partage de connexion, ou sur un réseau public** ?

Ne posez qu'une de ces questions à la fois ; vous en avez rarement besoin des trois.

## Symptôme : « Échec de l'authentification » à la connexion
1. Confirmez que l'identifiant est votre e-mail professionnel complet, pas le nom court.
2. Ressaisissez le mot de passe manuellement — un mot de passe enregistré ou expiré
   est la cause la plus fréquente.
3. Validez l'invite MFA dans les 30 secondes ; une invite expirée est vue comme un
   échec d'authentification.
4. Si le mot de passe a été changé récemment, déconnectez-vous complètement du client
   VPN puis reconnectez-vous.

Si l'authentification échoue encore après un mot de passe confirmé correct et une
nouvelle validation MFA, le compte est peut-être verrouillé — voir
`password_reset_fr.md`.

## Symptôme : la connexion se coupe toutes les quelques minutes
1. Passez du Wi-Fi à une connexion filaire si possible.
2. Rapprochez-vous du routeur ou désactivez les autres applications gourmandes en
   bande passante.
3. Mettez à jour le client GlobalConnect vers la dernière version depuis le Software
   Center.
4. Redémarrez l'ordinateur pour vider un état d'adaptateur réseau bloqué.

## Symptôme : connecté, mais les sites internes ne chargent pas
1. Vérifiez que l'icône d'état affiche **Connecté**, pas « Connexion en cours ».
2. Essayez le portail interne par son adresse complète, pas par un favori.
3. Videz le DNS : redémarrez l'ordinateur, c'est la réinitialisation sûre et prise en
   charge.
4. Vérifiez que vous n'êtes pas sur un réseau qui bloque le trafic VPN (certains
   hôtels/cafés le font).

## Consignes de sécurité
- Ne désactivez jamais la vérification des certificats du client VPN, même si une
  invite le suggère.
- N'installez pas de VPN personnel ou tiers pour « contourner » le VPN d'entreprise.

## Quand escalader
Escaladez vers l'équipe réseau (voir `escalation_policy_fr.md`) si :
- L'authentification échoue après un mot de passe et une MFA confirmés corrects.
- La connexion se coupe à répétition sur un réseau filaire réputé bon.
- Plusieurs personnes du même site signalent le VPN en panne en même temps (panne
  possible).
Indiquez le texte exact de l'erreur, le type de réseau et la version du client dans
le ticket.
