# Online Člověče, nezlob se

Real-time multiplayer webová aplikace pro hru Člověče, nezlob se (Ludo) v prohlížeči.

## 📋 Popis

Online verze klasické deskové hry Člověče, nezlob se pro 2-4 hráče nebo solo režim. Hra běží v reálném čase pomocí WebSocket komunikace. Všichni hráči se připojují do jednoho společného lobby a hrají spolu. Aplikace podporuje také solo režim, kde jeden hráč hraje za všechny barvy.

## 🚀 Rychlý start

### Předpoklady

- Docker a Docker Compose
- Python 3.11+ (pro lokální vývoj)

### Spuštění pomocí Docker

```bash
docker compose up -d --build
```

Aplikace bude dostupná na `http://localhost` (port 80 je mapován na port 8000 v kontejneru)

### Konfigurace logování

Úroveň logování lze nastavit přes environment variable `LOG_LEVEL` v `docker-compose.yml`:
- `DEBUG` - zobrazí všechny logy včetně detailních debug informací (vývoj)
- `INFO` - zobrazí informační logy (výchozí, vhodné pro testování)
- `WARNING` - zobrazí pouze varování a chyby (doporučeno pro produkci)
- `ERROR` - zobrazí pouze chyby (minimální logování)
- `CRITICAL` - zobrazí pouze kritické chyby

**Příklad konfigurace v `docker-compose.yml`:**
```yaml
environment:
  - PYTHONUNBUFFERED=1
  - LOG_LEVEL=INFO  # Změňte na WARNING pro produkci
```

Pro produkci doporučujeme nastavit `LOG_LEVEL=WARNING` nebo `LOG_LEVEL=ERROR`.

### Lokální vývoj

```bash
# Instalace závislostí
pip install -r requirements.txt

# Spuštění serveru
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 🎮 Jak hrát

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

## 🏗️ Architektura

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

## 📁 Struktura projektu

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
├── main.py                     # FastAPI aplikace + WebSocket endpoint
├── requirements.txt            # Python závislosti
├── Dockerfile                  # Docker image definice
├── docker-compose.yml          # Docker Compose konfigurace
└── README.md                   # Tato dokumentace
```

## 🎯 Herní pravidla

### Základní pravidla

1. **Počet hráčů**: 2-4 hráči (nebo solo režim)
2. **Figurky**: Každý hráč má 4 figurky
3. **Cíl**: Dostat všechny 4 figurky do cíle
4. **Kostka**: Hráči hází kostkou (1-6)
5. **Šestka**: Pokud hráč hodí 6, může házet znovu (pokud má legální tah)

### Herní mechaniky

#### 1. Výstup z domečku (home → track)
- Figurka může opustit domeček **pouze s 6**
- Figurka se umístí na startovní pozici své barvy
- Pokud je startovní pozice obsazena soupeřem, soupeřova figurka se vyhodí do domečku
- Pokud je startovní pozice obsazena vlastní figurkou, tah není možný

#### 2. Pohyb po hlavní dráze (track)
- Figurky se pohybují po hlavní dráze (52 políček, track-0 až track-51)
- Modulo aritmetika: pohyb přes konec dráhy se přepočítá na začátek
- **Vyhození**: Pokud hráč přistane na poli s figurkou soupeře, soupeřova figurka se vyhodí do domečku
- **Blokování**: Nelze přistát na poli s vlastní figurkou (tah není možný)

#### 3. Vstup do cílové dráhy (track → home_lane)
- Figurka vstoupí do cílové dráhy, když překročí svůj ENTRY_INDEX (políčko těsně před startem)
- ENTRY_INDEX pro každou barvu:
  - Red: track-51
  - Blue: track-12
  - Yellow: track-25
  - Green: track-38
- Výpočet: pokud `dice_roll > stepsToEntry`, figurka vstoupí do lane
- Přestřelení: pokud by figurka přestřelila konec lane (více než 4 políčka), tah není možný

#### 4. Pohyb v cílové dráze (home_lane → finished)
- Figurky se pohybují v cílové dráze (4 políčka, lane-0 až lane-3)
- **Přesný dojezd**: Musí se trefit přesně - přestřelení není možné
- **Blokování**: Nelze přistát na políčku s vlastní figurkou
- **Cíl**: Když figurka dojde na lane-3, přejde do stavu `finished`

#### 5. Extra hod při šestce
- Pokud hráč hodí 6, má další hod
- Pokud hráč hodí 6, ale nemá žádný legální tah, extra hod propadne (MVP pravidlo)
- Pokud hráč hodí 6 a pohnul figurkou, hází znovu

#### 6. První nasazení
- Pokud hráč nemá žádné figurky na ploše, má 3 pokusy hodit 6ku
- Pokud nehodí 6ku ani po 3 pokusech, tah končí

#### 7. Ukončení tahu
- Tah končí automaticky, pokud hráč nemá žádné legální tahy
- Tah končí po pohybu figurky (pokud nehodil 6ku)
- Tah končí po vyčerpání 3 pokusů na první nasazení

