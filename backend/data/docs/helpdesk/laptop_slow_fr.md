# Ordinateur portable lent ou qui ne répond pas

Un ordinateur lent vient le plus souvent de trop d'applications ouvertes, d'un disque
presque plein, d'une mise à jour en attente ou — plus rarement — d'un logiciel
malveillant. Faites d'abord les étapes simples et sans risque, et n'escaladez que si
les performances restent mauvaises ensuite.

## Commencez ici : identifiez d'abord le mode d'échec
Ne déroulez PAS une liste générique. Posez d'abord UNE question, puis suivez la
branche correspondante :

> « Est-ce lent **tout le temps**, seulement dans une **application précise** (comme
> les appels vidéo ou un logiciel lourd), ou est-ce que ça **a commencé d'un coup**
> après une mise à jour ou un nouveau logiciel ? »

- **Lent tout le temps** → branche A
- **Seulement pendant les appels vidéo** → branche B
- **Seulement une application précise** → branche C
- **A commencé d'un coup** → branche D

## Branche A — lent tout le temps
1. **Redémarrez** — cela vide la mémoire et termine les mises à jour en attente ;
   beaucoup d'ordinateurs « lents depuis des jours » ont simplement besoin d'un
   redémarrage.
2. **Libérez de l'espace disque** — Windows ralentit fortement quand le disque système
   est presque plein. Vérifiez l'espace libre sur C:, videz la Corbeille, effacez les
   gros téléchargements et les anciennes copies locales de fichiers déjà dans le
   cloud. Visez au moins 10 % de libre.
3. **Réduisez les applications au démarrage et en arrière-plan** — ouvrez le
   Gestionnaire des tâches, triez par CPU puis Mémoire, fermez ce que vous n'utilisez
   pas (surtout les onglets de navigateur en trop), et dans l'onglet **Démarrage**
   désactivez les applications inutiles à l'ouverture de session (gardez la sécurité
   et le VPN).
4. **Lancez l'analyse antivirus gérée** si c'est encore lent (voir branche D étape 2).

## Branche B — lent seulement pendant les appels vidéo
1. Fermez les autres applications et onglets avant l'appel.
2. Désactivez le flou/effets d'arrière-plan, gourmands en CPU sur les ordinateurs plus
   anciens.
3. Utilisez une connexion filaire ou rapprochez-vous du routeur.

## Branche C — une seule application précise est lente
1. Ouvrez le **Gestionnaire des tâches** et triez par CPU, puis Mémoire, pour voir si
   cette application consomme l'essentiel des ressources.
2. Fermez les autres applications lourdes et les fenêtres de navigateur en trop pour
   lui libérer des ressources.
3. Si seule cette application est lente alors que le reste va bien, notez son nom —
   elle a peut-être besoin de son propre correctif ou d'une mise à jour ; escaladez
   avec le nom de l'application si ça persiste.

## Branche D — a commencé d'un coup (après une mise à jour ou un nouveau logiciel)
1. **Redémarrez** d'abord — une mise à jour en attente se termine souvent au
   redémarrage.
2. Lancez une **analyse complète** de l'antivirus géré depuis l'icône de la barre des
   tâches. Ne téléchargez **pas** de « nettoyeur » ou d'« optimiseur » tiers — ils ne
   sont pas approuvés et souvent dangereux.
3. Si ça a commencé juste après une installation, ce logiciel est la cause probable.

## Consignes de sécurité
- N'installez jamais d'outils d'optimisation ou de nettoyage de registre non
  approuvés.
- Ne désactivez jamais l'antivirus géré pour « accélérer les choses ».

## Quand escalader
Escaladez (voir `escalation_policy_fr.md`) si l'ordinateur reste lent après un
redémarrage, un nettoyage du disque et une analyse antivirus propre ; si l'analyse
détecte quelque chose qu'elle ne peut pas retirer ; ou si le disque est défaillant
(cliquetis, blocages fréquents). Indiquez le modèle, l'âge et ce qui le rend lent.
