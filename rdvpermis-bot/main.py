"""
main.py — Point d'entrée Bot RdvPermis V5

  python main.py --login   → Connexion manuelle via CDP (Chrome)
  python main.py           → Lance le bot (scan + réservation)
  python main.py --test    → Vérifie que la session est valide
"""
import asyncio
import argparse
import logging
import sys
import yaml
from pathlib import Path
from bot import BotRdvPermis, sauvegarder_session


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("bot.log", encoding="utf-8"),
        ]
    )


def load_config():
    path = Path("config.yaml")
    if not path.exists():
        print("❌ config.yaml introuvable")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def mode_test(config):
    bot = BotRdvPermis(config)
    await bot.demarrer()
    try:
        ok = await bot.se_connecter()
        if ok:
            await bot.get_panier()
            print("✅ Bot prêt — lance : python main.py")
        else:
            print("❌ Session invalide — lance : python main.py --login")
    finally:
        await bot.arreter()


async def run(config):
    logger = logging.getLogger("rdvpermis.main")
    bot = BotRdvPermis(config)
    await bot.demarrer()
    try:
        ok = await bot.se_connecter()
        if not ok:
            logger.critical("❌ Session invalide — lance : python main.py --login")
            return
        await bot.boucle()
    except KeyboardInterrupt:
        logger.info("⛔ Arrêt demandé (Ctrl+C)")
    finally:
        if bot.places_reservees:
            logger.info(f"📋 {len(bot.places_reservees)} batch(s) réservé(s) :")
            for r in bot.places_reservees:
                logger.info(f"   • {r['nb']} places — {r['date']} @ {r['centre']}")
        await bot.arreter()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", action="store_true", help="Connexion manuelle CDP")
    parser.add_argument("--test",  action="store_true", help="Vérifier la session")
    args = parser.parse_args()

    setup_logging()
    config = load_config()

    if args.login:
        await sauvegarder_session()
        return

    if args.test:
        await mode_test(config)
        return

    print("""
╔══════════════════════════════════════════════╗
║   🚗  BOT RDVPERMIS V5 — EN COURS            ║
║   (Ctrl+C pour arrêter)                      ║
╚══════════════════════════════════════════════╝
""")
    await run(config)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Arrêt propre")