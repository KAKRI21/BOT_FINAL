# Bot RdvPermis — Guide complet

Une application de bureau (Windows) qui recherche et réserve automatiquement des
créneaux d'examen du permis de conduire sur la plateforme officielle
`pro.permisdeconduire.gouv.fr`, pour les élèves de l'auto-école.

Ce guide explique **tout** : comment installer l'application, comment elle
fonctionne, et ce que fait chaque réglage.

---

## Sommaire

1. [Installation (une seule fois)](#1-installation-une-seule-fois)
2. [Utilisation au quotidien](#2-utilisation-au-quotidien)
3. [Comment fonctionne le bot](#3-comment-fonctionne-le-bot)
4. [Tous les réglages expliqués](#4-tous-les-réglages-expliqués)
5. [Notifications](#5-notifications)
6. [Sécurité](#6-sécurité)
7. [Problèmes courants](#7-problèmes-courants)

---

## 1. Installation (une seule fois)

À faire une seule fois, par la personne qui gère le bot. Les autres employés
n'auront ensuite qu'à double-cliquer sur une icône.

### Prérequis

- **Python 3.12** (ou plus récent, hors 3.14 pour l'instant) :
  https://www.python.org/downloads/ — cocher **"Add python.exe to PATH"**
  pendant l'installation.
- **Google Chrome** installé normalement sur le PC.

### Construire l'application

1. Copier tout le dossier du projet sur le PC (`bot.py`, `main.py`,
   `notifier.py`, `config.yaml`, `gui_app.py`, `build_exe.bat`...).
2. Double-cliquer sur **`build_exe.bat`**.
3. Attendre quelques minutes (installation des dépendances Python).
4. Un dossier **`dist\`** apparaît, contenant **`BotRdvPermis.exe`**.

### Déployer sur les postes

- Copier `BotRdvPermis.exe` sur le **Bureau** de chaque poste.
- Au premier lancement, l'application crée automatiquement à côté de l'exe :
  `config.yaml` (réglages), `cookies.json` (session), `bot.log` (journal),
  `chrome_profile\` (profil Chrome dédié).

**Si Windows bloque le lancement** ("Contrôle de l'application intelligent") :
voir la section [Problèmes courants](#7-problèmes-courants).

---

## 2. Utilisation au quotidien

Double-cliquer sur l'icône **BotRdvPermis** du Bureau. L'application a deux
onglets :

### Onglet Configuration

Tous les réglages de recherche/réservation/notifications (détail plus bas).
Ne pas oublier de cliquer **💾 Enregistrer la configuration** après une
modification.

### Onglet Contrôle

| Bouton | Effet |
|---|---|
| **🔑 Se connecter** | Ouvre Chrome automatiquement (aucune commande à taper). Connectez-vous sur le site dans la fenêtre qui s'ouvre, puis cliquez sur "J'ai terminé" dans l'appli — la session est alors enregistrée. À refaire si la session expire. |
| **🧪 Tester la session** | Vérifie en quelques secondes que la connexion est toujours valide, sans démarrer le bot. |
| **▶ Démarrer le bot** | Lance la recherche/réservation automatique selon la configuration enregistrée. |
| **⏹ Arrêter le bot** | Stoppe le bot à tout moment. |

Le **journal en direct** en bas de l'écran affiche tout ce que fait le bot
(créneaux trouvés, réservations, erreurs) en temps réel, avec un code couleur :
🟢 vert = succès, 🟠 orange = avertissement, 🔴 rouge = erreur.

En haut à droite : **Panier** (nombre de places mises au panier sur 36
maximum autorisées par le site) et **Réservés** (nombre de places réellement
confirmées sur le quota fixé).

---

## 3. Comment fonctionne le bot

En résumé, le bot :

1. Se connecte au site avec la session enregistrée (`cookies.json`).
2. Interroge en boucle les centres d'examen choisis, pour trouver des
   créneaux libres correspondant aux critères (dates, horaires, groupe de
   permis).
3. Dès qu'un créneau correspond, il le réserve automatiquement (jusqu'à
   atteindre le quota fixé).
4. Envoie une notification (son / Telegram / email) à chaque réservation,
   selon ce qui est activé.

### Mode veille + réveil programmé ("rush")

Sur ce type de plateforme, de nouveaux créneaux sont souvent mis en ligne à
heure fixe (ex. 15h00), avec une forte demande au moment de l'ouverture.
Si l'option **"Réveil programmé"** est activée :

- Le bot reste en **attente passive** (scans très espacés, économes) jusqu'à
  l'heure de réveil configurée.
- Dès que cette heure arrive, il passe en **mode RUSH** : scans très
  fréquents pendant la période de forte affluence, pour maximiser les
  chances de capter un créneau dès sa mise en ligne.

Si l'option est désactivée, le bot scanne en continu au même rythme, à
l'intervalle défini, toute la journée.

---

## 4. Tous les réglages expliqués

### Recherche de créneaux

| Champ | Explication |
|---|---|
| **Groupe permis** | Catégorie de permis recherchée (ex. `B` pour la voiture). |
| **Date min / Date max** | Fenêtre de dates dans laquelle chercher un créneau (format AAAA-MM-JJ). Laisser vide = pas de limite. |
| **Heure min / Heure max** | Plage horaire acceptée pour un créneau (ex. 09:00–17:00). |
| **Centres** | Cases à cocher pour choisir les centres d'examen à surveiller. Aucune case cochée = tous les centres disponibles sont surveillés. |

### Réservation

| Champ | Explication |
|---|---|
| **Quota max** | Nombre maximum de places à réserver avant que le bot s'arrête tout seul. `-1` = illimité. |
| **Max par créneau** | Limite du nombre de réservations sur un même créneau horaire. `-1` = illimité. |
| **Mode** | `tous` = réserve toutes les places disponibles trouvées ; `consecutifs` = privilégie des créneaux consécutifs (utile pour regrouper plusieurs élèves). |
| **Élèves par créneau** | Nombre d'élèves à inscrire par créneau réservé (1 à 4). |

### Fonctionnement

| Champ | Explication |
|---|---|
| **Intervalle entre scans** | Fréquence de vérification des créneaux en dehors du mode rush (en secondes). Plus bas = plus réactif, mais plus de charge sur le site. |
| **Réveil programmé (rush)** | Active/désactive le mode veille + réveil décrit ci-dessus. |
| **Heure de réveil** | Heure (HH:MM) à laquelle le bot passe en mode rush actif. |

---

## 5. Notifications

| Option | Explication |
|---|---|
| **Bip sonore local** | Émet un son sur le PC à chaque réservation réussie. |
| **Telegram** | Envoie un message sur Telegram à chaque réservation. Nécessite un token de bot Telegram et un identifiant de discussion (`chat_id`). |
| **Email** | Envoie un email à chaque réservation. Nécessite une adresse expéditrice, un mot de passe d'application (pas le mot de passe normal du compte email), un serveur SMTP et son port. |

---

## 6. Sécurité

⚠️ **Le fichier `cookies.json` contient la session de connexion active** au
site `pro.permisdeconduire.gouv.fr`. Toute personne en possession de ce
fichier peut se faire passer pour le compte connecté. En conséquence :

- Ne jamais partager ce fichier par email ou messagerie non chiffrée.
- Ne jamais le publier sur un dépôt Git **public**. S'il a déjà été publié
  par erreur, retirez-le de l'historique Git et reconnectez-vous pour
  générer une nouvelle session.
- Si l'accès semble compromis ou expire, utilisez simplement
  **🔑 Se connecter** pour régénérer une session propre.

Les identifiants Telegram/Email saisis dans l'onglet Configuration sont
stockés en clair dans `config.yaml` (à côté de l'exe) : gardez ce fichier
sur des postes de confiance uniquement.

---

## 7. Problèmes courants

**"Contrôle de l'application intelligent a bloqué..." au lancement de l'exe**
→ Normal pour un exécutable non signé. Ouvrir **Sécurité Windows** →
**Contrôle des applications et du navigateur** → **Paramètres du Contrôle de
l'application intelligent** → **Désactivé**. Relancer l'application.

**Chrome ne s'ouvre pas lors de "Se connecter"**
→ Vérifier que Google Chrome est bien installé dans
`C:\Program Files\Google\Chrome\Application\chrome.exe`. Si Chrome est
installé ailleurs, contactez la personne technique pour ajuster le chemin
dans `gui_app.py`.

**Le bot dit "Session invalide"**
→ La session a expiré. Cliquer sur **🔑 Se connecter** pour se reconnecter.

**Aucun créneau trouvé depuis longtemps**
→ Vérifier dans l'onglet Configuration que les centres, dates et horaires
choisis ne sont pas trop restrictifs, et regarder le journal pour d'éventuels
messages d'erreur.