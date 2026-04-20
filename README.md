# KIRANET Bandi Bot 🤖

Monitora quotidianamente la piattaforma ANAC (pubblicitalegale.anticorruzione.it)
e invia via Telegram le gare di appalto rilevanti per KIRANET S.r.l.

---

## Requisiti

- Docker + Docker Compose (già presente su mabalu.it)
- Un Bot Telegram (creato via @BotFather)
- Chat ID del destinatario (utente, gruppo o canale)

---

## Setup rapido

### 1. Crea il Bot Telegram

1. Apri Telegram, cerca **@BotFather**
2. Invia `/newbot` e segui le istruzioni
3. Copia il **token** che ti viene dato (es. `123456789:AABBCCDDEEFFaabb...`)

### 2. Ottieni il Chat ID

Per un **gruppo o canale**: aggiungi il bot al gruppo, poi invia un messaggio e visita:
```
https://api.telegram.org/bot<TOKEN>/getUpdates
```
Il Chat ID del gruppo inizia con `-100`.

Per un **utente singolo**: usa `@userinfobot` su Telegram.

### 3. Clona/copia il progetto sul server

```bash
# Sul server mabalu.it
cd /opt/docker  # o la tua directory Docker preferita
mkdir bandi-bot && cd bandi-bot
# copia qui tutti i file del progetto
```

### 4. Configura le variabili d'ambiente

```bash
cp .env.example .env
nano .env
```

Compila:
```
TELEGRAM_TOKEN=123456789:il_tuo_token
TELEGRAM_CHAT_ID=-100il_tuo_gruppo_id
```

### 5. Build e avvio

```bash
docker compose up -d --build
```

### 6. Test immediato

```bash
# Esecuzione manuale una tantum per testare
docker compose run --rm bandi-bot now
```

### 7. Verifica i log

```bash
docker compose logs -f
# oppure nel volume
docker exec kiranet-bandi-bot cat /data/bandi_bot.log
```

---

## Struttura del messaggio Telegram

```
⭐ GARA 1/5 [score: 65]
📋 Fornitura software cartella clinica elettronica - ASL Napoli 2 Nord
🏛 SA: ASL NAPOLI 2 NORD
📅 Pubblicata: 2025-04-19 | Scade: 2025-05-20
🔑 CIG: B1234567XX
💰 Importo: €250,000.00
📌 ⭐ keyword prioritaria: 'cartella clinica elettronica' | PNRR/Missione 6 | ente d'interesse: ASL
🔗 Apri bando
```

### Legenda icone priorità:
- ⭐ = Alta priorità (score ≥ 40)
- 🔶 = Media priorità (score 20-39)
- 🔷 = Priorità standard (score 10-19)

---

## Configurazione avanzata (docker-compose.yml)

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `DAYS_BACK` | `1` | Giorni a ritroso da cercare |
| `MAX_RESULTS` | `100` | Max risultati per keyword |
| `CRON_SCHEDULE` | `15 7 * * *` | Orario esecuzione (crontab) |
| `RUN_ON_START` | `0` | Esegui all'avvio container |
| `LOG_LEVEL` | `INFO` | Verbosità log |

---

## Personalizzazione keyword e priorità

Modifica `bandi_bot.py`:

- **`KEYWORDS`**: lista completa di keyword da cercare
- **`HIGH_PRIORITY_KEYWORDS`**: keyword che aumentano lo score (+30 punti)
- **`ENTI_INTEREST`**: enti committenti di interesse (+15 punti)
- **`CPV_CODES`**: codici CPV di interesse (+20 punti)

---

## Aggiornamento

```bash
docker compose pull
docker compose up -d --build
```

---

## Troubleshooting

**Il bot non invia messaggi:**
```bash
# Verifica la configurazione Telegram
docker compose run --rm bandi-bot now
docker compose logs bandi-bot
```

**Nessun bando trovato:**
- Normale se oggi non ci sono gare nelle keyword configurate
- Prova ad aumentare `DAYS_BACK=7` per test retrospettivi

**Il sito ANAC ha cambiato le API:**
- Controlla i log per errori HTTP
- L'endpoint PVL può variare: aggiornare `PVL_SEARCH_URL` in `bandi_bot.py`
- Alternativa stabile: usare solo le API OCDS su `dati.anticorruzione.it`
