"""
bot.py — Bot RdvPermis V5 FINAL — Version complète avec option d'attente passive de Rush programmée

Nouvelles fonctionnalités :
  1. Filtre horaire configurable (heure_min / heure_max)
  2. Quota de réservations (quota_max)
  3. Mode "consecutifs" → priorise les créneaux qui se suivent
  4. Mode attente passive intelligente ("rush_auto_reload") :
     Le bot reste totalement silencieux avant l'heure cible (ex: 15h00) pour éviter tout ban,
     tout en entretenant la session (Anti-AFK), puis se réveille à la milliseconde près.
"""
import asyncio
import json
import logging
import aiohttp
import random
from datetime import datetime as dt, date, timedelta
from pathlib import Path
from typing import Optional
from yarl import URL

logger = logging.getLogger("rdvpermis.bot")

# Couleurs terminal
VERT    = "\033[92m"
ROUGE   = "\033[91m"
JAUNE   = "\033[93m"
RESET   = "\033[0m"
GRAS    = "\033[1m"

BASE_URL     = "https://pro.permisdeconduire.gouv.fr"
API          = f"{BASE_URL}/api/v2/auto-ecole"
COOKIES_FILE = Path("cookies.json")

API_MOI             = f"{API}/employes/moi"
API_CRENODISPO_DATE = f"{API}/crenodispo/date"
API_CRENODISPO      = f"{API}/crenodispo"
API_PANIER          = f"{API}/panier"
API_PANIER_SIMPLE   = f"{API}/panier/creneaux"
API_PANIER_MULTIPLE = f"{API}/panier/creneaux-multiples"

# ── Centres par département ────────────────────────────────────────────────
CENTRES_95 = [
    {"id": "1aa3ebe5-67f4-48ff-adbe-bbb93d0f31ed", "nom": "GONESSE B",        "dept": "095"},
    {"id": "305413f9-f3d1-47a4-9978-5cd0545c2be1", "nom": "CERGY B",          "dept": "095"},
    {"id": "e93b6e32-8623-4d61-a16f-f059f7df0f9f", "nom": "ARGENTEUIL B",     "dept": "095"},
]

CENTRES_93 = [
    {"id": "fe9885bf-1a5e-4646-8654-c559431dba75", "nom": "ST BRICE B",       "dept": "093"},
    {"id": "a83a154b-bda4-45ef-bded-2466977a151e", "nom": "BOBIGNY B",        "dept": "093"},
    {"id": "4154a134-e1a0-4518-998d-18e3279cdd2e", "nom": "ROSNY B",          "dept": "093"},
]

CENTRES_FAVORIS = [
    {"id": "1aa3ebe5-67f4-48ff-adbe-bbb93d0f31ed", "nom": "GONESSE B",        "dept": "095"},
    {"id": "fe9885bf-1a5e-4646-8654-c559431dba75", "nom": "ST BRICE B",       "dept": "093"},
    {"id": "305413f9-f3d1-47a4-9978-5cd0545c2be1", "nom": "CERGY B",          "dept": "095"},
    {"id": "e93b6e32-8623-4d61-a16f-f059f7df0f9f", "nom": "ARGENTEUIL B",     "dept": "095"},
    {"id": "a83a154b-bda4-45ef-bded-2466977a151e", "nom": "BOBIGNY B",         "dept": "093"},
    {"id": "4154a134-e1a0-4518-998d-18e3279cdd2e", "nom": "ROSNY B",           "dept": "093"},
]

TOUS_LES_CENTRES = CENTRES_95 + CENTRES_93
PANIER_MAX = 36


