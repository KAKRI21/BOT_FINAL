"""
test_scan.py — Scan à blanc (aucune réservation)
"""
import asyncio
import json
import time
import aiohttp
from datetime import date, timedelta
from pathlib import Path
from yarl import URL

BASE_URL     = "https://pro.permisdeconduire.gouv.fr"
API          = f"{BASE_URL}/api/v2/auto-ecole"
COOKIES_FILE = Path("cookies.json")

CENTRES = [
    {"id": "1aa3ebe5-67f4-48ff-adbe-bbb93d0f31ed", "nom": "GONESSE B"},
    {"id": "4bdb3c8a-a0f3-446c-bc15-246fb182e4b9", "nom": "ST BRICE SOUS FORET"},
    {"id": "305413f9-f3d1-47a4-9978-5cd0545c2be1", "nom": "CERGY B"},
]

DATE_MIN = date.today().isoformat()
DATE_MAX = (date.today() + timedelta(days=120)).isoformat()
GROUPE   = "B"


async def scan_centre(session, centre):
    nom       = centre["nom"]
    centre_id = centre["id"]
    cursor    = DATE_MIN
    resultats = []

    while cursor <= DATE_MAX:
        await asyncio.sleep(0.5)  # courtoisie anti-429

        try:
            t0 = time.perf_counter()
            async with session.get(
                f"{API}/crenodispo/date",
                params={"centres-ids": centre_id, "groupe-permis": GROUPE, "date": cursor},
                timeout=aiohttp.ClientTimeout(total=6)
            ) as r:
                ms1 = int((time.perf_counter() - t0) * 1000)
                if r.status == 429:
                    print(f"  [{nom}] ⏳ 429 — pause 10s")
                    await asyncio.sleep(10)
                    continue
                if r.status != 200:
                    print(f"  [{nom}] ❌ HTTP {r.status} — arrêt")
                    break
                prochaine = await r.json()

            # Pas de date disponible
            if not isinstance(prochaine, str) or not prochaine:
                print(f"  [{nom}] ✅ Aucune date disponible à partir de {cursor}")
                break

            # Date hors période
            if prochaine > DATE_MAX:
                print(f"  [{nom}] ✅ Date {prochaine} hors période — arrêt")
                break

            # ── FIX BOUCLE INFINIE ──────────────────────────────────
            # Si l'API retourne une date AVANT ou ÉGALE au cursor,
            # ça veut dire qu'il n'y a rien d'autre → on BREAK
            if prochaine < cursor:
                print(f"  [{nom}] ✅ Plus rien après {cursor} — arrêt")
                break

            # Étape 2 : créneaux de cette date
            t2 = time.perf_counter()
            async with session.get(
                f"{API}/crenodispo",
                params={"centres-ids": centre_id, "groupe-permis": GROUPE, "date": prochaine},
                timeout=aiohttp.ClientTimeout(total=6)
            ) as r:
                ms2 = int((time.perf_counter() - t2) * 1000)
                data  = await r.json() if r.status == 200 else []
                ids   = [x["id"] for x in data if "id" in x] if isinstance(data, list) else []
                heures = [x.get("dateHeureDebut","")[11:16] for x in (data or []) if x.get("dateHeureDebut")]

            if ids:
                print(f"  [{nom}] 🎯 {prochaine} → {len(ids)} créneaux [{', '.join(heures[:5])}] ({ms1}ms/{ms2}ms)")
                resultats.append({"centre": nom, "date": prochaine, "nb": len(ids)})
            else:
                print(f"  [{nom}] ⬜ {prochaine} → vide ({ms1}ms/{ms2}ms)")

            # Avancer AU LENDEMAIN DE PROCHAINE (pas du cursor)
            cursor = (date.fromisoformat(prochaine) + timedelta(days=1)).isoformat()

        except Exception as e:
            print(f"  [{nom}] 💥 {e}")
            break

    return resultats


async def main():
    print("\n" + "="*65)
    print("  TEST SCAN COMPLET — BOT RDVPERMIS V5")
    print("  (Scan à blanc — AUCUNE réservation)")
    print("="*65)

    if not COOKIES_FILE.exists():
        print("\n❌ cookies.json introuvable — python main.py --login")
        return

    cookies = json.loads(COOKIES_FILE.read_text())
    session = aiohttp.ClientSession(
        headers={
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer":         f"{BASE_URL}/crenodispo",
        },
        cookie_jar=aiohttp.CookieJar()
    )
    for c in cookies:
        domain = c.get("domain", "").lstrip(".")
        if domain:
            try:
                session.cookie_jar.update_cookies({c["name"]: c["value"]}, response_url=URL(f"https://{domain}"))
            except Exception:
                pass

    async with session.get(f"{API}/employes/moi", timeout=aiohttp.ClientTimeout(total=8)) as r:
        if r.status != 200:
            print(f"\n❌ Session invalide ({r.status}) — python main.py --login")
            await session.close()
            return
        data = await r.json()
        print(f"\n✅ {data.get('prenom')} {data.get('nom')} — {data.get('autoEcole',{}).get('nom')}")

    async with session.get(f"{API}/panier?inclureEstCandidatObligatoire=true", timeout=aiohttp.ClientTimeout(total=8)) as r:
        if r.status == 200:
            print(f"🛒 Panier : {len((await r.json()).get('elementsDuPanier', []))}/36\n")

    print(f"🔄 Scan {DATE_MIN} → {DATE_MAX} (3 centres en parallèle)...\n")
    t0 = time.perf_counter()

    tous = await asyncio.gather(
        scan_centre(session, CENTRES[0]),
        scan_centre(session, CENTRES[1]),
        scan_centre(session, CENTRES[2]),
    )

    ms = int((time.perf_counter() - t0) * 1000)
    total = sum(r["nb"] for res in tous for r in res)

    print("\n" + "="*65)
    print("  RÉSUMÉ")
    print("="*65)
    for res in tous:
        for r in res:
            print(f"  ✅ {r['centre']} — {r['date']} — {r['nb']} place(s)")
    if total == 0:
        print("  ⬜ Aucun créneau (normal hors 15h)")
    print(f"\n  ⏱️  Scan total : {ms}ms | Places : {total}")
    print()
    await session.close()


if __name__ == "__main__":
    asyncio.run(main())