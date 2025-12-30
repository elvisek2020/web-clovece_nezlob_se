# Člověče, nezlob se

Real-time multiplayer webová aplikace pro hru Člověče, nezlob se (Ludo) v prohlížeči.

## 📋 Popis

Online verze klasické deskové hry Člověče, nezlob se pro 2-4 hráče nebo solo režim. Hra běží v reálném čase pomocí WebSocket komunikace. Všichni hráči se připojují do jednoho společného lobby a hrají spolu. Aplikace podporuje také solo režim, kde jeden hráč hraje za všechny barvy.

## ✨ Funkce

- ✅ Real-time multiplayer hra pro 2-4 hráče
- ✅ Solo režim - jeden hráč hraje za všechny barvy
- ✅ WebSocket komunikace pro real-time aktualizace
- ✅ Lobby systém s ready mechanikou
- ✅ Automatické ukončení tahu při absenci legálních tahů
- ✅ Reconnect funkcionalita při ztrátě spojení
- ✅ SVG vizualizace hrací plochy
- ✅ Box-style UI komponenty
- ✅ Zobrazení statistik hráčů během hry

## 📖 Použití

### Multiplayer režim (2-4 hráči)

1. **Připojení**: Zadejte své jméno a klikněte na "Připojit se"
2. **Lobby**: Počkejte na další hráče (minimálně 2, maximálně 4)
3. **Výběr barvy**: Vyberte si barvu (pokud je dostupná)
4. **Připravenost**: Klikněte na "Připraven" když jste připraveni začít
5. **Spuštění hry**: Když jsou všichni připraveni, klikněte na "Spustit hru"
6. **Hraní**:
   - Hoďte kostkou kliknutím na "Hodit kostkou"
   - Pohybujte figurkami kliknutím na ně
   - Pokud hodíte 6, můžete házet znovu
   - Cíl: Dostat všechny 4 figurky do cíle

### Solo režim

1. **Připojení**: Zadejte své jméno a klikněte na "Solo režim"
2. **Automatické vytvoření botů**: Aplikace automaticky vytvoří virtuální hráče (boty) pro zbývající barvy při startu hry
3. **Hraní**: Hrajete za všechny barvy - při každém tahu můžete vybrat, kterou barvou chcete táhnout (solo hráč je vždy na tahu)
4. **Cíl**: Dostat všechny figurky všech barev do cíle
5. **Ukončení**: Můžete kdykoliv ukončit hru pomocí tlačítka "Ukončit hru"

## 🚀 Deployment

### Předpoklady

- Docker a Docker Compose

### Docker Compose

Aplikace je připravena pro spuštění pomocí Docker Compose. Soubor `docker-compose.yml` obsahuje veškerou potřebnou konfiguraci.

#### Spuštění

```bash
docker compose up -d --build
```

Aplikace bude dostupná na `http://localhost` (port 80 je mapován na port 8000 v kontejneru)

#### Konfigurace

Aplikace je konfigurována pomocí `docker-compose.yml`:

```yaml
services:
  app:
    # Pro vývoj použijte build:
    build:
      context: .
      dockerfile: Dockerfile
    # Pro produkci použijte image z GHCR:
    # image: ghcr.io/elvisek2020/web-clovece_nezlob_se:latest
    container_name: web-clovece_nezlob_se
    hostname: web-clovece_nezlob_se
    restart: unless-stopped
    ports:
      - "80:8000"
    environment:
      - PYTHONUNBUFFERED=1
      - LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    # Pro produkci přidejte síťovou konfiguraci:
    # networks:
    #   core:
    #     ipv4_address: 172.20.0.xxx

# Pro produkci odkomentujte:
# networks:
#   core:
#     external: true
```

#### Update aplikace

```bash
docker compose pull
docker compose up -d
```

#### Rollback na konkrétní verzi

V `docker-compose.yml` změňte image tag:

```yaml
services:
  app:
    image: ghcr.io/elvisek2020/web-clovece_nezlob_se:sha-<commit-sha>
```

### GitHub a CI/CD

#### Inicializace repozitáře

1. **Vytvoření GitHub repozitáře**:

   ```bash
   # Vytvořte nový repozitář na GitHubu
   # Název: web-clovece_nezlob_se
   ```
