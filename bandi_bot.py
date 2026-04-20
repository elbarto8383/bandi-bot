#!/usr/bin/env python3
"""
KIRANET Bandi Bot v6
- Keyword configurabili da /data/keywords.json (bind mount)
- Ricerca automatica giornaliera via cron
- Menu interattivo Telegram con pulsanti inline
"""

import os, json, time, logging, sqlite3, requests
from datetime import datetime, timedelta
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_IDS_STR = os.environ.get("TELEGRAM_CHAT_IDS", "")
TELEGRAM_CHAT_IDS = [id.strip() for id in TELEGRAM_CHAT_IDS_STR.split(",") if id.strip()]
DB_PATH          = os.environ.get("DB_PATH", "/data/bandi_seen.db")
LOG_PATH         = os.environ.get("LOG_PATH", "/logs/bandi_bot.log")
KEYWORDS_PATH    = os.environ.get("KEYWORDS_PATH", "/data/keywords.json")
LOG_LEVEL        = os.environ.get("LOG_LEVEL", "INFO")

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH),  exist_ok=True)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh, _sh = logging.FileHandler(LOG_PATH), logging.StreamHandler()
_fh.setFormatter(_fmt); _sh.setFormatter(_fmt)
logging.basicConfig(level=getattr(logging, LOG_LEVEL), handlers=[_fh, _sh])
log = logging.getLogger("bandi-bot")

# ── Keyword di default (fallback se keywords.json non esiste) ─────────────────
DEFAULT_KEYWORDS = [
    "cartella clinica elettronica", "cartella clinica digitale",
    "informatizzazione reparti", "software gestione pazienti",
    "digitalizzazione sanitaria", "sistemi informativi medici",
    "fascicolo sanitario elettronico", "telemedicina",
    "software ospedaliero", "pnrr missione 6",
    "digitalizzazione ospedali", "servizi informatici sanitari",
    "carrelli informatizzati", "armadi automatizzati",
    "dispenser automatici farmaci", "logistica del farmaco",
    "asl", "asst", "irccs", "soresa", "policlinico",
]

DEFAULT_HIGH_PRIORITY = {
    "cartella clinica elettronica", "cartella clinica digitale",
    "software gestione pazienti", "fascicolo sanitario elettronico",
    "telemedicina", "pnrr missione 6", "digitalizzazione ospedali",
    "digitalizzazione sanitaria", "servizi informatici sanitari",
    "sanita digitale", "software ospedaliero",
}

DEFAULT_ENTI = [
    "asl", "asst", "aou", "azienda ospedaliera", "policlinico",
    "irccs", "soresa", "consip", "ospedale", "azienda sanitaria",
]

# ── Caricamento keyword da file ───────────────────────────────────────────────
def load_keywords() -> tuple[list, set, list]:
    """
    Carica keywords da /data/keywords.json.
    Restituisce (all_keywords, high_priority_set, enti_interest).
    Se il file non esiste o è corrotto, usa i default.
    """
    if not os.path.exists(KEYWORDS_PATH):
        log.warning(f"keywords.json non trovato in {KEYWORDS_PATH}, uso keyword di default")
        # Crea il file di default automaticamente
        _create_default_keywords_file()
        return DEFAULT_KEYWORDS, DEFAULT_HIGH_PRIORITY, DEFAULT_ENTI

    try:
        with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        kws    = data.get("keywords", DEFAULT_KEYWORDS)
        high   = set(data.get("high_priority", list(DEFAULT_HIGH_PRIORITY)))
        enti   = data.get("enti_interest", DEFAULT_ENTI)

        log.info(f"Keyword caricate da file: {len(kws)} keyword, "
                 f"{len(high)} alta priorità, {len(enti)} enti")
        return kws, high, enti

    except Exception as e:
        log.error(f"Errore lettura keywords.json: {e} — uso default")
        return DEFAULT_KEYWORDS, DEFAULT_HIGH_PRIORITY, DEFAULT_ENTI


