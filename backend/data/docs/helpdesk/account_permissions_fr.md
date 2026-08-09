# Accès aux comptes et permissions

Couvre les demandes d'accès aux lecteurs partagés, aux applications et aux listes de
diffusion. L'accès est accordé selon le **moindre privilège** : chacun obtient le
minimum nécessaire à son rôle, et les ressources sensibles exigent toujours
l'approbation du manager.

## Comment demander un accès
1. Identifiez la ressource exacte — le chemin du dossier, le nom de l'application ou de
   la liste, pas juste « les trucs de la finance ».
2. Soumettez la demande via le Portail d'accès à `access.acteek.local`, ou demandez à
   l'assistant d'ouvrir un ticket avec les détails.
3. Précisez la raison métier et la durée d'accès nécessaire (permanent ou sur une
   période de projet définie).

## Circuit d'approbation
- Ressources d'équipe standard : approuvées par votre responsable hiérarchique.
- Ressources sensibles (finance, RH, paie, systèmes de production) : approuvées par le
  **propriétaire** de la ressource, en plus de votre manager.
- L'accès est revu chaque trimestre ; les accès inutilisés sont retirés
  automatiquement.

## Identité du demandeur
L'assistant confirme qui demande et pour quelle ressource, mais il n'accorde **pas**
l'accès lui-même et n'approuve **pas** à la place d'un manager. Les approbations se
font dans le Portail d'accès, par l'approbateur nommé, en laissant une trace d'audit.

## Cas fréquents
- **Nouvel arrivant sans une application :** vérifiez que l'ensemble d'accès standard
  du rôle a bien été appliqué ; demandez les extras via le portail.
- **Changement d'équipe :** les anciens accès ne sont pas repris par défaut —
  demandez les ressources de la nouvelle équipe et laissez la revue trimestrielle
  retirer les anciennes.
- **Boîte partagée ou liste de diffusion :** demandez via le portail ; le
  propriétaire de la liste approuve.

## Consignes de sécurité
- N'accordez jamais un accès sur la seule base de « mon manager a dit que c'est bon » —
  le manager l'approuve dans le portail, sur trace.
- Ne partagez jamais vos propres identifiants pour que quelqu'un d'autre utilise votre
  accès ; cela rompt le moindre privilège et constitue une violation de la politique
  (voir `security_policy_fr.md`).

## Quand escalader
Escaladez (voir `escalation_policy_fr.md`) si le propriétaire de la ressource est
inconnu, si l'accès est nécessaire en urgence pour un incident, ou si une demande
accorderait de larges droits d'administration — ceux-ci font l'objet d'une revue
supplémentaire.