2. **Inicializace lokálního repozitáře**:

   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/elvisek2020/web-clovece_nezlob_se.git
   git push -u origin main
   ```
3. **Vytvoření GitHub Actions workflow**:

   Vytvořte soubor `.github/workflows/docker.yml` - viz [příklad workflow](.github/workflows/docker.yml) v tomto repozitáři.
4. **Nastavení viditelnosti image**:

   - Po prvním buildu jděte na GitHub → Packages
   - Najděte vytvořený package `web-clovece_nezlob_se`
   - V Settings → Change visibility nastavte na **Public**

#### Commitování změn a automatické buildy

1. **Proveďte změny v kódu**
2. **Commit a push**:

   ```bash
   git add .
   git commit -m "Popis změn"
   git push origin main
   ```
3. **Automatický build**:

   - Po push do `main` branch se automaticky spustí GitHub Actions workflow
   - Vytvoří se Docker image pro `linux/amd64` a `linux/arm64`
   - Image se nahraje do GHCR
   - Taguje se jako `latest` a `sha-<commit-sha>`
4. **Sledování buildu**:

   - GitHub → Actions → zobrazí se běžící workflow
   - Po dokončení je image dostupná na `ghcr.io/elvisek2020/web-clovece_nezlob_se:latest`

#### GitHub Container Registry (GHCR)

Aplikace je dostupná jako Docker image z GitHub Container Registry:

- **Latest**: `ghcr.io/elvisek2020/web-clovece_nezlob_se:latest`
- **Konkrétní commit**: `ghcr.io/elvisek2020/web-clovece_nezlob_se:sha-<commit-sha>`

Image je **veřejný** (public), takže není potřeba autentizace pro pull.

---

## 🔧 Technická dokumentace

### 🏗️ Architektura

Aplikace je postavena jako **real-time multiplayer hra** s následujícími charakteristikami:

- **Single-lobby systém**: Všichni hráči se připojují do jednoho společného lobby
- **WebSocket komunikace**: Veškerá real-time komunikace probíhá přes WebSocket
- **State-less frontend**: Frontend pouze zobrazuje stav přijatý ze serveru
- **Server-side validace**: Veškerá herní logika a validace probíhá na serveru
- **In-memory storage**: Všechna data jsou uložena v RAM (žádná databáze)
- **SVG vizualizace**: Hrací plocha je vizualizována pomocí SVG s anchor body pro pozicování figurek

### Technický stack

**Backend:**

- FastAPI (Python 3.11+)
- WebSockets pro real-time komunikaci
- Uvicorn jako ASGI server
- Python logging s konfigurovatelnou úrovní

**Frontend:**

- Vanilla JavaScript (ES6+)
- HTML5 + CSS3
- WebSocket API
- SVG pro vizualizaci hrací plochy

**Deployment:**

- Docker
- Docker Compose

### 📁 Struktura projektu

```
web-clovece_nezlob_se/
├── app/
│   ├── __init__.py
│   ├── models.py              # Datové modely (GameSession, Player, Piece, PieceStatus, GameStatus)
│   └── game_logic.py          # Herní logika (inicializace, pohyb, kontrola výhry, validace)
├── static/
│   ├── index.html             # Hlavní HTML stránka (login, lobby, game)
│   ├── style.css              # Styly (box-style komponenty)
│   ├── app.js                 # Frontend JavaScript (WebSocket komunikace, UI logika, SVG rendering)
│   ├── favicon.ico            # Favicon
│   └── images/
│       ├── board_modern_52.svg # SVG hrací plocha s anchor body
│       └── pozadi.png          # Pozadí hrací plochy
├── _docs/
│   ├── CHYBY_V_HERNI_LOGICE.md                    # Dokumentace nalezených chyb a oprav
│   ├── CURSOR_REBUILD_TAHY_A_CIL.md              # Specifikace pravidel pohybu figurek
│   ├── ARCHITEKTURA_A_NAVOD_PRO_PODOBNE_APLIKACE.md  # Architektura a návod
│   ├── QUICK_START_GUIDE.md                      # Rychlý start
│   └── ...                                       # Další dokumentace
├── main.py                    # FastAPI aplikace + WebSocket endpoint
├── requirements.txt           # Python závislosti
├── Dockerfile                 # Docker image definice
├── docker-compose.yml         # Docker Compose konfigurace
└── README.md                  # Tato dokumentace
```

### 🔧 API dokumentace

#### WebSocket endpoint

**URL**: `ws://localhost/ws` (nebo `ws://localhost:8000/ws` při lokálním vývoji)

