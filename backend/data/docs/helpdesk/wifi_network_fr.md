# Wi-Fi et connectivité réseau

Couvre le Wi-Fi du bureau, la connexion à domicile pour le télétravail, et la
différence entre un problème de réseau local et une panne d'entreprise. Un problème de
Wi-Fi n'est pas la même chose qu'un problème de VPN — voir `vpn_troubleshooting_fr.md`
si vous vous connectez bien au Wi-Fi mais n'atteignez pas les systèmes internes.

## Commencez ici : identifiez d'abord le mode d'échec
Ne déroulez PAS une liste générique. Posez d'abord UNE question pour savoir ce qui se
passe exactement, puis suivez la branche correspondante :

> « Quand vous essayez de vous connecter, que se passe-t-il : le réseau **ACTEEK-Corp
> n'apparaît pas**, il **refuse votre mot de passe**, il **se connecte mais sans
> Internet**, il **tourne puis échoue**, ou est-ce que **d'autres réseaux échouent
> aussi** ? »

- **ACTEEK-Corp n'apparaît pas** → branche A
- **Identifiants / mot de passe refusés** → branche B
- **Connecté mais pas d'Internet / sites internes inaccessibles** → branche C
- **Tourne (« Connexion… ») puis échoue** → branche D
- **D'autres réseaux Wi-Fi échouent aussi** → branche E

Référence : connectez-vous à **ACTEEK-Corp** avec vos identifiants d'authentification
unique. **ACTEEK-Guest** est réservé aux visiteurs et n'atteint pas les systèmes
internes.

## Branche A — le réseau ACTEEK-Corp n'apparaît pas
1. Désactivez puis réactivez le Wi-Fi, puis relancez la recherche de réseaux.
2. Vérifiez que le Wi-Fi est activé et que le mode avion est désactivé.
3. Rapprochez-vous d'un point d'accès (vous êtes peut-être hors de portée).
4. Redémarrez l'ordinateur pour réinitialiser l'adaptateur sans fil.
5. Toujours absent alors que des collègues à proximité le voient → probable panne
   d'adaptateur sur l'ordinateur → escaladez vers l'équipe Postes de travail.

## Branche B — identifiants / mot de passe refusés
1. Ressaisissez soigneusement vos identifiants d'authentification unique (un mot de
   passe enregistré ou ancien est la cause habituelle).
2. Si votre mot de passe a été changé récemment ou que le compte est peut-être
   verrouillé, c'est un problème de connexion, pas de Wi-Fi — voir
   `password_reset_fr.md`.
3. Vérifiez que vous rejoignez **ACTEEK-Corp**, pas ACTEEK-Guest.

## Branche C — connecté mais pas d'Internet / sites internes inaccessibles
1. Vérifiez que l'état affiche **Connecté**, pas « Connexion » ou « Pas d'Internet ».
2. Si vous êtes à distance, c'est probablement un souci de VPN/accès interne, pas de
   Wi-Fi — voir `vpn_troubleshooting_fr.md`.
3. Redémarrez l'ordinateur pour rafraîchir la connexion réseau (réinitialisation sûre
   et prise en charge).

## Branche D — tourne (« Connexion… ») puis échoue
1. Oubliez le réseau ACTEEK-Corp, puis reconnectez-vous en ressaisissant vos
   identifiants.
2. Vérifiez que le Wi-Fi est activé et que le mode avion est désactivé.
3. Redémarrez l'ordinateur pour réinitialiser l'adaptateur sans fil.
4. Vous seul êtes concerné après ces étapes → escaladez vers l'équipe réseau ;
   plusieurs personnes au même étage concernées → probable panne de point d'accès
   (escaladez une seule fois).

## Branche E — d'autres réseaux échouent aussi
Si votre ordinateur ne se connecte à AUCUN Wi-Fi (domicile, partage de connexion,
etc.), le problème vient de l'appareil, pas du Wi-Fi d'entreprise :
1. Redémarrez l'ordinateur pour réinitialiser l'adaptateur sans fil.
2. Si tous les réseaux échouent encore, escaladez vers l'équipe Postes de travail —
   l'adaptateur ou le pilote sans fil a probablement besoin d'attention.

## Wi-Fi à domicile (télétravail) : signal faible ou qui saute
1. Rapprochez-vous du routeur ou retirez les obstacles.
2. Redémarrez le routeur et le modem domestiques (débranchez 30 secondes, rebranchez).
3. Préférez une connexion filaire pour les appels si possible.
4. Testez un autre appareil — si tout est lent, c'est probablement votre fournisseur
   d'accès, pas l'ordinateur.

## Problème local vs panne d'entreprise
- Seul votre appareil est concerné → local : suivez la branche correspondante.
- Plusieurs collègues au même site en même temps → probable panne : escaladez pour
  que ce soit suivi une seule fois, pas en plusieurs tickets.

## Consignes de sécurité
- Ne connectez jamais un ordinateur professionnel à un réseau ouvert inconnu pour
  « juste avoir Internet » sur du travail sensible ; utilisez un réseau de confiance
  et le VPN.
- Ne partagez pas les identifiants du Wi-Fi d'entreprise avec des visiteurs —
  orientez-les vers ACTEEK-Guest.

## Quand escalader
Escaladez (voir `escalation_policy_fr.md`) si le Wi-Fi d'entreprise est en panne pour
plusieurs personnes, si le réseau reste inaccessible après la bonne branche et un
redémarrage, si l'adaptateur sans fil échoue sur tous les réseaux (équipe Postes de
travail), ou si le Wi-Fi domestique d'un employé à distance fonctionne mais qu'il
n'atteint toujours pas les systèmes de l'entreprise (c'est alors probablement le VPN —
voir `vpn_troubleshooting_fr.md`).
