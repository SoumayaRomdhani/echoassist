# Politique d'escalade et de ticketing

Quand l'assistant ne peut pas résoudre un problème depuis la base de connaissances,
quand une demande dépasse son autorité, ou quand un problème est urgent ou sensible
côté sécurité, il crée un ticket et route vers la bonne équipe humaine. Escalader est
une issue normale et positive — ne devinez jamais en cas de doute.

## Quand escalader
Escaladez si l'un de ces cas est vrai :
- Les étapes documentées n'ont pas résolu le problème (« ça ne marche toujours pas »).
- La demande sort de la base de connaissances — il n'y a pas de procédure approuvée.
- L'action nécessite une autorité que l'assistant n'a pas (réinitialisation manuelle
  de mot de passe, octroi d'accès, déblocage d'une boîte retenue pour sécurité).
- La demande est dangereuse ou contraire à la politique (voir `security_policy_fr.md`)
  — refusez l'action et escaladez le besoin sous-jacent par la voie sûre.
- Le problème est étendu (plusieurs personnes, un même site) — probablement une panne.

## Niveaux de sévérité
- **S1 – Critique :** toute une équipe ou un site est bloqué, ou un incident de
  sécurité est en cours. Routez immédiatement ; n'attendez pas plus de détails.
- **S2 – Élevé :** une personne ne peut pas faire son travail essentiel (pas de
  messagerie, pas de VPN, compte verrouillé) et le libre-service n'a pas corrigé.
- **S3 – Normal :** un problème isolé et non bloquant avec un contournement
  (ordinateur lent, demande d'accès, question de « comment faire »).

## Informations requises dans un ticket
Rassemblez le minimum pour que l'équipe humaine n'ait pas à rappeler :
- Qui est concerné (nom et, si pertinent, équipe ou site).
- Une brève description du problème et depuis quand il a commencé.
- Le message d'erreur exact, s'il y en a un.
- Ce qui a déjà été essayé (les étapes du document concerné).
- La sévérité et toute échéance.

## Routage
- Comptes, mots de passe, MFA, accès → équipe Identité.
- VPN, Wi-Fi, connectivité, pannes → équipe Réseau.
- Matériel portable, performances, remplacements → équipe Postes de travail.
- Activité suspecte, hameçonnage, appareils perdus → équipe Sécurité (S1/S2).

## Consignes de sécurité
- Ne retardez jamais une escalade de sécurité S1 pour finir un dépannage.
- Ne clôturez jamais un ticket comme résolu sans que l'employé confirme que c'est
  corrigé (voir l'étape de confirmation dans le flux helpdesk).
