"""
bot.py — Bot RdvPermis V5 FINAL
FIX : boucle infinie quand /crenodispo/date retourne une date <= curseur déjà traité
"""
import asyncio
import json
import logging
import aiohttp
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from yarl import URL

logger = logging.getLogger("rdvpermis.bot")

BASE_URL     = "https://pro.permisdeconduire.gouv.fr"
API          = f"{BASE_URL}/api/v2/auto-ecole"
COOKIES_FILE = Path("cookies.json")

API_MOI             = f"{API}/employes/moi"
API_CRENODISPO_DATE = f"{API}/crenodispo/date"
API_CRENODISPO      = f"{API}/crenodispo"
API_PANIER          = f"{API}/panier"
API_PANIER_MULTIPLE = f"{API}/panier/creneaux-multiples"

CENTRES_FAVORIS = [
    {"id": "1aa3ebe5-67f4-48ff-adbe-bbb93d0f31ed", "nom": "GONESSE B"},
    {"id": "4bdb3c8a-a0f3-446c-bc15-246fb182e4b9", "nom": "ST BRICE SOUS FORET"},
    {"id": "305413f9-f3d1-47a4-9978-5cd0545c2be1", "nom": "CERGY B"},
]

PANIER_MAX = 36


# ════════════════════════════════════════════════════════════════════
#  LOGIN CDP
# ════════════════════════════════════════════════════════════════════

async def sauvegarder_session():
    from playwright.async_api import async_playwright

    print("\n" + "="*60)
    print("  MODE CONNEXION MANUELLE (CDP)")
    print("="*60)
    print("""
  ÉTAPE 1 — Lance Chrome avec ce raccourci (PowerShell) :

    & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" `
      --remote-debugging-port=9222 `
      --user-data-dir="C:\\chrome_bot"

  ÉTAPE 2 — Connecte-toi sur :
    https://pro.permisdeconduire.gouv.fr/crenodispo

  ÉTAPE 3 — Une fois sur CrenoDispo, reviens ici et appuie ENTRÉE.
""")

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page    = context.pages[0] if context.pages else await context.new_page()
        print("  ✅ Connecté au Chrome via CDP")
    except Exception as e:
        print(f"\n  ❌ Impossible de se connecter au Chrome : {e}")
        print("  → Vérifie que Chrome est lancé avec --remote-debugging-port=9222")
        await pw.stop()
        return False

    await asyncio.to_thread(input, "  👉 Appuie sur ENTRÉE une fois connecté sur CrenoDispo...")

    print("\n  💾 Extraction des cookies...")
    cookies = await context.cookies()
    COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
    print(f"  ✅ {len(cookies)} cookie(s) sauvegardés dans {COOKIES_FILE}")
    print("  ➡️  Lance maintenant : python main.py\n")

    await pw.stop()
    return True


