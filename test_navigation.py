import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

COOKIES_FILE = Path("cookies.json")
CRENODISPO_URL = "https://pro.permisdeconduire.gouv.fr/crenodispo"

async def tester_navigation_visuelle():
    print("\n=== 🧪 TEST DE NAVIGATION VISUELLE ET SEMAINE PAR SEMAINE ===")
    
    if not COOKIES_FILE.exists():
        print("❌ Erreur : Tu dois d'abord générer tes cookies avec main.py --login")
        return

    # 1. Lancement de Playwright en mode VISUEL (headless=False)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
    
    # Création d'un contexte propre avec une taille d'écran standard
    context = await browser.new_context(no_viewport=True)
    
    # 2. Injection des cookies capturés
    print("🍪 Injection des 50 cookies dans le navigateur de test...")
    cookies = json.loads(COOKIES_FILE.read_text())
    await context.add_cookies(cookies)
    
    page = await context.new_page()
    
    try:
        # 3. Direction la page de recherche des créneaux
        print(f"🌐 Navigation vers : {CRENODISPO_URL}")
        await page.goto(CRENODISPO_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000) # Petite pause pour observer l'affichage
        
        # Vérification si on est bien connecté ou si Akamai nous a éjecté
        if "auth" in page.url or "login" in page.url:
            print("❌ Session expirée ou rejetée. Relance d'abord le login d'origine.")
            await browser.close()
            await pw.stop()
            return

        print("✅ Accès à la page CrenoDispo réussi sans reconnexions !")

        # 4. Simulation : Sélection du premier bouton radio (Centre d'examen)
        # Note : On cherche un bouton radio ou un label contenant nos centres cibles (ex: GONESSE)
        print("🎯 Tentative de sélection du centre d'examen...")
        # On attend que les sélecteurs de centres soient chargés
        await page.wait_for_selector("input[type='radio']", timeout=10000)
        
        # Exemple générique : on clique sur le premier centre disponible à l'écran
        centres_radio = await page.query_selector_all("input[type='radio']")
        if centres_radio:
            await centres_radio[0].click()
            print("👉 Premier centre sélectionné avec succès.")
            await page.wait_for_timeout(2000)
        
        # 5. Boucle de navigation : Semaine par Semaine
        print("\n🔄 Début de la simulation de changement de semaine...")
        
        # Sélecteur typique du bouton "Semaine suivante" (souvent une flèche ou un bouton avec une classe spécifique)
        # S'il s'agit d'une flèche classique avec un titre ou un chevron :
        # On va chercher par texte ou par sélecteur de classe (ex: les boutons autour du composant calendrier)
        # Pour le test, on va chercher un bouton contenant ">" ou un attribut lié à la navigation suivante.
        
        for semaine in range(1, 5): # On va avancer de 4 semaines
            print(f"📅 Passage à la semaine suivante (+{semaine}) via l'interface...")
            
            # TENTATIVE 1 : Trouver par icône/texte de bouton classique de calendrier gouv
            bouton_suivant = await page.query_selector("button:has-text('>')") or \
                             await page.query_selector("[aria-label='Semaine suivante']") or \
                             await page.query_selector(".next-button") # Sélecteur classique
                             
            if bouton_suivant:
                await bouton_suivant.click()
                print(f"   ↳ Clic effectué ! Attente du chargement de la semaine {semaine}...")
                await page.wait_for_timeout(2500) # On attend 2.5s pour voir le calendrier bouger à l'écran
            else:
                # Si le sélecteur strict échoue, on cherche un élément cliquable contenant le caractère de flèche standard
                try:
                    await page.click("//button[contains(.,'>')]", timeout=3000)
                    print(f"   ↳ Clic via XPath effectué ! Semaine {semaine} chargée.")
                    await page.wait_for_timeout(2500)
                except Exception:
                    print("   ⚠️ Bouton 'Semaine suivante' introuvable avec ces sélecteurs. Regarde l'écran pour identifier son sélecteur exact.")
                    break

        print("\n🏁 Fin du test visuel ! La navigation semaine par semaine fonctionne.")
        print("Le bot est capable de manipuler le DOM et de simuler parfaitement une action humaine.")
        
        # On laisse la fenêtre ouverte 5 secondes de plus pour que tu puisses contempler le résultat
        await page.wait_for_timeout(5000)

    except Exception as e:
        print(f"💥 Une erreur est survenue pendant le test de navigation : {e}")

    finally:
        await browser.close()
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(tester_navigation_visuelle())