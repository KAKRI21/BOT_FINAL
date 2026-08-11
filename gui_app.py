"""
gui_app.py — Interface bureau pour le Bot RdvPermis
=====================================================
Application graphique (Tkinter) permettant à un utilisateur non technique de :
  - démarrer / arrêter le bot
  - se connecter (récupération des cookies de session via Chrome)
  - tester la session
  - modifier la configuration (horaires, centres, quota, notifications...)
  - suivre les logs et réservations en temps réel

Ce fichier ne modifie pas bot.py / notifier.py / main.py — il les réutilise tels quels.
"""
import asyncio
import copy
import logging
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

import yaml

if getattr(sys, "frozen", False):
    # Exécuté depuis un .exe construit par PyInstaller : on utilise le dossier
    # de l'exécutable (et non le dossier temporaire d'extraction) pour que
    # config.yaml / cookies.json / bot.log restent lisibles et modifiables.
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
import os  # noqa: E402
os.chdir(BASE_DIR)  # bot.py utilise des chemins relatifs (cookies.json, bot.log)

from bot import BotRdvPermis, CENTRES_FAVORIS, COOKIES_FILE  # noqa: E402

import subprocess

CONFIG_PATH = BASE_DIR / "config.yaml"
LOG_PATH = BASE_DIR / "bot.log"
PROFILE_DIR = BASE_DIR / "chrome_profile"
DEBUG_PORT = 9222
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_CONFIG = {
    "search": {"groupe_permis": "B", "date_min": "", "date_max": "",
               "dates_specifiques": [],
               "heure_min": "09:00", "heure_max": "17:00", "centres": [], "dept": None},
    "reservation": {"quota_max": 36, "max_par_creneau": -1, "mode": "consecutifs", "nb_eleves": 1},
    "bot": {"interval_secondes": 5, "rush_auto_reload": True, "rush_heure": "15:00"},
    "notifications": {
        "son_local": True,
        "telegram": {"active": False, "bot_token": "", "chat_id": ""},
        "email": {"active": False, "expediteur": "", "destinataire": "",
                   "smtp_host": "", "smtp_port": 587, "mot_de_passe_app": ""},
    },
}


def deep_merge(base, override):
    result = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return deep_merge(DEFAULT_CONFIG, data)
    return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config: dict):
    header = (
        "# ============================================================\n"
        "#  CONFIG BOT RDVPERMIS — généré par l'interface graphique\n"
        "# ============================================================\n\n"
    )
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)


class QueueHandler(logging.Handler):
    """Handler de logging qui pousse chaque ligne dans une queue thread-safe."""

    def __init__(self, log_queue: "queue.Queue[str]"):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put_nowait(self.format(record))
        except Exception:
            pass


def setup_logging(log_queue: "queue.Queue[str]"):
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    qh = QueueHandler(log_queue)
    qh.setFormatter(fmt)
    root.addHandler(qh)


class AsyncWorker:
    """Boucle asyncio persistante tournant dans un thread dédié.

    Le thread Tkinter (principal) soumet des coroutines via `submit()` et peut
    annuler la tâche en cours via `cancel_current()`.
    """

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._current_task: asyncio.Task | None = None
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro, on_done=None):
        """Lance `coro` comme tâche annulable ; on_done(exc_or_none) est appelé à la fin."""

        def _create():
            task = self.loop.create_task(coro)
            self._current_task = task

            def _finished(t: asyncio.Task):
                exc = None
                if not t.cancelled():
                    exc = t.exception()
                if on_done:
                    on_done(exc)

            task.add_done_callback(_finished)

        self.loop.call_soon_threadsafe(_create)

    def cancel_current(self):
        def _cancel():
            if self._current_task and not self._current_task.done():
                self._current_task.cancel()

        self.loop.call_soon_threadsafe(_cancel)

    def run_quick(self, coro, on_done):
        """Pour des opérations courtes (test session) qui ne doivent pas être annulables."""
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def _wait():
            try:
                result = fut.result()
                on_done(result, None)
            except Exception as e:  # noqa: BLE001
                on_done(None, e)

        threading.Thread(target=_wait, daemon=True).start()