async def sauvegarder_session():
    from playwright.async_api import async_playwright
    print("\n" + "="*60)
    print("  MODE CONNEXION MANUELLE (CDP)")
    print("="*60)
    print("""
  ÉTAPE 1 — Lance Chrome (PowerShell) :
    & "C:\Program Files\Google\Chrome\Application\chrome.exe" `
      --remote-debugging-port=9222 `
      --user-data-dir="C:\chrome_bot"

  ÉTAPE 2 — Connecte-toi sur :
    https://pro.permisdeconduire.gouv.fr/crenodispo

  ÉTAPE 3 — Une fois sur CrenoDispo → reviens ici et appuie ENTRÉE.
""")
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page    = context.pages[0] if context.pages else await context.new_page()
        print("  ✅ Connecté au Chrome via CDP")
    except Exception as e:
        print(f"\n  ❌ Chrome introuvable : {e}")
        print("  → Lance Chrome avec --remote-debugging-port=9222")
        await pw.stop()
        return False

    await asyncio.to_thread(input, "  👉 Appuie sur ENTRÉE une fois sur CrenoDispo...")
    cookies = await context.cookies()
    COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
    print(f"  ✅ {len(cookies)} cookie(s) sauvegardés dans {COOKIES_FILE}")
    print("  ➡️  Lance : python main.py\n")
    await pw.stop()
    return True


def _filtre_heure(heure_str: str, heure_min: str, heure_max: str) -> bool:
    if not heure_str:
        return True
    try:
        h     = dt.strptime(heure_str[:5], "%H:%M").time()
        h_min = dt.strptime(heure_min, "%H:%M").time()
        h_max = dt.strptime(heure_max, "%H:%M").time()
        return h_min <= h <= h_max
    except Exception:
        return True


def _filtrer_creneaux(creneaux: list, heure_min: str, heure_max: str,
                       max_par_creneau: int, mode: str) -> list:
    STATUTS_BLOQUES = {"RÉSERVÉ_PAR_AUTRE_AUTO_ÉCOLE", "RÉSERVÉ", "ANNULÉ"}
    filtres = []
    for c in creneaux:
        statut = c.get("statutDeReservation", "")
        if statut in STATUTS_BLOQUES:
            continue
        debut = c.get("dateHeureDebut", "")
        heure = debut[11:16] if len(debut) >= 16 else ""
        if _filtre_heure(heure, heure_min, heure_max):
            filtres.append(c)

    if not filtres:
        return []

    filtres.sort(key=lambda c: c.get("dateHeureDebut", ""))

    if max_par_creneau > 0:
        compteur = {}
        result = []
        for c in filtres:
            heure = c.get("dateHeureDebut", "")[11:16]
            nb = compteur.get(heure, 0)
            if nb < max_par_creneau:
                compteur[heure] = nb + 1
                result.append(c)
        filtres = result

    if mode == "consecutifs" and len(filtres) > 1:
        meilleur_bloc = []
        bloc_courant  = [filtres[0]]

        for i in range(1, len(filtres)):
            prec = filtres[i - 1]
            curr = filtres[i]
            try:
                fin_prec  = dt.fromisoformat(prec.get("dateHeureFin", "").replace("Z",""))
                debut_curr = dt.fromisoformat(curr.get("dateHeureDebut","").replace("Z",""))
                diff_min = abs((debut_curr - fin_prec).total_seconds()) / 60
                if diff_min <= 2:
                    bloc_courant.append(curr)
                else:
                    if len(bloc_courant) > len(meilleur_bloc):
                        meilleur_bloc = bloc_courant
                    bloc_courant = [curr]
            except Exception:
                bloc_courant.append(curr)

        if len(bloc_courant) > len(meilleur_bloc):
            meilleur_bloc = bloc_courant

        if meilleur_bloc:
            filtres = meilleur_bloc

    return filtres


