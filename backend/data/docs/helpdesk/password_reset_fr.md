# Réinitialisation du mot de passe et compte verrouillé

Ce document couvre la réinitialisation d'un mot de passe oublié et le déblocage d'un
compte verrouillé. L'assistant doit vérifier l'identité avant de guider une
réinitialisation et ne doit **jamais** lire, définir ou accepter un mot de passe
pendant l'appel.

## Réinitialisation en libre-service
Le plus rapide est le portail en libre-service à l'adresse interne
`reset.acteek.local` :
1. Choisissez **Mot de passe oublié**.
2. Saisissez votre e-mail professionnel.
3. Validez la vérification d'identité (invite MFA ou code de secours).
4. Définissez un nouveau mot de passe conforme à la politique : au moins 12
   caractères, mêlant lettres, chiffres et un symbole, et différent de vos 5
   derniers mots de passe.

Le nouveau mot de passe s'applique à la messagerie, au VPN et à l'authentification
unique en quelques minutes.

## Compte verrouillé après trop de tentatives
Les comptes se verrouillent automatiquement après 5 échecs de connexion, pour se
protéger contre les tentatives de devinette.
1. Attendez 15 minutes — la plupart des verrouillages temporaires se lèvent seuls.
2. Utilisez ensuite la réinitialisation en libre-service ci-dessus plutôt que de
   réessayer l'ancien mot de passe.
3. Si le compte se reverrouille aussitôt après une réinitialisation correcte, une
   application peut garder en cache l'ancien mot de passe (messagerie, client VPN) —
   déconnectez ces applications.

## Vérification d'identité
La réinitialisation en libre-service prouve déjà l'identité via la MFA. Un agent
humain ne peut effectuer une réinitialisation manuelle qu'après avoir vérifié
l'employé par le contrôle approuvé (confirmation du manager ou rappel vérifié sur le
numéro enregistré). Ne réinitialisez jamais un mot de passe sur la seule parole de
l'appelant.

## Consignes de sécurité
- Ne dites jamais à voix haute le mot de passe actuel ou temporaire d'un appelant ;
  le portail le définit de façon privée.
- N'acceptez jamais un nouveau mot de passe dicté par l'appelant ; il le définit
  lui-même dans le portail.
- Réinitialiser le mot de passe de **quelqu'un d'autre** n'est pas du libre-service :
  cela exige l'approbation du manager et passe par l'escalade.

## Quand escalader
Escaladez (voir `escalation_policy_fr.md`) si :
- Le portail en libre-service est lui-même injoignable.
- Le compte se reverrouille immédiatement après une réinitialisation correcte.
- L'identité ne peut pas être vérifiée par une méthode approuvée.
- La demande consiste à réinitialiser le compte d'une autre personne.
