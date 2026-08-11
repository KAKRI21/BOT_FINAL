# 🚗 Bot RdvPermis — Guide d'installation et d'utilisation

## Installation (5 minutes)

### 1. Prérequis
- Python 3.10+ installé
- Connexion internet

### 2. Installer les dépendances

```bash
# Cloner / copier le dossier, puis :
pip install -r requirements.txt
playwright install chromium
```

### 3. Configurer le bot

Ouvrir `config.yaml` et remplir :
- `credentials` : email + mot de passe du compte auto-école RdvPermis
- `candidates` : liste des NEPH + noms des élèves à placer
- `search` : département, centres acceptés, plage de dates
- `bot.mode` : `"auto"` (réserve seul) ou `"manuel"` (notifie seulement)
- `notifications` : Telegram ou email si souhaité (optionnel)

---

## Utilisation

### Tester la connexion d'abord
```bash
python main.py --test
```

### Lancer le bot
```bash
python main.py
```

### Mode debug (voir le navigateur)
```bash
python main.py --debug
```

### Utiliser un autre fichier config
```bash
python main.py --config ma_config.yaml
```

---

## Déploiement sur VPS (Linux)

### Installation sur Ubuntu/Debian
```bash
sudo apt update && sudo apt install python3 python3-pip -y
pip3 install -r requirements.txt
playwright install chromium
playwright install-deps chromium    # Dépendances système
```

### Lancer en arrière-plan avec screen
```bash
screen -S rdvbot
python main.py
# Ctrl+A puis D pour détacher
# screen -r rdvbot pour reprendre
```

### Ou avec systemd (service permanent)
Créer `/etc/systemd/system/rdvpermis.service` :
```ini
[Unit]
Description=Bot RdvPermis Auto-Ecole
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/rdvpermis-bot
ExecStart=/usr/bin/python3 main.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Activer :
```bash
sudo systemctl enable rdvpermis
sudo systemctl start rdvpermis
sudo systemctl status rdvpermis
```

### Voir les logs en direct
```bash
tail -f bot.log
```

---

## Notifications Telegram (recommandé pour VPS)

1. Ouvrir Telegram, chercher **@BotFather**
2. Envoyer `/newbot` et suivre les instructions → récupérer le **token**
3. Chercher **@userinfobot** → récupérer votre **chat_id**
4. Remplir dans `config.yaml` :
   ```yaml
   telegram:
     active: true
     bot_token: "1234567890:ABCdef..."
     chat_id: "987654321"
   ```

---

## Conseils

- **Intervalle recommandé** : 10-20 secondes (évite d'être bloqué)
- **Mode auto** : le bot réserve dès qu'une place correspond — idéal si vous lui faites confiance
- **Mode manuel** : le bot notifie, vous réservez vous-même — plus de contrôle
- **Screenshots** : des captures sont sauvegardées à chaque confirmation de réservation
- **Logs** : tout est enregistré dans `bot.log`

---

## Structure du projet

```
rdvpermis-bot/
├── main.py          # Point d'entrée
├── bot.py           # Moteur principal (Playwright)
├── notifier.py      # Notifications (son, Telegram, email)
├── config.yaml      # Configuration (à remplir)
├── requirements.txt # Dépendances Python
├── README.md        # Ce fichier
└── bot.log          # Logs (créé au lancement)
```
