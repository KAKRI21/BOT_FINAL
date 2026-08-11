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


def apply_overrides(config, args):
    """Applique les arguments CLI par-dessus config.yaml"""
    if args.heure_min:
        config["search"]["heure_min"] = args.heure_min
    if args.heure_max:
        config["search"]["heure_max"] = args.heure_max
    if args.quota is not None:
        config["reservation"]["quota_max"] = args.quota
    if args.mode:
        config["reservation"]["mode"] = args.mode
    if args.centres:
        config["search"]["centres"] = args.centres
    if args.date_min:
        config["search"]["date_min"] = args.date_min
    if args.date_max:
        config["search"]["date_max"] = args.date_max
    if args.nb_eleves is not None:
        if args.nb_eleves > 4:
            print("❌ --nb-eleves max = 4 (limite plateforme)")
            sys.exit(1)
        config["reservation"]["nb_eleves"] = args.nb_eleves
    if args.dept:
        config["search"]["dept"] = args.dept
    
    # ─── OVERRIDE POUR LE RUSH PROGRAMMÉ ───
    if args.rush_heure:
        config["bot"]["rush_heure"] = args.rush_heure
        config["bot"]["rush_auto_reload"] = True
        
    return config


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
            logger.info(f"📋 {len(bot.places_reservees)} place(s) réservée(s) :")
            for r in bot.places_reservees:
                logger.info(f"   • {r}")
        await bot.arreter()


async def main():
    parser = argparse.ArgumentParser(description="Bot RdvPermis V5")
    parser.add_argument("--login",     action="store_true", help="Ouvrir navigateur pour se connecter")
    parser.add_argument("--test",      action="store_true", help="Tester la session")

    # ── Overrides config.yaml ──────────────────────────────
    parser.add_argument("--heure-min",  dest="heure_min",  metavar="HH:MM",
                        help='Heure min (ex: "09:00")')
    parser.add_argument("--heure-max",  dest="heure_max",  metavar="HH:MM",
                        help='Heure max (ex: "17:00")')
    parser.add_argument("--quota",      dest="quota",      type=int, metavar="N",
                        help="Quota max de réservations (ex: 7)")
    parser.add_argument("--mode",       dest="mode",
                        choices=["tous", "consecutifs"],
                        help="Mode de sélection des créneaux")
    parser.add_argument("--centres",    dest="centres",    nargs="+", metavar="CENTRE",
                        help='Centres à scanner (ex: "GONESSE B" "CERGY B")')
    parser.add_argument("--date-min",   dest="date_min",   metavar="YYYY-MM-DD",
                        help="Date min de recherche")
    parser.add_argument("--date-max",   dest="date_max",   metavar="YYYY-MM-DD",
                        help="Date max de recherche")
    parser.add_argument("--nb-eleves",  dest="nb_eleves",  type=int, metavar="N",
                        help="Nombre de candidats à placer par créneau (ex: 3)")
    parser.add_argument("--dept",       dest="dept",
                        choices=["93", "95"],
                        help="Filtrer par département (93 ou 95)")
    
    # ── Nouvel argument pour l'heure du rush ────────────────
    parser.add_argument("--rush-heure", dest="rush_heure", metavar="HH:MM",
                        help='Heure planifiée du rush pour réveiller le bot (ex: "15:00")')

    args = parser.parse_args()

    setup_logging()
    config = load_config()
    config = apply_overrides(config, args)

    if args.login:
        await sauvegarder_session()
        return

    if args.test:
        bot = BotRdvPermis(config)
        await bot.demarrer()
        try:
            ok = await bot.se_connecter()
            if ok:
                await bot.get_panier()
                print("✅ Bot prêt — lance : python main.py")
            else:
                print("❌ Session invalide — python main.py --login")
        finally:
            await bot.arreter()
        return

    # Affiche la config effective
    s = config["search"]
    r = config["reservation"]
    b = config["bot"]
    rush_status = f"{b.get('rush_heure', '15:00')} (Attente Passive)" if b.get("rush_auto_reload", True) else "Désactivé (Scan Continu)"
    
    print(f"""
╔══════════════════════════════════════════════╗
║   🚗  BOT RDVPERMIS V5 — EN COURS            ║
║   (Ctrl+C pour arrêter)                      ║
╚══════════════════════════════════════════════╝
  Horaires  : {s['heure_min']} → {s['heure_max']}
  Quota     : {r['quota_max']}
  Mode      : {r['mode']}
  Élèves/cr : {r.get('nb_eleves', 1)}
  Centres   : {s['centres'] or 'tous'}
  Dept      : {s.get('dept', 'tous')}
  Planif Rush: {rush_status}
""")
    await run(config)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Arrêt propre")