async def gui_login_flow(status_cb, wait_event: asyncio.Event):
    """Lance automatiquement Chrome avec le port de débogage, s'y connecte via
    Playwright (CDP), attend que l'utilisateur se connecte et clique sur
    « J'ai terminé », puis enregistre les cookies de session."""
    from playwright.async_api import async_playwright

    chrome_path = next((p for p in CHROME_CANDIDATES if Path(p).exists()), None)
    if not chrome_path:
        raise RuntimeError(
            "Google Chrome est introuvable à l'emplacement habituel. "
            "Vérifiez qu'il est bien installé sur ce PC."
        )

    status_cb("Lancement de Chrome...")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen([
            chrome_path,
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={PROFILE_DIR}",
            "https://www.google.com",
        ])
    except Exception as e:
        raise RuntimeError(f"Impossible de lancer Chrome : {e}") from e

    await asyncio.sleep(2)  # laisse le temps à Chrome de démarrer

    pw = await async_playwright().start()
    browser = None
    for _ in range(10):
        try:
            browser = await pw.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
            break
        except Exception:
            await asyncio.sleep(1)
    if browser is None:
        await pw.stop()
        raise RuntimeError("Connexion à Chrome impossible. Réessayez.")

    context = browser.contexts[0]
    _ = context.pages[0] if context.pages else await context.new_page()

    status_cb("Connectez-vous sur le site RdvPermis dans la fenêtre Chrome, puis cliquez sur "
               "« J'ai terminé » ci-dessous.")

    await wait_event.wait()

    cookies = await context.cookies()
    import json
    COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
    await pw.stop()
    return len(cookies)


async def test_session(config: dict):
    bot = BotRdvPermis(config)
    await bot.demarrer()
    try:
        ok = await bot.se_connecter()
        if ok:
            await bot.get_panier()
        return ok
    finally:
        await bot.arreter()