# ════════════════════════════════════════════════════════════════════
#  BOT PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class BotRdvPermis:
    def __init__(self, config):
        self.cfg        = config
        self.search_cfg = config["search"]
        self.bot_cfg    = config["bot"]
        self.notif_cfg  = config.get("notifications", {})
        self.session: Optional[aiohttp.ClientSession] = None
        self.nb_panier  = 0
        self.places_reservees = []

    async def demarrer(self):
        self.session = aiohttp.ClientSession(
            headers={
                "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept":          "application/json, text/plain, */*",
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Content-Type":    "application/json",
                "Origin":          BASE_URL,
                "Referer":         f"{BASE_URL}/crenodispo",
                "sec-fetch-dest":  "empty",
                "sec-fetch-mode":  "cors",
                "sec-fetch-site":  "same-origin",
            },
            cookie_jar=aiohttp.CookieJar()
        )
        logger.info("Session HTTP créée")

    async def arreter(self):
        try:
            if self.session and not self.session.closed:
                await self.session.close()
        except Exception:
            pass
        logger.info("Session fermée")

    async def se_connecter(self) -> bool:
        if not COOKIES_FILE.exists():
            logger.error(f"❌ {COOKIES_FILE} introuvable → python main.py --login")
            return False

        cookies = json.loads(COOKIES_FILE.read_text())
        for c in cookies:
            domain = c.get("domain", "").lstrip(".")
            if not domain:
                continue
            try:
                self.session.cookie_jar.update_cookies(
                    {c["name"]: c["value"]},
                    response_url=URL(f"https://{domain}")
                )
            except Exception:
                pass

        logger.info(f"  Cookies chargés depuis {COOKIES_FILE}")
        return await self._verifier_session()

    async def _verifier_session(self) -> bool:
        try:
            async with self.session.get(API_MOI, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    data = await r.json()
                    logger.info(
                        f"  ✅ Session valide — "
                        f"{data.get('prenom')} {data.get('nom')} "
                        f"({data.get('autoEcole', {}).get('nom')})"
                    )
                    return True
                logger.warning(f"  Session invalide — HTTP {r.status}")
                return False
        except Exception as e:
            logger.error(f"  Erreur vérification : {e}")
            return False

    async def get_panier(self) -> int:
        try:
            async with self.session.get(
                f"{API_PANIER}?inclureEstCandidatObligatoire=true",
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    self.nb_panier = len(data.get("elementsDuPanier", []))
                    logger.info(f"🛒 Panier : {self.nb_panier}/{PANIER_MAX}")
        except Exception as e:
            logger.debug(f"Erreur panier : {e}")
        return self.nb_panier

    # ════════════════════════════════════════════════════════════════
    #  SCAN D'UN CENTRE — cascade avec anti-boucle infinie
    # ════════════════════════════════════════════════════════════════

    async def _scan_centre_unique(self, centre: dict):
        if self.nb_panier >= PANIER_MAX:
            return

        date_min  = self.search_cfg.get("date_min", date.today().isoformat())
        date_max  = self.search_cfg.get("date_max", (date.today() + timedelta(days=90)).isoformat())
        groupe    = self.search_cfg.get("groupe_permis", "B")
        centre_id = centre["id"]
        nom       = centre["nom"]
        cursor    = date_min
        derniere_date_traitee = None   # ← FIX anti-boucle infinie

        while cursor <= date_max and self.nb_panier < PANIER_MAX:
            try:
                # ── Étape 1 : prochaine date avec créneaux ───────────
                async with self.session.get(
                    API_CRENODISPO_DATE,
                    params={"centres-ids": centre_id, "groupe-permis": groupe, "date": cursor},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as r:
                    if r.status == 429:
                        logger.debug(f"[{nom}] 429 rate limit — pause 2s")
                        await asyncio.sleep(2)
                        continue
                    if r.status != 200:
                        break
                    prochaine = await r.json()

                # Validation de la date retournée
                if not isinstance(prochaine, str) or not prochaine:
                    logger.debug(f"[{nom}] Plus aucune date disponible à partir de {cursor}")
                    break

                if prochaine > date_max:
                    logger.debug(f"[{nom}] Date {prochaine} dépasse date_max")
                    break

                # ── FIX BOUCLE INFINIE ───────────────────────────────
                # L'API retourne toujours la 1ère date dispo globale, pas relative au cursor.
                # Si prochaine < cursor → on a déjà tout scanné → BREAK
                if prochaine < cursor:
                    logger.debug(f"[{nom}] Plus rien après {cursor}")
                    break

                # ── Étape 2 : créneaux de cette date ─────────────────
                async with self.session.get(
                    API_CRENODISPO,
                    params={"centres-ids": centre_id, "groupe-permis": groupe, "date": prochaine},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as r:
                    if r.status == 429:
                        await asyncio.sleep(2)
                        continue
                    if r.status != 200:
                        derniere_date_traitee = prochaine
                        cursor = (date.fromisoformat(prochaine) + timedelta(days=1)).isoformat()
                        continue
                    data = await r.json()
                    ids  = [x["id"] for x in data if "id" in x] if isinstance(data, list) else []

                derniere_date_traitee = prochaine  # Marquer comme traité

                if not ids:
                    cursor = (date.fromisoformat(prochaine) + timedelta(days=1)).isoformat()
                    continue

                logger.info(f"  ⚡ [{nom}] {prochaine} → {len(ids)} créneau(x) — réservation...")

                # ── Étape 3 : réservation ────────────────────────────
                places_restantes = PANIER_MAX - self.nb_panier
                lot = ids[:min(10, places_restantes)]

                async with self.session.post(
                    f"{API_PANIER_MULTIPLE}?inclureEstCandidatObligatoire=true",
                    json={"creneauxId": lot},
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as r:
                    body = ""
                    try:
                        body = str(await r.json())
                    except Exception:
                        body = await r.text()

                    if r.status in (200, 201, 204):
                        self.nb_panier += len(lot)
                        self.places_reservees.append({"centre": nom, "date": prochaine, "nb": len(lot)})
                        logger.info(
                            f"  ✅✅ [{nom}] {prochaine} — {len(lot)} place(s) réservée(s) ! "
                            f"Panier : {self.nb_panier}/{PANIER_MAX}"
                        )
                        await self._notifier(nom, prochaine, len(lot))
                    elif r.status == 422 and "SEUIL_ATTEINT" in body:
                        logger.warning(f"  ⚠️ [{nom}] Seuil formateur atteint")
                    elif r.status in (401, 403):
                        raise Exception("SESSION_EXPIREE")
                    else:
                        logger.debug(f"  [{nom}] Réservation HTTP {r.status}")

                # Étape 4 : avancer au lendemain
                cursor = (date.fromisoformat(prochaine) + timedelta(days=1)).isoformat()

            except Exception as e:
                if "SESSION_EXPIREE" in str(e):
                    raise
                break

    # ════════════════════════════════════════════════════════════════
    #  BOUCLE PRINCIPALE — 3 centres en parallèle
    # ════════════════════════════════════════════════════════════════

    async def boucle(self):
        interval = self.bot_cfg.get("interval_secondes", 5)
        logger.info(
            f"🤖 Bot démarré — 3 centres en parallèle | intervalle {interval}s | "
            f"{self.search_cfg.get('date_min')} → {self.search_cfg.get('date_max')}"
        )
        await self.get_panier()

        iteration = 0
        while True:
            iteration += 1

            if self.nb_panier >= PANIER_MAX:
                logger.info(f"🏁 Panier plein ({PANIER_MAX}/{PANIER_MAX}) — pause 60s")
                await asyncio.sleep(60)
                await self.get_panier()
                continue

            if iteration % 5 == 1:
                logger.info(
                    f"--- It.#{iteration} | Panier {self.nb_panier}/{PANIER_MAX} | "
                    f"{__import__('datetime').datetime.now().strftime('%H:%M:%S')} ---"
                )

            try:
                await asyncio.gather(
                    self._scan_centre_unique(CENTRES_FAVORIS[0]),
                    self._scan_centre_unique(CENTRES_FAVORIS[1]),
                    self._scan_centre_unique(CENTRES_FAVORIS[2]),
                )
            except Exception as e:
                if "SESSION_EXPIREE" in str(e):
                    logger.error("⚠️ Session expirée — relance : python main.py --login")
                    return
                logger.error(f"Erreur boucle : {e}")

            delai = interval + random.uniform(-0.5, 1.5)
            await asyncio.sleep(max(1, delai))

    async def _notifier(self, centre: str, jour: str, nb: int):
        try:
            from notifier import notifier as notify
            await notify(self.notif_cfg, [{"centre": centre, "date": jour, "nb": nb}], {})
        except Exception:
            pass