class BotRdvPermis:
    def __init__(self, config):
        self.cfg         = config
        self.search_cfg  = config["search"]
        self.resa_cfg    = config.get("reservation", {})
        self.bot_cfg     = config["bot"]
        self.notif_cfg   = config.get("notifications", {})
        self.session: Optional[aiohttp.ClientSession] = None
        self.nb_panier   = 0
        self.nb_reserves = 0
        self.places_reservees = []
        self.jours_reserves: dict = {}

    @property
    def quota_max(self) -> int:
        return self.resa_cfg.get("quota_max", 36)

    @property
    def heure_min(self) -> str:
        return self.search_cfg.get("heure_min", "00:00")

    @property
    def heure_max(self) -> str:
        return self.search_cfg.get("heure_max", "23:59")

    @property
    def rush_enabled(self) -> bool:
        return self.bot_cfg.get("rush_auto_reload", True)

    @property
    def rush_heure(self) -> str:
        return self.bot_cfg.get("rush_heure", "15:00")

    @property
    def quota_atteint(self) -> bool:
        if self.quota_max < 0:
            return False
        return self.nb_reserves >= self.quota_max

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
                    logger.info(f"🛒 Panier : {self.nb_panier}/{PANIER_MAX} | Quota : {self.nb_reserves}/{self.quota_max if self.quota_max > 0 else '∞'}")
        except Exception as e:
            logger.debug(f"Erreur panier : {e}")
        return self.nb_panier

    async def _reserver_un(self, creneau_id: str, nom_centre: str, heure: str,
                            max_tentatives: int = 3) -> str:
        for tentative in range(1, max_tentatives + 1):
            try:
                async with self.session.post(
                    f"{API_PANIER_SIMPLE}?inclureEstCandidatObligatoire=true",
                    json={"creneauId": creneau_id},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    body = {}
                    try:
                        body = await r.json()
                    except Exception:
                        body = {"raw": await r.text()}
                    body_str = str(body)

                    if r.status == 201:
                        self.nb_panier   += 1
                        self.nb_reserves += 1
                        msg = (
                            f"{VERT}{GRAS}"
                            f"✅✅ RÉSERVÉ ! [{nom_centre}] {heure} "
                            f"— Panier: {self.nb_panier}/{PANIER_MAX} "
                            f"| Quota: {self.nb_reserves}/{self.quota_max if self.quota_max > 0 else '∞'}"
                            f"{RESET}"
                        )
                        logger.info(msg)
                        return "ok"

                    if r.status == 409:
                        logger.debug(f"  [{nom_centre}] {heure} → 409 déjà dans un panier")
                        return "deja_panier"

                    if r.status == 422:
                        logger.debug(f"  [{nom_centre}] {heure} → 422 déjà pris")
                        return "deja_pris"

                    if r.status == 400:
                        if "SEUIL_ATTEINT" in body_str:
                            logger.warning(f"  {JAUNE}⚠️ Seuil formateur atteint{RESET}")
                            return "seuil"
                        logger.warning(f"  {JAUNE}⚠️ Panier plein ou erreur 400{RESET}")
                        return "panier_plein"

                    if r.status in (401, 403):
                        logger.error(f"  {ROUGE}🔒 Session expirée{RESET}")
                        return "session_expiree"

                    if r.status == 429:
                        delai = min(2 ** tentative, 30)
                        logger.warning(f"  {JAUNE}⏳ Rate limit (429) — pause {delai}s{RESET}")
                        await asyncio.sleep(delai)
                        continue

                    if r.status >= 500:
                        delai = min(2 ** tentative, 15)
                        logger.warning(f"  ⚠️ Erreur serveur {r.status} — retry dans {delai}s")
                        await asyncio.sleep(delai)
                        continue

                    logger.info(f"  ⚠️ HTTP {r.status} non géré : {body_str[:100]}")
                    return "erreur"

            except asyncio.TimeoutError:
                logger.warning(f"  Timeout tentative {tentative}/{max_tentatives}")
                if tentative < max_tentatives:
                    await asyncio.sleep(2 ** tentative)
            except Exception as e:
                logger.error(f"  Erreur réseau : {e}")
                return "erreur"

        return "erreur"

    async def _scan_une_date(self, centre: dict, jour: str, groupe: str, mode: str, max_cts: int):
        """
        Scanne un centre pour UN jour précis : récupère les créneaux, filtre,
        et réserve si besoin. Gère elle-même les retries sur 429 (max 15
        tentatives) avant d'abandonner ce jour et de passer au suivant —
        pour éviter qu'un seul jour bloque indéfiniment tout le scan.
        """
        nom = centre["nom"]
        cid = centre["id"]

        data = None
        for _tentative in range(15):
            if self.quota_atteint or self.nb_panier >= PANIER_MAX:
                return
            await asyncio.sleep(0.1)
            async with self.session.get(
                API_CRENODISPO,
                params={"centres-ids": cid, "groupe-permis": groupe, "date": jour},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                if r.status == 429:
                    delai = random.randint(3, 7)
                    logger.warning(f"  ⏳ Rate limit (429) pendant scan — pause {delai}s")
                    await asyncio.sleep(delai)
                    continue
                if r.status != 200:
                    return
                data = await r.json()
            break
        else:
            logger.debug(f"[{nom}] {jour} → abandon après trop de 429")
            return

        if self.jours_reserves.get((cid, jour), 0) >= 2:
            return

        if not isinstance(data, list) or not data:
            return

        creneaux_filtres = _filtrer_creneaux(data, self.heure_min, self.heure_max, max_cts, mode)
        if not creneaux_filtres:
            return

        for creneau in creneaux_filtres:
            if self.quota_atteint or self.nb_panier >= PANIER_MAX:
                break

            creneau_id = creneau["id"]
            heure      = creneau.get("dateHeureDebut", "")[11:16]

            resultat = await self._reserver_un(creneau_id, nom, heure)

            if resultat == "session_expiree":
                raise Exception("SESSION_EXPIREE")
            elif resultat in ("panier_plein", "seuil"):
                return

            if resultat == "ok":
                self.jours_reserves[(cid, jour)] = self.jours_reserves.get((cid, jour), 0) + 1
                await self._notifier(nom, jour, heure)

            if self.quota_atteint:
                return

    async def _scan_centre_unique(self, centre: dict):
        if self.quota_atteint or self.nb_panier >= PANIER_MAX:
            return

        groupe  = self.search_cfg.get("groupe_permis", "B")
        mode    = self.resa_cfg.get("mode", "tous")
        max_cts = self.resa_cfg.get("max_par_creneau", -1)
        nom     = centre["nom"]

        # ── Mode "dates précises" : liste explicite de jours non-contigus ──
        dates_specifiques = self.search_cfg.get("dates_specifiques") or []
        if dates_specifiques:
            aujourdhui = date.today().isoformat()
            jours = sorted({d for d in dates_specifiques if d >= aujourdhui})
            for jour in jours:
                if self.quota_atteint or self.nb_panier >= PANIER_MAX:
                    return
                try:
                    await self._scan_une_date(centre, jour, groupe, mode, max_cts)
                except Exception as e:
                    if "SESSION_EXPIREE" in str(e):
                        raise
                    logger.debug(f"[{nom}] Erreur sur {jour} : {e}")
            return

        # ── Mode "plage continue" : comportement historique date_min → date_max ──
        date_min = self.search_cfg.get("date_min", date.today().isoformat())
        date_max = self.search_cfg.get("date_max", (date.today() + timedelta(days=120)).isoformat())
        cursor   = max(date_min, date.today().isoformat())

        while cursor <= date_max and not self.quota_atteint and self.nb_panier < PANIER_MAX:
            try:
                await self._scan_une_date(centre, cursor, groupe, mode, max_cts)
            except Exception as e:
                if "SESSION_EXPIREE" in str(e):
                    raise
                logger.debug(f"[{nom}] Erreur : {e}")
                break
            cursor = (date.fromisoformat(cursor) + timedelta(days=1)).isoformat()

    async def boucle(self):
        interval = self.bot_cfg.get("interval_secondes", 5)
        centres  = self._get_centres_actifs()

        logger.info(
            f"🤖 Bot initialisé | {len(centres)} centre(s) cible(s) | "
            f"Plage horaire : {self.heure_min}–{self.heure_max} | "
            f"Quota maximal : {self.quota_max if self.quota_max > 0 else '∞'}"
        )
        await self.get_panier()

        try:
            r_hour, r_min = map(int, self.rush_heure.split(":"))
        except Exception:
            logger.warning("⚠️ Format de rush_heure invalide, repli sur 15:00")
            r_hour, r_min = 15, 0

        iteration = 0
        while True:
            iteration += 1

            if self.quota_atteint:
                logger.info(f"{VERT}{GRAS}🏁 Quota atteint — bot terminé{RESET}")
                return

            if self.nb_panier >= PANIER_MAX:
                logger.info(f"🛑 Panier plein — pause 60s")
                await asyncio.sleep(60)
                await self.get_panier()
                continue

            # ─── GESTION DE L'ATTENTE PASSIVE SÉCURISÉE AVANT LE RUSH ───
            maintenant = dt.now()
            cible_rush = maintenant.replace(hour=r_hour, minute=r_min, second=0, microsecond=0)
            
            if self.rush_enabled and maintenant < cible_rush:
                temps_restant = (cible_rush - maintenant).total_seconds()
                minutes_restantes = int(temps_restant // 60)
                secondes_restantes = int(temps_restant % 60)
                
                if iteration % 6 == 1 or temps_restant <= 15:
                    logger.info(
                        f"🎧 {JAUNE}Mode attente passive actif{RESET} | "
                        f"Réveil prévu à {self.rush_heure} | "
                        f"Temps restant : {minutes_restantes}m {secondes_restantes}s"
                    )
                
                # Attente par tranches courtes (max 10s) pour intercepter le rush à la seconde près
                await asyncio.sleep(min(10, temps_restant))
                
                # Toutes les 3 minutes d'attente passive (18 itérations de 10s), on actualise le panier (Anti-AFK discret)
                if iteration % 18 == 0:
                    await self.get_panier()
                continue

            # ─── DÉCLENCHEMENT DU SCAN (AU RUSH OU EN MODE NORMAL CONTINU) ───
            if iteration % 10 == 1 or (self.rush_enabled and cible_rush <= maintenant <= cible_rush + timedelta(seconds=10)):
                logger.info(
                    f"⚡ {VERT}{GRAS}RUSH ACTIF{RESET} --- It.#{iteration} | Panier {self.nb_panier}/{PANIER_MAX} | "
                    f"Réservés {self.nb_reserves}/{self.quota_max if self.quota_max > 0 else '∞'} | "
                    f"{dt.now().strftime('%H:%M:%S')} ---"
                )

            try:
                for c in centres:
                    await self._scan_centre_unique(c)
                    if self.quota_atteint:
                        break
            except Exception as e:
                if "SESSION_EXPIREE" in str(e):
                    logger.error(f"{ROUGE}⚠️ Session expirée — relance : python main.py --login{RESET}")
                    return
                logger.error(f"Erreur boucle : {e}")

            # Rythme de sommeil dynamique après un scan complet
            maintenant_apres_scan = dt.now()
            fin_rush = cible_rush + timedelta(minutes=5)
            
            if self.rush_enabled and (cible_rush <= maintenant_apres_scan <= fin_rush):
                # Fenêtre critique (les 5 premières minutes du rush) : on enchaîne instantanément
                await asyncio.sleep(random.uniform(0.4, 0.8))
            else:
                # Mode normal continu ou après la fin de la tempête du rush
                await asyncio.sleep(interval + random.uniform(1, 3))

    def _get_centres_actifs(self) -> list:
        filtre = self.search_cfg.get("centres", [])
        dept   = self.search_cfg.get("dept")

        if dept == "95":
            pool = CENTRES_95
        elif dept == "93":
            pool = CENTRES_93
        elif filtre:
            pool = TOUS_LES_CENTRES
        else:
            pool = CENTRES_FAVORIS

        if not filtre:
            return pool
        return [c for c in pool if any(f.lower() in c["nom"].lower() for f in filtre)]

    async def _notifier(self, centre: str, jour: str, heure: str):
        try:
            from notifier import notifier as notify
            await notify(self.notif_cfg, [{"centre": centre, "date": jour, "heure": heure, "nb": 1}], {})
        except Exception:
            pass