def _create_default_keywords_file():
    """Crea keywords.json con i valori di default se non esiste."""
    try:
        os.makedirs(os.path.dirname(KEYWORDS_PATH), exist_ok=True)
        data = {
            "_commento": (
                "Modifica questo file per aggiornare le keyword di ricerca. "
                "Il bot le rilegge ad ogni esecuzione — nessun riavvio necessario."
            ),
            "keywords": DEFAULT_KEYWORDS,
            "high_priority": list(DEFAULT_HIGH_PRIORITY),
            "enti_interest": DEFAULT_ENTI,
        }
        with open(KEYWORDS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info(f"keywords.json creato automaticamente in {KEYWORDS_PATH}")
    except Exception as e:
        log.error(f"Impossibile creare keywords.json: {e}")


def save_keywords(kws: list, high: list, enti: list):
    """Salva le keyword aggiornate nel file."""
    try:
        data = {
            "_commento": (
                "Modifica questo file per aggiornare le keyword di ricerca. "
                "Il bot le rilegge ad ogni esecuzione — nessun riavvio necessario."
            ),
            "keywords": kws,
            "high_priority": high,
            "enti_interest": enti,
        }
        with open(KEYWORDS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log.error(f"Errore salvataggio keywords.json: {e}")
        return False

# ── API PVL ───────────────────────────────────────────────────────────────────
API_BASE      = "https://pubblicitalegale.anticorruzione.it/api/v0"
CODICE_SCHEDA = "2,4"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://pubblicitalegale.anticorruzione.it/bandi",
}

def fetch_avvisi_page(date_str: str, page: int = 0, size: int = 50) -> dict:
    try:
        r = requests.get(f"{API_BASE}/avvisi",
                         params={"dataPubblicazioneStart": date_str,
                                 "dataPubblicazioneEnd":   date_str,
                                 "page": page, "size": size,
                                 "codiceScheda": CODICE_SCHEDA},
                         headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return r.json()
        log.warning(f"API HTTP {r.status_code} data={date_str} page={page}")
    except Exception as e:
        log.error(f"Errore API: {e}")
    return {}

def fetch_all_avvisi(date_str: str) -> list[dict]:
    all_items, page = [], 0
    while True:
        data    = fetch_avvisi_page(date_str, page=page, size=50)
        content = data.get("content", [])
        all_items.extend(content)
        if page >= data.get("totalPages", 1) - 1 or not content:
            break
        page += 1
        time.sleep(0.5)
    return all_items

def extract_text(avviso: dict) -> str:
    parts = []
    def dig(obj):
        if isinstance(obj, str): parts.append(obj)
        elif isinstance(obj, list):
            for i in obj: dig(i)
        elif isinstance(obj, dict):
            for v in obj.values(): dig(v)
    dig(avviso)
    return " ".join(parts)

def normalize_avviso(avviso: dict) -> Optional[dict]:
    uid      = avviso.get("idAvviso") or avviso.get("idAppalto") or ""
    data_pub = avviso.get("dataPubblicazione", "")
    data_sc  = avviso.get("dataScadenza", "")
    if not uid:
        return None

    oggetto = sa = cig = cpv = ""
    importo = 0.0

    try:
        tmpl_list = avviso.get("template", [])
        if tmpl_list and isinstance(tmpl_list, list):
            inner = tmpl_list[0].get("template", {})
            meta  = inner.get("metadata", {})
            oggetto = (meta.get("descrizione") or meta.get("titolo") or "").strip()

            for sec in inner.get("sections", []):
                name   = sec.get("name", "")
                fields = sec.get("fields", {})
                items  = sec.get("items", [])

                if "SEZ. A" in name or "Committente" in name:
                    soggetti = fields.get("soggetti_sa", [])
                    if soggetti and isinstance(soggetti, list):
                        sa = soggetti[0].get("denominazione_amministrazione", "").strip()

                if "SEZ. C" in name or "Oggetto" in name:
                    if items and isinstance(items, list):
                        lotto = items[0]
                        cig   = lotto.get("cig", "").strip()
                        cpv   = lotto.get("cpv", "").strip()
                        if not oggetto:
                            oggetto = lotto.get("descrizione", "").strip()
                        for campo in ["valore_stimato", "importo_base_asta",
                                      "importo", "valore_totale"]:
                            val = lotto.get(campo)
                            if val:
                                try:
                                    importo = float(str(val).replace(".", "").replace(",", "."))
                                except: pass
                                break
    except Exception as e:
        log.debug(f"Errore parsing template uid={uid}: {e}")

    if not cig:
        cig = uid

    def fmt_date(s):
        if not s: return "N/D"
        try: return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").strftime("%d/%m/%Y")
        except: pass
        try: return s[8:10] + "/" + s[5:7] + "/" + s[0:4]
        except: return "N/D"

    return {
        "cig": cig, "uid": uid,
        "titolo":    (oggetto or "N/D")[:300],
        "stazione":  (sa or "N/D")[:150],
        "data_pub":  fmt_date(data_pub),
        "data_scad": fmt_date(data_sc),
        "importo":   importo, "cpv": cpv,
        "url":       f"https://pubblicitalegale.anticorruzione.it/bandi/{uid}",
        "_raw_text": extract_text(avviso),
    }

# ── Match & Score ─────────────────────────────────────────────────────────────
def norm(s):
    return (s.lower()
            .replace("à","a").replace("è","e").replace("é","e")
            .replace("ì","i").replace("ò","o").replace("ù","u"))

def match_keywords(bando: dict, all_keywords: list) -> list[str]:
    testo = norm(bando.get("_raw_text", "") or bando["titolo"] + " " + bando["stazione"])
    return [kw for kw in all_keywords if norm(kw) in testo]

def score_bando(bando: dict, matched: list, high_priority: set,
                enti_interest: list) -> tuple[int, list[str]]:
    score, reasons = 0, []
    testo = norm(bando.get("_raw_text", "") or "")
    for kw in matched:
        if kw in high_priority: score += 30; reasons.append(f"⭐ '{kw}'")
        else:                    score += 10; reasons.append(f"kw: '{kw}'")
    for ente in enti_interest:
        if norm(ente) in testo: score += 15; reasons.append(f"ente: {ente}"); break
    if "pnrr" in testo or "missione 6" in testo:
        score += 25; reasons.append("PNRR/M6")
    imp = bando.get("importo", 0) or 0
    if imp > 500_000:   score += 10; reasons.append(f"€{imp:,.0f}")
    elif imp > 100_000: score += 5
    return score, reasons[:5]

# ── DB ────────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS seen_bandi (
        cig TEXT PRIMARY KEY, sent_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn

def is_seen(conn, cig):
    return conn.execute("SELECT 1 FROM seen_bandi WHERE cig=?", (cig,)).fetchone() is not None

def mark_seen(conn, cig):
    conn.execute("INSERT OR IGNORE INTO seen_bandi (cig, sent_at) VALUES (?, ?)",
                 (cig, datetime.now().isoformat()))
    conn.commit()

def cleanup_old(conn, days=90):
    conn.execute("DELETE FROM seen_bandi WHERE sent_at < ?",
                 ((datetime.now() - timedelta(days=days)).isoformat(),))
    conn.commit()

def get_stats(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM seen_bandi").fetchone()[0]
    oggi  = conn.execute("SELECT COUNT(*) FROM seen_bandi WHERE sent_at >= ?",
                         (datetime.now().strftime("%Y-%m-%d"),)).fetchone()[0]
    sett  = conn.execute("SELECT COUNT(*) FROM seen_bandi WHERE sent_at >= ?",
                         ((datetime.now() - timedelta(days=7)).isoformat(),)).fetchone()[0]
    return {"totale": total, "oggi": oggi, "settimana": sett}

# ── Core ricerca ──────────────────────────────────────────────────────────────
def cerca_bandi(days_back: int, conn, send_unseen_only: bool = True) -> list[tuple]:
    # Rilegge keyword dal file ad ogni ricerca
    all_keywords, high_priority, enti_interest = load_keywords()

    dates = [(datetime.now() - timedelta(days=i)).strftime("%d/%m/%Y")
             for i in range(days_back)]
    found = {}

    for date_str in dates:
        log.info(f"Scarico avvisi del {date_str}...")
        avvisi = fetch_all_avvisi(date_str)
        log.info(f"  Totale avvisi: {len(avvisi)}")

        for raw in avvisi:
            b = normalize_avviso(raw)
            if not b or b["cig"] in found:
                continue
            matched = match_keywords(b, all_keywords)
            if not matched:
                continue
            sc, reasons = score_bando(b, matched, high_priority, enti_interest)
            if sc >= 10:
                found[b["cig"]] = (b, sc, reasons)
                log.info(f"  ✓ Match score={sc} → {b['titolo'][:60]}")

    results = [(b, sc, r) for cig, (b, sc, r) in found.items()
               if not send_unseen_only or not is_seen(conn, cig)]
    results.sort(key=lambda x: x[1], reverse=True)
    return results

# ── Telegram API ──────────────────────────────────────────────────────────────
TG = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def tg_send(chat_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "text": text,
               "parse_mode": parse_mode, "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(f"{TG}/sendMessage", json=payload, timeout=15)
        return r.json().get("result", {})
    except Exception as e:
        log.error(f"tg_send error: {e}"); return {}

def tg_edit(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id,
               "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(f"{TG}/editMessageText", json=payload, timeout=15)
    except: pass

def tg_answer(callback_id, text=""):
    try:
        requests.post(f"{TG}/answerCallbackQuery",
                      json={"callback_query_id": callback_id, "text": text}, timeout=10)
    except: pass

def tg_get_updates(offset=0):
    try:
        r = requests.get(f"{TG}/getUpdates",
                         params={"offset": offset, "timeout": 30,
                                 "allowed_updates": ["message", "callback_query"]},
                         timeout=35)
        if r.status_code == 200:
            return r.json().get("result", [])
    except: pass
    return []

# ── Menu ──────────────────────────────────────────────────────────────────────
MAIN_MENU = {
    "inline_keyboard": [[
        {"text": "🔍 Bandi di oggi",     "callback_data": "cerca_1"},
        {"text": "📅 Ultimi 7 giorni",   "callback_data": "cerca_7"},
    ],[
        {"text": "📅 Ultimi 30 giorni",  "callback_data": "cerca_30"},
        {"text": "📊 Statistiche",       "callback_data": "stats"},
    ],[
        {"text": "🔑 Vedi keyword",      "callback_data": "kw_list"},
        {"text": "➕ Aggiungi keyword",  "callback_data": "kw_add_prompt"},
    ],[
        {"text": "ℹ️ Info bot",          "callback_data": "info"},
    ]]
}

BACK_MENU = {"inline_keyboard": [[{"text": "⬅️ Torna al menu", "callback_data": "menu"}]]}

def menu_text():
    return "🏢 <b>KIRANET Bandi Bot</b>\n━━━━━━━━━━━━━━━━━━━━\nSeleziona un'opzione:"

def format_bando(b, score, reasons, idx, tot):
    icon = "⭐" if score >= 40 else ("🔶" if score >= 20 else "🔷")
    imp  = f"\n💰 €{b['importo']:,.0f}" if b.get("importo") else ""
    return (
        f"{icon} <b>GARA {idx}/{tot}</b> [score: {score}]\n"
        f"📋 {b['titolo'][:180]}\n"
        f"🏛 <b>SA:</b> {b['stazione'][:100]}\n"
        f"📅 Pub: {b['data_pub']} | Scade: {b['data_scad']}\n"
        f"🔑 <b>CIG:</b> {b['cig']}{imp}\n"
        f"📌 {' | '.join(reasons[:3])}\n"
        f"🔗 <a href='{b['url']}'>Apri su ANAC</a>"
    )

# ── Stato conversazione per aggiunta keyword ──────────────────────────────────
# chat_id → stato atteso (es. "waiting_keyword_add")
conversation_state = {}

def handle_callback(callback, conn):
    chat_id    = callback["message"]["chat"]["id"]
    msg_id     = callback["message"]["message_id"]
    data       = callback.get("data", "")
    cb_id      = callback["id"]

    if str(chat_id) not in TELEGRAM_CHAT_IDS:
        tg_answer(cb_id, "⛔ Non autorizzato"); return

    tg_answer(cb_id)

    # ── Cerca bandi ───────────────────────────────────────────────────────────
    if data.startswith("cerca_"):
        days  = int(data.split("_")[1])
        label = {1: "oggi", 7: "ultimi 7 giorni", 30: "ultimi 30 giorni"}.get(days, f"{days} giorni")
        tg_edit(chat_id, msg_id,
                f"⏳ Ricerca in corso per <b>{label}</b>...\nAttendi qualche secondo.")

        results = cerca_bandi(days, conn, send_unseen_only=False)

        if not results:
            tg_edit(chat_id, msg_id,
                    f"🔍 Nessuna gara rilevante per <b>{label}</b>.",
                    reply_markup=BACK_MENU)
            return

        tg_edit(chat_id, msg_id,
                f"✅ Trovate <b>{len(results)} gare</b> per <b>{label}</b>:")

        for idx, (b, sc, reasons) in enumerate(results[:20], 1):
            tg_send(chat_id, format_bando(b, sc, reasons, idx, min(len(results), 20)))
            time.sleep(0.8)

        tg_send(chat_id,
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 {min(len(results),20)} di {len(results)} gare | "
                f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                reply_markup=BACK_MENU)

    # ── Statistiche ───────────────────────────────────────────────────────────
    elif data == "stats":
        s = get_stats(conn)
        all_kws, high, enti = load_keywords()
        tg_edit(chat_id, msg_id,
                f"📊 <b>Statistiche</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 Oggi: <b>{s['oggi']}</b> bandi\n"
                f"📅 Ultimi 7 gg: <b>{s['settimana']}</b> bandi\n"
                f"🗂 Totale storico: <b>{s['totale']}</b> bandi\n"
                f"🔑 Keyword attive: <b>{len(all_kws)}</b>\n"
                f"⭐ Alta priorità: <b>{len(high)}</b>\n"
                f"⏰ Cron: ogni giorno alle 07:15",
                reply_markup=BACK_MENU)

    # ── Lista keyword ─────────────────────────────────────────────────────────
    elif data == "kw_list":
        all_kws, high, enti = load_keywords()
        # Suddivide in blocchi da 30 per non superare il limite Telegram
        kw_text = "\n".join(
            f"{'⭐' if kw in high else '🔹'} {kw}"
            for kw in all_kws
        )
        tg_edit(chat_id, msg_id,
                f"🔑 <b>Keyword attive ({len(all_kws)})</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⭐ = alta priorità | 🔹 = standard\n\n"
                f"{kw_text[:3000]}",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "➕ Aggiungi",  "callback_data": "kw_add_prompt"},
                        {"text": "➖ Rimuovi",   "callback_data": "kw_del_prompt"},
                    ],[
                        {"text": "⬅️ Menu", "callback_data": "menu"}
                    ]]
                })

    # ── Prompt aggiunta keyword ───────────────────────────────────────────────
    elif data == "kw_add_prompt":
        conversation_state[chat_id] = "waiting_kw_add"
        tg_edit(chat_id, msg_id,
                "➕ <b>Aggiungi keyword</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Scrivi la keyword da aggiungere.\n"
                "Aggiungi <code>!</code> davanti per renderla alta priorità.\n\n"
                "Esempi:\n"
                "<code>gestione letti ospedalieri</code>\n"
                "<code>!terapia intensiva digitale</code>\n\n"
                "Oppure annulla:",
                reply_markup=BACK_MENU)

    # ── Prompt rimozione keyword ──────────────────────────────────────────────
    elif data == "kw_del_prompt":
        conversation_state[chat_id] = "waiting_kw_del"
        tg_edit(chat_id, msg_id,
                "➖ <b>Rimuovi keyword</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Scrivi la keyword esatta da rimuovere\n"
                "(copia dalla lista keyword).\n\n"
                "Oppure annulla:",
                reply_markup=BACK_MENU)

    # ── Info ──────────────────────────────────────────────────────────────────
    elif data == "info":
        all_kws, high, _ = load_keywords()
        tg_edit(chat_id, msg_id,
                f"ℹ️ <b>KIRANET Bandi Bot v6</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📡 Fonte: pubblicitalegale.anticorruzione.it\n"
                f"🔑 {len(all_kws)} keyword | ⭐ {len(high)} alta priorità\n"
                f"⏰ Ricerca automatica: <b>ogni giorno alle 07:15</b>\n"
                f"📁 Keyword file: <code>{KEYWORDS_PATH}</code>\n"
                f"🏢 KIRANET S.r.l.",
                reply_markup=BACK_MENU)

    # ── Torna al menu ─────────────────────────────────────────────────────────
    elif data == "menu":
        conversation_state.pop(chat_id, None)
        tg_edit(chat_id, msg_id, menu_text(), reply_markup=MAIN_MENU)


def handle_message(message, conn):
    chat_id = message["chat"]["id"]
    text    = message.get("text", "").strip()

    if str(chat_id) not in TELEGRAM_CHAT_IDS:
        return

    # Comandi
    if text in ["/start", "/menu"]:
        conversation_state.pop(chat_id, None)
        tg_send(chat_id, menu_text(), reply_markup=MAIN_MENU)
        return

    # Gestione stato conversazione
    state = conversation_state.get(chat_id)

    if state == "waiting_kw_add":
        conversation_state.pop(chat_id, None)
        kw = text.strip()
        is_high = kw.startswith("!")
        if is_high:
            kw = kw[1:].strip()

        if not kw:
            tg_send(chat_id, "❌ Keyword vuota. Riprova dal menu.", reply_markup=MAIN_MENU)
            return

        all_kws, high, enti = load_keywords()
        kw_norm = kw.lower()

        if kw_norm in [k.lower() for k in all_kws]:
            tg_send(chat_id, f"⚠️ La keyword <b>{kw}</b> è già presente.",
                    reply_markup=MAIN_MENU)
            return

        all_kws.append(kw_norm)
        if is_high:
            high.add(kw_norm)

        if save_keywords(all_kws, list(high), enti):
            prio = " (⭐ alta priorità)" if is_high else ""
            tg_send(chat_id,
                    f"✅ Keyword aggiunta{prio}:\n<b>{kw_norm}</b>\n\n"
                    f"Totale keyword: {len(all_kws)}",
                    reply_markup=MAIN_MENU)
            log.info(f"Keyword aggiunta: '{kw_norm}' (high={is_high})")
        else:
            tg_send(chat_id, "❌ Errore nel salvataggio. Riprova.", reply_markup=MAIN_MENU)

    elif state == "waiting_kw_del":
        conversation_state.pop(chat_id, None)
        kw = text.strip().lower()

        all_kws, high, enti = load_keywords()
        all_kws_lower = [k.lower() for k in all_kws]

        if kw not in all_kws_lower:
            tg_send(chat_id,
                    f"⚠️ Keyword <b>{kw}</b> non trovata.\n"
                    f"Usa '🔑 Vedi keyword' per vedere la lista esatta.",
                    reply_markup=MAIN_MENU)
            return

        all_kws = [k for k in all_kws if k.lower() != kw]
        high.discard(kw)

        if save_keywords(all_kws, list(high), enti):
            tg_send(chat_id,
                    f"✅ Keyword rimossa:\n<b>{kw}</b>\n\n"
                    f"Keyword rimanenti: {len(all_kws)}",
                    reply_markup=MAIN_MENU)
            log.info(f"Keyword rimossa: '{kw}'")
        else:
            tg_send(chat_id, "❌ Errore nel salvataggio. Riprova.", reply_markup=MAIN_MENU)

    else:
        # Messaggio non atteso
        tg_send(chat_id,
                "Usa /menu per aprire il pannello di controllo.",
                reply_markup=MAIN_MENU)


# ── Modalità SEARCH (cron) ────────────────────────────────────────────────────
def run_search():
    log.info("══ KIRANET Bandi Bot v6 – ricerca automatica ══")
    conn = init_db()
    cleanup_old(conn)

    all_kws, _, _ = load_keywords()
    today = datetime.now().strftime("%d/%m/%Y")
    log.info(f"Data: {today} | Keyword attive: {len(all_kws)}")

    results = cerca_bandi(1, conn, send_unseen_only=True)
    log.info(f"Nuovi da inviare: {len(results)}")

    if results:
        for chat_id in TELEGRAM_CHAT_IDS:
            tg_send(chat_id,
                    f"🚨 <b>KIRANET Bandi Monitor</b>\n"
                    f"📅 {today}\n"
                    f"✅ <b>{len(results)} nuove gare</b> trovate:",
                    reply_markup=MAIN_MENU)
        time.sleep(1)
        for idx, (b, sc, reasons) in enumerate(results, 1):
            for chat_id in TELEGRAM_CHAT_IDS:
                tg_send(chat_id, format_bando(b, sc, reasons, idx, len(results)))
            mark_seen(conn, b["cig"])
            time.sleep(1.2)
        for chat_id in TELEGRAM_CHAT_IDS:
            tg_send(chat_id,
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🤖 Completato | Gare: {len(results)}\n"
                    f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                    reply_markup=MAIN_MENU)
    else:
        for chat_id in TELEGRAM_CHAT_IDS:
            tg_send(chat_id,
                    f"🔍 <b>KIRANET Bandi Monitor</b>\n"
                    f"📅 {today}\n"
                    f"✅ Nessuna nuova gara rilevante oggi.",
                    reply_markup=MAIN_MENU)

    conn.close()
    log.info("══ Fine ricerca ══")


# ── Modalità MENU (long polling) ──────────────────────────────────────────────
def run_menu():
    log.info("══ KIRANET Bandi Bot v6 – menu interattivo avviato ══")
    conn   = init_db()
    offset = 0

    for chat_id in TELEGRAM_CHAT_IDS:
        tg_send(chat_id,
                "🤖 <b>KIRANET Bandi Bot online!</b>\n"
                "Usa /menu per aprire il pannello.",
                reply_markup=MAIN_MENU)

    while True:
        try:
            updates = tg_get_updates(offset)
            for upd in updates:
                offset = upd["update_id"] + 1
                if "callback_query" in upd:
                    handle_callback(upd["callback_query"], conn)
                elif "message" in upd:
                    handle_message(upd["message"], conn)
        except Exception as e:
            log.error(f"Polling error: {e}")
            time.sleep(5)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "search"
    if arg == "menu":
        run_menu()
    else:
        run_search()
