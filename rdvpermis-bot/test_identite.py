import asyncio
import json
import aiohttp
from pathlib import Path
from yarl import URL

async def tester_identite():
    print("\n🔍 Interrogation des serveurs du gouvernement...")
    
    # 1. On charge tes cookies
    cookies_path = Path("cookies.json")
    if not cookies_path.exists():
        print("❌ Aucun cookie trouvé. Fais le --login d'abord.")
        return
        
    cookies = json.loads(cookies_path.read_text())
    
    # 2. On prépare la session invisible
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
    for c in cookies:
        if c.get("domain"):
            session.cookie_jar.update_cookies(
                {c["name"]: c["value"]},
                response_url=URL(f"https://{c['domain'].lstrip('.')}")
            )
            
    # 3. ON POSE LA QUESTION À L'API ("Qui suis-je ?")
    api_moi_url = "https://pro.permisdeconduire.gouv.fr/api/v2/auto-ecole/employes/moi"
    
    async with session.get(api_moi_url) as reponse:
        if reponse.status == 200:
            # Le serveur nous reconnaît et nous envoie nos données !
            data = await reponse.json()
            
            print("\n✅ CONNEXION INVISIBLE RÉUSSIE À 100 % ! 🎉")
            print("Voici ce que le serveur du gouvernement voit quand ton bot lui parle :")
            print("-" * 50)
            print(f"👤 Employé connecté : {data.get('prenom')} {data.get('nom')}")
            print(f"✉️ Email            : {data.get('email')}")
            
            auto_ecole = data.get('autoEcole', {})
            print(f"🏫 Auto-école       : {auto_ecole.get('nom')}")
            print(f"📍 Ville            : {auto_ecole.get('ville')} ({auto_ecole.get('codePostal')})")
            print(f"🔢 Numéro Aurige    : {auto_ecole.get('aurigeId')}")
            print("-" * 50)
            
        else:
            print(f"\n❌ Échec ! Le serveur ne nous reconnaît pas. Code erreur : {reponse.status}")
            
    await session.close()

if __name__ == "__main__":
    asyncio.run(tester_identite())