### Konstanty hry

- **TRACK_LEN**: 52 (hlavní dráha má 52 políček)
- **LANE_LEN**: 4 (cílová dráha má 4 políčka)
- **START_INDEX**: 
  - Red: 0
  - Blue: 13
  - Yellow: 26
  - Green: 39
- **ENTRY_INDEX**: 
  - Red: 51
  - Blue: 12
  - Yellow: 25
  - Green: 38

## 🔧 API dokumentace

### WebSocket endpoint

**URL**: `ws://localhost/ws` (nebo `ws://localhost:8000/ws` při lokálním vývoji)

### Zprávy od klienta k serveru

#### `join`
Připojení hráče do lobby.

```json
{
  "type": "join",
  "name": "Jméno hráče",
  "solo_mode": false
}
```

#### `set_ready`
Označení hráče jako připraveného.

```json
{
  "type": "set_ready"
}
```

#### `start_game`
Spuštění hry (pouze pokud jsou všichni připraveni).

```json
{
  "type": "start_game"
}
```

#### `roll_dice`
Hod kostkou.

```json
{
  "type": "roll_dice"
}
```

#### `move_piece`
Pohyb figurkou.

```json
{
  "type": "move_piece",
  "piece_id": "uuid-figurky"
}
```

#### `skip_turn`
Přeskočení tahu (pokud nelze pohnout žádnou figurkou). **Poznámka**: V novějších verzích se tah ukončuje automaticky, pokud hráč nemá žádné legální tahy.

```json
{
  "type": "skip_turn"
}
```

#### `select_color`
Výběr barvy hráče (pouze před začátkem hry).

```json
{
  "type": "select_color",
  "color": "red"
}
```

#### `reconnect`
Připojení hráče po ztrátě spojení (používá token z sessionStorage).

```json
{
  "type": "reconnect",
  "token": "uuid-tokenu"
}
```

#### `leave_lobby`
Odejít z lobby.

```json
{
  "type": "leave_lobby"
}
```

#### `end_solo_game`
Ukončení hry v solo režimu (pouze pro solo režim).

```json
{
  "type": "end_solo_game"
}
```

### Zprávy od serveru k klientovi

#### `lobby_state`
Stav lobby (posílá se při změně).

```json
{
  "type": "lobby_state",
  "status": "waiting",
  "players": [...],
  "can_start": true,
  "available_colors": ["red", "blue"],
  "all_colors": ["red", "blue", "green", "yellow"],
  "solo_mode": false
}
```

#### `game_state`
Herní stav (posílá se při změně).

```json
{
  "type": "game_state",
  "status": "playing",
  "current_player_id": "uuid",
  "last_dice_roll": 4,
  "can_roll_dice": true,
  "winner_id": null,
  "solo_mode": false,
  "solo_player_id": "uuid",
  "players": [...]
}
```

#### `dice_rolled`
Informace o hodu kostkou.

```json
{
  "type": "dice_rolled",
  "player_id": "uuid",
  "player_name": "Jméno",
  "dice_roll": 6,
  "can_move_pawn_ids": ["uuid1", "uuid2"],
  "turn_ended_automatically": false
}
```

#### `piece_moved`
Informace o pohybu figurkou.

```json
{
  "type": "piece_moved",
  "player_id": "uuid",
  "player_name": "Jméno",
  "result": {
    "action": "piece_moved",
    "piece_id": "uuid",
    "old_position": 10,
    "new_position": 14
  }
}
```

#### `game_end`
Konec hry.

```json
{
  "type": "game_end",
  "winner_id": "uuid",
  "winner_name": "Jméno"
}
```

#### `error`
Chybová zpráva.

```json
{
  "type": "error",
  "message": "Popis chyby"
}
```

#### `joined`
Potvrzení připojení hráče.

```json
{
  "type": "joined",
  "player_id": "uuid",
  "token": "uuid-tokenu",
  "solo_mode": false
}
```

#### `reconnected`
Potvrzení úspěšného reconnectu.

```json
{
  "type": "reconnected",
  "player_id": "uuid"
}
```

#### `turn_skipped`
Informace o přeskočení tahu.

```json
{
  "type": "turn_skipped",
  "player_id": "uuid",
  "player_name": "Jméno"
}
```

#### `game_reset`
Informace o resetu hry (např. když odejde příliš mnoho hráčů).

```json
{
  "type": "game_reset",
  "message": "Hra byla resetována - příliš málo hráčů"
}
```

#### `solo_game_ended`
Potvrzení ukončení solo hry.

```json
{
  "type": "solo_game_ended",
  "message": "Hra byla ukončena"
}
```

## 🔧 Vývoj

### Přidání nových funkcí

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

### Testování

- **Multiplayer**: Otevřete aplikaci ve více prohlížečích nebo záložkách
- **Solo režim**: Použijte tlačítko "Solo režim" pro testování bez dalších hráčů
- **Logy**: Sledujte serverové logy pomocí `docker logs web-clovece_nezlob_se -f`

