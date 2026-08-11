"""
notifier.py — Notifications (son, Telegram, Email)
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

logger = logging.getLogger("rdvpermis.notifier")


def bip_sonore(nb=5):
    try:
        import sys, time
        for _ in range(nb):
            sys.stdout.write("\a")
            sys.stdout.flush()
            time.sleep(0.2)
    except Exception:
        pass


async def envoyer_telegram(token, chat_id, message):
    try:
        import aiohttp
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json={"chat_id": chat_id, "text": message},
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    logger.info("📲 Telegram envoyé")
    except Exception as e:
        logger.warning(f"Telegram erreur : {e}")


def envoyer_email(cfg, sujet, corps):
    try:
        msg = MIMEMultipart()
        msg["From"]    = cfg["expediteur"]
        msg["To"]      = cfg["destinataire"]
        msg["Subject"] = sujet
        msg.attach(MIMEText(corps, "html"))
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as srv:
            srv.starttls()
            srv.login(cfg["expediteur"], cfg["mot_de_passe_app"])
            srv.sendmail(cfg["expediteur"], cfg["destinataire"], msg.as_string())
        logger.info("📧 Email envoyé")
    except Exception as e:
        logger.error(f"Email erreur : {e}")


async def notifier(config, creneaux, candidat):
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    nb  = creneaux[0].get("nb", len(creneaux)) if creneaux else 0
    date = creneaux[0].get("date","?") if creneaux else "?"
    centre = creneaux[0].get("centre","?") if creneaux else "?"

    msg = (
        f"🚗 PLACES RÉSERVÉES !\n\n"
        f"{nb} place(s) ajoutée(s) au panier\n"
        f"Date   : {date}\n"
        f"Centre : {centre}\n"
        f"Heure  : {now}"
    )

    if config.get("son_local"):
        bip_sonore()

    tg = config.get("telegram", {})
    if tg.get("active") and tg.get("bot_token"):
        await envoyer_telegram(tg["bot_token"], tg["chat_id"], msg)

    em = config.get("email", {})
    if em.get("active"):
        envoyer_email(em, f"[RdvPermis] {nb} place(s) réservée(s) !", msg.replace("\n","<br>"))