class BotRunner:
    """Encapsule le cycle de vie du bot (identique à main.run()) pour exposer un état à la GUI."""

    def __init__(self, config: dict):
        self.config = config
        self.bot: BotRdvPermis | None = None

    async def run(self):
        logger = logging.getLogger("rdvpermis.main")
        self.bot = BotRdvPermis(self.config)
        await self.bot.demarrer()
        try:
            ok = await self.bot.se_connecter()
            if not ok:
                logger.error("❌ Session invalide — utilisez le bouton « Se connecter »")
                return
            await self.bot.boucle()
        except asyncio.CancelledError:
            logger.info("⛔ Arrêt demandé par l'utilisateur")
            raise
        finally:
            if self.bot.places_reservees:
                logger.info(f"📋 {len(self.bot.places_reservees)} place(s) réservée(s)")
            await self.bot.arreter()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bot RdvPermis — Auto-École")
        self.geometry("880x640")
        self.minsize(760, 560)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        setup_logging(self.log_queue)
        self.worker = AsyncWorker()

        self.config_data = load_config()
        self.running = False
        self.bot_runner: BotRunner | None = None
        self._login_event: asyncio.Event | None = None

        self._build_ui()
        self.after(150, self._poll_log_queue)
        self.after(1000, self._poll_bot_state)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_control = ttk.Frame(notebook)
        self.tab_config = ttk.Frame(notebook)
        notebook.add(self.tab_control, text="  Contrôle  ")
        notebook.add(self.tab_config, text="  Configuration  ")

        self._build_control_tab()
        self._build_config_tab()

    # -- Onglet Contrôle --------------------------------------------------
    def _build_control_tab(self):
        top = ttk.Frame(self.tab_control)
        top.pack(fill="x", padx=10, pady=10)

        self.status_var = tk.StringVar(value="● Arrêté")
        status_label = ttk.Label(top, textvariable=self.status_var, font=("Segoe UI", 14, "bold"),
                                  foreground="#c0392b")
        status_label.pack(side="left")
        self.status_label = status_label

        self.stats_var = tk.StringVar(value="Panier : 0/36   |   Réservés : 0")
        ttk.Label(top, textvariable=self.stats_var, font=("Segoe UI", 10)).pack(side="right")

        btns = ttk.Frame(self.tab_control)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        self.btn_start = ttk.Button(btns, text="▶  Démarrer le bot", command=self._on_start)
        self.btn_start.pack(side="left", padx=(0, 6))

        self.btn_stop = ttk.Button(btns, text="⏹  Arrêter le bot", command=self._on_stop,
                                    state="disabled")
        self.btn_stop.pack(side="left", padx=6)

        ttk.Separator(btns, orient="vertical").pack(side="left", fill="y", padx=10)

        self.btn_login = ttk.Button(btns, text="🔑  Se connecter", command=self._on_login)
        self.btn_login.pack(side="left", padx=6)

        self.btn_test = ttk.Button(btns, text="🧪  Tester la session", command=self._on_test)
        self.btn_test.pack(side="left", padx=6)

        log_frame = ttk.LabelFrame(self.tab_control, text="Journal en direct")
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(log_frame, state="disabled", wrap="word",
                                                    font=("Consolas", 9), bg="#111318", fg="#d6d6d6")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text.tag_config("ok", foreground="#2ecc71")
        self.log_text.tag_config("warn", foreground="#f39c12")
        self.log_text.tag_config("err", foreground="#e74c3c")

    # -- Onglet Configuration ---------------------------------------------
    def _build_config_tab(self):
        canvas = tk.Canvas(self.tab_config, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.tab_config, orient="vertical", command=canvas.yview)
        form = ttk.Frame(canvas)
        form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y")

        cfg = self.config_data
        pad = {"padx": 8, "pady": 5}

        # -- Recherche --
        sec = ttk.LabelFrame(form, text="Recherche de créneaux")
        sec.grid(row=0, column=0, sticky="ew", **pad)
        s = cfg["search"]

        ttk.Label(sec, text="Groupe permis :").grid(row=0, column=0, sticky="w", **pad)
        self.var_groupe = tk.StringVar(value=s.get("groupe_permis", "B"))
        ttk.Entry(sec, textvariable=self.var_groupe, width=8).grid(row=0, column=1, sticky="w", **pad)

        # -- Mode de sélection des dates : plage continue OU dates précises --
        ttk.Label(sec, text="Dates recherchées :").grid(row=1, column=0, sticky="nw", **pad)
        mode_frame = ttk.Frame(sec)
        mode_frame.grid(row=1, column=1, columnspan=3, sticky="w", **pad)

        dates_dep = s.get("dates_specifiques") or []
        self.var_date_mode = tk.StringVar(value="precises" if dates_dep else "plage")
        ttk.Radiobutton(mode_frame, text="Plage continue (tous les jours entre les deux)",
                        variable=self.var_date_mode, value="plage",
                        command=self._on_date_mode_change).pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="Dates précises (uniquement les jours choisis)",
                        variable=self.var_date_mode, value="precises",
                        command=self._on_date_mode_change).pack(anchor="w")

        # Conteneur commun : les deux sous-formulaires occupent la même cellule,
        # un seul est visible à la fois (grid()/grid_remove()).
        date_container = ttk.Frame(sec)
        date_container.grid(row=2, column=0, columnspan=4, sticky="w", **pad)

        self.frame_plage = ttk.Frame(date_container)
        ttk.Label(self.frame_plage, text="Du (AAAA-MM-JJ) :").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.var_date_min = tk.StringVar(value=s.get("date_min", ""))
        ttk.Entry(self.frame_plage, textvariable=self.var_date_min, width=14).grid(row=0, column=1, sticky="w", padx=(0, 16))
        ttk.Label(self.frame_plage, text="Au (AAAA-MM-JJ) :").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.var_date_max = tk.StringVar(value=s.get("date_max", ""))
        ttk.Entry(self.frame_plage, textvariable=self.var_date_max, width=14).grid(row=0, column=3, sticky="w")

        self.frame_precises = ttk.Frame(date_container)
        ttk.Label(self.frame_precises, text="Ajouter une date :").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.var_new_date = tk.StringVar()
        entry_new_date = ttk.Entry(self.frame_precises, textvariable=self.var_new_date, width=14)
        entry_new_date.grid(row=0, column=1, sticky="w", padx=(0, 6))
        entry_new_date.bind("<Return>", lambda e: self._on_add_date())
        ttk.Button(self.frame_precises, text="➕ Ajouter", command=self._on_add_date).grid(
            row=0, column=2, sticky="w")
        ttk.Label(self.frame_precises, text="(AAAA-MM-JJ, ex: 2026-07-31)",
                  foreground="#888888").grid(row=0, column=3, sticky="w", padx=(6, 0))

        list_row = ttk.Frame(self.frame_precises)
        list_row.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.date_listbox = tk.Listbox(list_row, height=4, width=32, selectmode="extended",
                                        exportselection=False)
        self.date_listbox.pack(side="left")
        list_scroll = ttk.Scrollbar(list_row, orient="vertical", command=self.date_listbox.yview)
        list_scroll.pack(side="left", fill="y")
        self.date_listbox.configure(yscrollcommand=list_scroll.set)
        for d in sorted(dates_dep):
            self.date_listbox.insert("end", d)
        ttk.Button(self.frame_precises, text="🗑 Supprimer la sélection",
                   command=self._on_remove_dates).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        if self.var_date_mode.get() == "precises":
            self.frame_precises.grid(row=0, column=0, sticky="w")
        else:
            self.frame_plage.grid(row=0, column=0, sticky="w")

        ttk.Label(sec, text="Heure min (HH:MM) :").grid(row=3, column=0, sticky="w", **pad)
        self.var_heure_min = tk.StringVar(value=s.get("heure_min", "09:00"))
        ttk.Entry(sec, textvariable=self.var_heure_min, width=10).grid(row=3, column=1, sticky="w", **pad)

        ttk.Label(sec, text="Heure max (HH:MM) :").grid(row=3, column=2, sticky="w", **pad)
        self.var_heure_max = tk.StringVar(value=s.get("heure_max", "17:00"))
        ttk.Entry(sec, textvariable=self.var_heure_max, width=10).grid(row=3, column=3, sticky="w", **pad)

        ttk.Label(sec, text="Centres (aucun = tous) :").grid(row=4, column=0, sticky="nw", **pad)
        centre_frame = ttk.Frame(sec)
        centre_frame.grid(row=4, column=1, columnspan=3, sticky="w", **pad)
        selected = set(s.get("centres") or [])
        self.centre_vars: dict[str, tk.BooleanVar] = {}
        for i, c in enumerate(CENTRES_FAVORIS):
            nom = c["nom"]
            var = tk.BooleanVar(value=nom in selected)
            self.centre_vars[nom] = var
            ttk.Checkbutton(centre_frame, text=nom, variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=4, pady=2)

        # -- Réservation --
        sec2 = ttk.LabelFrame(form, text="Réservation")
        sec2.grid(row=1, column=0, sticky="ew", **pad)
        r = cfg["reservation"]

        ttk.Label(sec2, text="Quota max (-1 = illimité) :").grid(row=0, column=0, sticky="w", **pad)
        self.var_quota = tk.StringVar(value=str(r.get("quota_max", 36)))
        ttk.Entry(sec2, textvariable=self.var_quota, width=8).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(sec2, text="Max par créneau (-1 = illimité) :").grid(row=0, column=2, sticky="w", **pad)
        self.var_max_par_creneau = tk.StringVar(value=str(r.get("max_par_creneau", -1)))
        ttk.Entry(sec2, textvariable=self.var_max_par_creneau, width=8).grid(row=0, column=3, sticky="w", **pad)

        ttk.Label(sec2, text="Mode :").grid(row=1, column=0, sticky="w", **pad)
        self.var_mode = tk.StringVar(value=r.get("mode", "consecutifs"))
        ttk.Combobox(sec2, textvariable=self.var_mode, values=["tous", "consecutifs"],
                     state="readonly", width=14).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(sec2, text="Élèves par créneau (max 4) :").grid(row=1, column=2, sticky="w", **pad)
        self.var_nb_eleves = tk.StringVar(value=str(r.get("nb_eleves", 1)))
        ttk.Entry(sec2, textvariable=self.var_nb_eleves, width=8).grid(row=1, column=3, sticky="w", **pad)

        # -- Bot --
        sec3 = ttk.LabelFrame(form, text="Fonctionnement")
        sec3.grid(row=2, column=0, sticky="ew", **pad)
        b = cfg["bot"]
        ttk.Label(sec3, text="Intervalle entre scans (secondes) :").grid(row=0, column=0, sticky="w", **pad)
        self.var_interval = tk.StringVar(value=str(b.get("interval_secondes", 5)))
        ttk.Entry(sec3, textvariable=self.var_interval, width=8).grid(row=0, column=1, sticky="w", **pad)

        ttk.Separator(sec3, orient="horizontal").grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 6))

        self.var_rush_actif = tk.BooleanVar(value=b.get("rush_auto_reload", True))
        ttk.Checkbutton(sec3, text="Réveil programmé (rush) — le bot reste en attente passive "
                                    "jusqu'à l'heure ci-dessous, puis scanne en continu",
                        variable=self.var_rush_actif).grid(
            row=2, column=0, columnspan=4, sticky="w", **pad)

        ttk.Label(sec3, text="Heure de réveil (HH:MM) :").grid(row=3, column=0, sticky="w", **pad)
        self.var_rush_heure = tk.StringVar(value=b.get("rush_heure", "15:00"))
        ttk.Entry(sec3, textvariable=self.var_rush_heure, width=10).grid(row=3, column=1, sticky="w", **pad)

        # -- Notifications --
        sec4 = ttk.LabelFrame(form, text="Notifications")
        sec4.grid(row=3, column=0, sticky="ew", **pad)
        n = cfg["notifications"]

        self.var_son = tk.BooleanVar(value=n.get("son_local", True))
        ttk.Checkbutton(sec4, text="Bip sonore local", variable=self.var_son).grid(
            row=0, column=0, sticky="w", columnspan=2, **pad)

        tg = n.get("telegram", {})
        self.var_tg_active = tk.BooleanVar(value=tg.get("active", False))
        ttk.Checkbutton(sec4, text="Telegram actif", variable=self.var_tg_active).grid(
            row=1, column=0, sticky="w", **pad)
        ttk.Label(sec4, text="Bot token :").grid(row=2, column=0, sticky="w", **pad)
        self.var_tg_token = tk.StringVar(value=tg.get("bot_token", ""))
        ttk.Entry(sec4, textvariable=self.var_tg_token, width=40, show="•").grid(
            row=2, column=1, columnspan=3, sticky="w", **pad)
        ttk.Label(sec4, text="Chat ID :").grid(row=3, column=0, sticky="w", **pad)
        self.var_tg_chat = tk.StringVar(value=tg.get("chat_id", ""))
        ttk.Entry(sec4, textvariable=self.var_tg_chat, width=20).grid(row=3, column=1, sticky="w", **pad)

        em = n.get("email", {})
        self.var_em_active = tk.BooleanVar(value=em.get("active", False))
        ttk.Checkbutton(sec4, text="Email actif", variable=self.var_em_active).grid(
            row=4, column=0, sticky="w", **pad)
        ttk.Label(sec4, text="Expéditeur :").grid(row=5, column=0, sticky="w", **pad)
        self.var_em_from = tk.StringVar(value=em.get("expediteur", ""))
        ttk.Entry(sec4, textvariable=self.var_em_from, width=28).grid(row=5, column=1, sticky="w", **pad)
        ttk.Label(sec4, text="Destinataire :").grid(row=5, column=2, sticky="w", **pad)
        self.var_em_to = tk.StringVar(value=em.get("destinataire", ""))
        ttk.Entry(sec4, textvariable=self.var_em_to, width=28).grid(row=5, column=3, sticky="w", **pad)
        ttk.Label(sec4, text="Serveur SMTP :").grid(row=6, column=0, sticky="w", **pad)
        self.var_em_host = tk.StringVar(value=em.get("smtp_host", ""))
        ttk.Entry(sec4, textvariable=self.var_em_host, width=28).grid(row=6, column=1, sticky="w", **pad)
        ttk.Label(sec4, text="Port SMTP :").grid(row=6, column=2, sticky="w", **pad)
        self.var_em_port = tk.StringVar(value=str(em.get("smtp_port", 587)))
        ttk.Entry(sec4, textvariable=self.var_em_port, width=8).grid(row=6, column=3, sticky="w", **pad)
        ttk.Label(sec4, text="Mot de passe d'application :").grid(row=7, column=0, sticky="w", **pad)
        self.var_em_pass = tk.StringVar(value=em.get("mot_de_passe_app", ""))
        ttk.Entry(sec4, textvariable=self.var_em_pass, width=28, show="•").grid(
            row=7, column=1, sticky="w", **pad)

        save_bar = ttk.Frame(form)
        save_bar.grid(row=4, column=0, sticky="ew", padx=8, pady=12)
        ttk.Button(save_bar, text="💾  Enregistrer la configuration",
                   command=self._on_save_config).pack(side="left")
        self.save_status_var = tk.StringVar(value="")
        ttk.Label(save_bar, textvariable=self.save_status_var, foreground="#2ecc71").pack(
            side="left", padx=10)

    # ------------------------------------------------------------- actions
    # ------------------------------------------------------- dates précises
    def _on_date_mode_change(self):
        if self.var_date_mode.get() == "precises":
            self.frame_plage.grid_remove()
            self.frame_precises.grid(row=0, column=0, sticky="w")
        else:
            self.frame_precises.grid_remove()
            self.frame_plage.grid(row=0, column=0, sticky="w")

    def _on_add_date(self):
        val = self.var_new_date.get().strip()
        if not DATE_RE.match(val):
            messagebox.showerror("Date invalide", "Format attendu : AAAA-MM-JJ (ex: 2026-07-31)")
            return
        existing = list(self.date_listbox.get(0, "end"))
        if val not in existing:
            existing.append(val)
            existing.sort()
            self.date_listbox.delete(0, "end")
            for d in existing:
                self.date_listbox.insert("end", d)
        self.var_new_date.set("")

    def _on_remove_dates(self):
        for i in reversed(self.date_listbox.curselection()):
            self.date_listbox.delete(i)

    # ------------------------------------------------------------------ config
    def _collect_config(self) -> dict | None:
        errors = []
        if not TIME_RE.match(self.var_heure_min.get().strip()):
            errors.append("Heure min invalide (format HH:MM)")
        if not TIME_RE.match(self.var_heure_max.get().strip()):
            errors.append("Heure max invalide (format HH:MM)")
        if not TIME_RE.match(self.var_rush_heure.get().strip()):
            errors.append("Heure de réveil invalide (format HH:MM)")
        date_mode = self.var_date_mode.get()
        dates_specifiques = list(self.date_listbox.get(0, "end")) if date_mode == "precises" else []
        if date_mode == "precises" and not dates_specifiques:
            errors.append("Ajoutez au moins une date en mode « Dates précises » (ou repassez en « Plage continue »)")
        if date_mode == "plage":
            for label, var in (("Date min", self.var_date_min), ("Date max", self.var_date_max)):
                val = var.get().strip()
                if val and not DATE_RE.match(val):
                    errors.append(f"{label} invalide (format AAAA-MM-JJ)")

        def to_int(var, name, lo=None, hi=None, allow_neg_one=False):
            try:
                v = int(var.get().strip())
            except ValueError:
                errors.append(f"{name} doit être un nombre entier")
                return None
            if allow_neg_one and v == -1:
                return v
            if lo is not None and v < lo:
                errors.append(f"{name} doit être ≥ {lo}")
            if hi is not None and v > hi:
                errors.append(f"{name} doit être ≤ {hi}")
            return v

        quota = to_int(self.var_quota, "Quota max", allow_neg_one=True)
        max_par_creneau = to_int(self.var_max_par_creneau, "Max par créneau", allow_neg_one=True)
        nb_eleves = to_int(self.var_nb_eleves, "Élèves par créneau", lo=1, hi=4)
        interval = to_int(self.var_interval, "Intervalle", lo=1)
        smtp_port = to_int(self.var_em_port, "Port SMTP", lo=1, hi=65535)

        if errors:
            messagebox.showerror("Configuration invalide", "\n".join(f"• {e}" for e in errors))
            return None

        centres = [nom for nom, var in self.centre_vars.items() if var.get()]

        return {
            "search": {
                "groupe_permis": self.var_groupe.get().strip() or "B",
                "date_min": "" if date_mode == "precises" else self.var_date_min.get().strip(),
                "date_max": "" if date_mode == "precises" else self.var_date_max.get().strip(),
                "dates_specifiques": dates_specifiques,
                "heure_min": self.var_heure_min.get().strip(),
                "heure_max": self.var_heure_max.get().strip(),
                "centres": centres,
                "dept": None,
            },
            "reservation": {
                "quota_max": quota,
                "max_par_creneau": max_par_creneau,
                "mode": self.var_mode.get(),
                "nb_eleves": nb_eleves,
            },
            "bot": {
                "interval_secondes": interval,
                "rush_auto_reload": self.var_rush_actif.get(),
                "rush_heure": self.var_rush_heure.get().strip(),
            },
            "notifications": {
                "son_local": self.var_son.get(),
                "telegram": {
                    "active": self.var_tg_active.get(),
                    "bot_token": self.var_tg_token.get().strip(),
                    "chat_id": self.var_tg_chat.get().strip(),
                },
                "email": {
                    "active": self.var_em_active.get(),
                    "expediteur": self.var_em_from.get().strip(),
                    "destinataire": self.var_em_to.get().strip(),
                    "smtp_host": self.var_em_host.get().strip(),
                    "smtp_port": smtp_port,
                    "mot_de_passe_app": self.var_em_pass.get(),
                },
            },
        }

    def _on_save_config(self):
        cfg = self._collect_config()
        if cfg is None:
            return
        self.config_data = cfg
        save_config(cfg)
        self.save_status_var.set("✅ Enregistré")
        self.after(2500, lambda: self.save_status_var.set(""))

    def _on_start(self):
        cfg = self._collect_config()
        if cfg is None:
            return
        save_config(cfg)
        self.config_data = cfg

        if not COOKIES_FILE.exists():
            if not messagebox.askyesno(
                "Session manquante",
                "Aucune session enregistrée. Voulez-vous vous connecter maintenant ?"
            ):
                return
            self._on_login()
            return

        self.bot_runner = BotRunner(cfg)
        self.running = True
        self._set_status(True)

        def on_done(exc):
            self.running = False
            self.after(0, lambda: self._set_status(False))
            if exc and not isinstance(exc, asyncio.CancelledError):
                logging.getLogger("rdvpermis.gui").error(f"Erreur : {exc}")

        self.worker.submit(self.bot_runner.run(), on_done=on_done)

    def _on_stop(self):
        self.worker.cancel_current()
        self.btn_stop.config(state="disabled")

    def _set_status(self, running: bool):
        if running:
            self.status_var.set("● En cours")
            self.status_label.config(foreground="#27ae60")
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
        else:
            self.status_var.set("● Arrêté")
            self.status_label.config(foreground="#c0392b")
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")

    def _on_test(self):
        cfg = self._collect_config()
        if cfg is None:
            return
        self.btn_test.config(state="disabled")

        def on_done(result, exc):
            self.btn_test.config(state="normal")
            if exc:
                messagebox.showerror("Test échoué", str(exc))
            elif result:
                messagebox.showinfo("Test réussi", "✅ Session valide — le bot est prêt.")
            else:
                messagebox.showwarning("Session invalide",
                                        "❌ Session invalide. Utilisez « Se connecter ».")

        self.worker.run_quick(test_session(cfg), on_done)

    def _on_login(self):
        win = tk.Toplevel(self)
        win.title("Connexion")
        win.geometry("480x240")
        win.transient(self)

        ttk.Label(win, text="Chrome va s'ouvrir automatiquement.",
                  wraplength=440, font=("Segoe UI", 10, "bold")).pack(padx=12, pady=(16, 4), anchor="w")
        ttk.Label(win, text="Allez sur le site RdvPermis et connectez-vous normalement, puis "
                            "revenez ici et cliquez sur « J'ai terminé ».",
                  wraplength=440).pack(padx=12, pady=(0, 10), anchor="w")

        status_var = tk.StringVar(value="Ouverture du navigateur...")
        ttk.Label(win, textvariable=status_var, foreground="#2980b9", wraplength=440).pack(
            padx=12, pady=4, anchor="w")

        done_btn = ttk.Button(win, text="✅ J'ai terminé")
        done_btn.pack(padx=12, pady=16)

        def status_cb(text):
            self.after(0, lambda: status_var.set(text))

        async def _flow():
            event = asyncio.Event()
            self._login_event = event

            def on_click():
                self.worker.loop.call_soon_threadsafe(event.set)
                done_btn.config(state="disabled")
                status_var.set("Récupération de la session...")

            self.after(0, lambda: done_btn.config(command=on_click))
            return await gui_login_flow(status_cb, event)

        def on_done(exc):
            def _finish():
                if exc:
                    messagebox.showerror("Échec de connexion", str(exc))
                else:
                    messagebox.showinfo("Connecté", "✅ Session enregistrée avec succès.")
                    win.destroy()
            self.after(0, _finish)

        self.worker.submit(_flow(), on_done=on_done)

    # --------------------------------------------------------------- poll
    def _poll_log_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass
        self.after(150, self._poll_log_queue)

    def _append_log(self, line: str):
        tag = None
        if "✅" in line or "🏁" in line:
            tag = "ok"
        elif "❌" in line or "ERROR" in line:
            tag = "err"
        elif "⚠️" in line or "WARNING" in line:
            tag = "warn"
        self.log_text.config(state="normal")
        self.log_text.insert("end", line + "\n", tag or ())
        # Limite la taille du journal affiché
        if float(self.log_text.index("end-1c").split(".")[0]) > 3000:
            self.log_text.delete("1.0", "500.0")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _poll_bot_state(self):
        if self.bot_runner and self.bot_runner.bot:
            bot = self.bot_runner.bot
            self.stats_var.set(
                f"Panier : {bot.nb_panier}/36   |   "
                f"Réservés : {bot.nb_reserves}/"
                f"{bot.quota_max if bot.quota_max > 0 else '∞'}"
            )
        self.after(1000, self._poll_bot_state)

    def _on_close(self):
        if self.running and not messagebox.askyesno(
            "Bot en cours", "Le bot tourne encore. Voulez-vous vraiment quitter ?"
        ):
            return
        self.worker.cancel_current()
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()