### Debugging

- Nastavte `LOG_LEVEL=DEBUG` v `docker-compose.yml` pro detailní logy
- Server loguje všechny důležité události s timestampy
- Frontend loguje chyby do konzole prohlížeče

## 📝 Historie změn

### V1.0.2 (2025-12-28)
- ✅ **Opravena kritická chyba**: Automatické ukončení tahu, když hráč nemá žádné legální tahy
- ✅ **Opraveno logování**: Výsledek pohybu se nyní správně loguje (`action` místo `status`)
- ✅ **Vylepšeno**: Přidána kontrola možných tahů po hodu kostkou
- ✅ **Vylepšeno**: Automatické ukončení tahu při šestce bez legálních tahů (extra hod propadne)

### V1.0.1 (2025-12-28)
- ✅ Opravena duplikace statistik šestek
- ✅ Opravena nekonzistentní logika `isMyTurn` v frontendu
- ✅ Opravena logika ukončení tahu při šestce bez pohybu
- ✅ Kompletní testování solo režimu
- ✅ Dokumentace nalezených chyb a oprav
- ✅ Přidáno logování s timestampy
- ✅ Konfigurovatelná úroveň logování přes environment variable

### V1.0.0 (2024)
- Základní implementace Ludo hry
- WebSocket real-time komunikace
- Lobby systém s ready mechanikou
- Herní logika: pohyb figurek, kontrola výhry
- Box-style UI komponenty
- Reconnect funkcionalita
- Docker podpora
- Solo režim
- SVG vizualizace hrací plochy

## 🐛 Známé problémy

- Žádné kritické problémy - všechny nalezené chyby byly opraveny
- Solo režim: Boti (virtuální hráči) jsou automaticky vytvářeni při startu hry, ale nejsou inteligentní - hrají náhodně

## 📋 Testování

Kompletní testování solo režimu bylo provedeno. Všechny nalezené chyby byly opraveny. 

Více informací najdete v dokumentaci:
- `_docs/CHYBY_V_HERNI_LOGICE.md` - Nalezené chyby a opravy
- `_docs/CURSOR_REBUILD_TAHY_A_CIL.md` - Specifikace pravidel pohybu figurek
- `_docs/ARCHITEKTURA_A_NAVOD_PRO_PODOBNE_APLIKACE.md` - Architektura a návod pro podobné aplikace

## 🎨 UI/UX

Aplikace používá **box-style komponenty** pro konzistentní vzhled:
- Všechny komponenty mají boxový vzhled s rámečky
- Konzistentní barvy a rozestupy
- Responzivní design
- SVG vizualizace hrací plochy s anchor body pro přesné pozicování figurek
- Automatické reconnect při ztrátě spojení (token se ukládá do sessionStorage)
- Zobrazení statistik hráčů během hry
- Barevné rozlišení hráčů v lobby i během hry

## 📚 Další zdroje

- [FastAPI dokumentace](https://fastapi.tiangolo.com/)
- [WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [Docker dokumentace](https://docs.docker.com/)
- [SVG dokumentace](https://developer.mozilla.org/en-US/docs/Web/SVG)

## 🚀 Deployment (Synology)

### Nasazení přes Container Manager

1. **Připravte si `docker-compose.yml`** (již připraven v projektu)

2. **V Synology Container Manageru**:
   - Otevřete **Container Manager** → **Project**
   - Vytvořte nový projekt nebo použijte existující
   - Nahrajte nebo zkopírujte obsah `docker-compose.yml`

3. **Spuštění**:
   - Projekt se automaticky spustí po vytvoření
   - Aplikace bude dostupná na nakonfigurovaném portu (výchozí: 80)

### Update aplikace

```bash
# V adresáři s docker-compose.yml
docker compose pull
docker compose up -d
```

### Rollback na konkrétní verzi

V `docker-compose.yml` změňte image tag:

```yaml
services:
  app:
    image: ghcr.io/elvisek2020/web-clovece_nezlob_se:sha-<commit-sha>
```

Například:
```yaml
image: ghcr.io/elvisek2020/web-clovece_nezlob_se:sha-abc123def456
```

### GitHub Container Registry (GHCR)

Image je dostupný na: `ghcr.io/elvisek2020/web-clovece_nezlob_se`

- **Latest**: `ghcr.io/elvisek2020/web-clovece_nezlob_se:latest`
- **Konkrétní commit**: `ghcr.io/elvisek2020/web-clovece_nezlob_se:sha-<commit-sha>`

Image je **veřejný** (public), takže není potřeba autentizace pro pull.

### Automatické buildy

Při každém push do `main` branch se automaticky:
1. Vytvoří Docker image pro `linux/amd64` a `linux/arm64`
2. Image se nahraje do GHCR
3. Taguje se jako `latest` a `sha-<commit-sha>`

## 📄 Licence

Tento projekt je vytvořen pro vzdělávací účely.