[Detailní popis API zpráv najdete v dokumentaci - `_docs/` nebo v kódu aplikace]

### 💻 Vývoj

#### Přidání nových funkcí

1. **Backend změny**:

   - Herní logika: `app/game_logic.py`
   - WebSocket endpoint: `main.py`
   - Datové modely: `app/models.py`
2. **Frontend změny**:

   - UI logika: `static/app.js`
   - HTML struktura: `static/index.html`
   - Styly: `static/style.css` (používejte box-style komponenty)
3. **SVG hrací plocha**:

   - `static/images/board_modern_52.svg` - anchor body pro pozicování figurek
   - Formát: `track-{0..51}`, `home-{color}-{0..3}`, `lane-{color}-{0..3}`

#### Testování

- **Multiplayer**: Otevřete aplikaci ve více prohlížečích nebo záložkách
- **Solo režim**: Použijte tlačítko "Solo režim" pro testování bez dalších hráčů
- **Logy**: Sledujte serverové logy pomocí `docker logs web-clovece_nezlob_se -f`

#### Debugging

- Nastavte `LOG_LEVEL=DEBUG` v `docker-compose.yml` pro detailní logy
- Server loguje všechny důležité události s timestampy
- Frontend loguje chyby do konzole prohlížeče

#### Úroveň logování (`LOG_LEVEL`)

- `DEBUG` - zobrazí všechny logy včetně detailních debug informací (vývoj)
- `INFO` - zobrazí informační logy (výchozí, vhodné pro testování)
- `WARNING` - zobrazí pouze varování a chyby (doporučeno pro produkci)
- `ERROR` - zobrazí pouze chyby (minimální logování)
- `CRITICAL` - zobrazí pouze kritické chyby

Pro produkci doporučujeme nastavit `LOG_LEVEL=WARNING` nebo `LOG_LEVEL=ERROR`.

### 🎨 UI/UX

Aplikace používá **box-style komponenty** pro konzistentní vzhled:

- Všechny komponenty mají boxový vzhled s rámečky
- Konzistentní barvy a rozestupy
- Responzivní design
- SVG vizualizace hrací plochy s anchor body pro přesné pozicování figurek
- Automatické reconnect při ztrátě spojení (token se ukládá do sessionStorage)
- Zobrazení statistik hráčů během hry
- Barevné rozlišení hráčů v lobby i během hry

### 📝 Historie změn

#### v.20251229.0750

- ✅ **Opravena kritická chyba**: Automatické ukončení tahu, když hráč nemá žádné legální tahy
- ✅ **Opraveno logování**: Výsledek pohybu se nyní správně loguje (`action` místo `status`)
- ✅ **Vylepšeno**: Přidána kontrola možných tahů po hodu kostkou
- ✅ **Vylepšeno**: Automatické ukončení tahu při šestce bez legálních tahů (extra hod propadne)

### 🐛 Známé problémy

- Žádné kritické problémy - všechny nalezené chyby byly opraveny
- Solo režim: Boti (virtuální hráči) jsou automaticky vytvářeni při startu hry, ale nejsou inteligentní - hrají náhodně

### 📚 Další zdroje

- [FastAPI dokumentace](https://fastapi.tiangolo.com/)
- [WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [Docker dokumentace](https://docs.docker.com/)
- [SVG dokumentace](https://developer.mozilla.org/en-US/docs/Web/SVG)

Více informací najdete v dokumentaci:

- `_docs/CHYBY_V_HERNI_LOGICE.md` - Nalezené chyby a opravy
- `_docs/CURSOR_REBUILD_TAHY_A_CIL.md` - Specifikace pravidel pohybu figurek
- `_docs/ARCHITEKTURA_A_NAVOD_PRO_PODOBNE_APLIKACE.md` - Architektura a návod pro podobné aplikace

## 📄 Licence

Tento projekt je vytvořen pro vzdělávací účely.
