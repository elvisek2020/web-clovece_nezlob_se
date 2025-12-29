from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Optional
from app.models import GameSession, Player, GameStatus
from app.game_logic import initialize_game, roll_dice, move_piece, end_turn, check_game_end, can_move_piece, has_pieces_on_board, get_can_move_pawn_ids

# Nastavení logování s timestampy
# Úroveň logování lze nastavit přes environment variable LOG_LEVEL (DEBUG, INFO, WARNING, ERROR, CRITICAL)
# V produkci nastav LOG_LEVEL=WARNING nebo ERROR pro minimalizaci logů
import os
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Online Člověče, nezlob se")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Globální stav hry
game_session = GameSession()
connected_clients: Dict[str, WebSocket] = {}
player_tokens: Dict[str, str] = {}


async def broadcast_to_all(message: dict):
    """Pošle zprávu všem připojeným klientům"""
    disconnected = []
    for player_id, websocket in connected_clients.items():
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Chyba při odesílání zprávy hráči {player_id}: {e}")
            disconnected.append(player_id)
    
    # Odstraní odpojené klienty
    for player_id in disconnected:
        connected_clients.pop(player_id, None)


async def send_to_player(player_id: str, message: dict):
    """Pošle zprávu konkrétnímu hráči"""
    if player_id in connected_clients:
        try:
            await connected_clients[player_id].send_json(message)
        except Exception as e:
            logger.error(f"Chyba při odesílání zprávy hráči {player_id}: {e}")


async def send_lobby_state():
    """Pošle stav lobby všem hráčům"""
    can_start = (
        len(game_session.players) >= 2 and
        all(p.ready for p in game_session.players) and
        game_session.status == GameStatus.WAITING
    ) or (
        game_session.solo_mode and
        len(game_session.players) >= 1 and
        all(p.ready for p in game_session.players) and
        game_session.status == GameStatus.WAITING
    )
    
    # Zjisti dostupné barvy
    used_colors = {p.color for p in game_session.players if p.color}
    available_colors = [c for c in game_session.COLORS if c not in used_colors]
    
    await broadcast_to_all({
        "type": "lobby_state",
        "status": game_session.status.value,
        "players": [p.to_dict() for p in game_session.players],
        "can_start": can_start,
        "available_colors": available_colors,
        "all_colors": game_session.COLORS,
        "solo_mode": game_session.solo_mode
    })


async def send_game_state(for_player_id: Optional[str] = None):
    """Pošle herní stav všem hráčům"""
    state = game_session.to_dict(for_player_id=for_player_id)
    state["type"] = "game_state"
    
    await broadcast_to_all(state)


@app.get("/")
async def get_index():
    """Vrátí hlavní HTML stránku"""
    return FileResponse("static/index.html")


@app.get("/health")
async def health_check():
    """Healthcheck endpoint pro Docker"""
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    player_id = None
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type", "unknown")
            # Logování pouze důležitých zpráv (ne game_state, které se posílá často)
            if msg_type not in ["game_state", "lobby_state"]:
                logger.info(f"[WS_MSG] Přijatá zpráva od {player_id or 'unknown'}: type={msg_type}")
            
            if msg_type == "join":
                # Připojení nového hráče
                name = message.get("name", "").strip()
                if not name:
                    await websocket.send_json({"type": "error", "message": "Jméno je povinné"})
                    continue
                
                solo_mode = message.get("solo_mode", False)
                
                # V solo režimu může být pouze jeden hráč
                if solo_mode:
                    # Pokud už existuje solo režim s hráči, nelze připojit dalšího
                    if game_session.solo_mode and len(game_session.players) >= 1:
                        await websocket.send_json({"type": "error", "message": "V solo režimu může být pouze jeden hráč"})
                        continue
                    # Nastav solo režim (i když byl předtím resetován)
                    game_session.solo_mode = True
                else:
                    if len(game_session.players) >= 4:
                        await websocket.send_json({"type": "error", "message": "Lobby je plné (max 4 hráči)"})
                        continue
                    # Pokud už existuje solo režim s hráči, nelze připojit normálního hráče
                    if game_session.solo_mode and len(game_session.players) >= 1:
                        await websocket.send_json({"type": "error", "message": "Lobby je v solo režimu"})
                        continue
                
                # Zkontroluje, zda hráč s tímto jménem už existuje
                if any(p.name.lower() == name.lower() for p in game_session.players):
                    await websocket.send_json({"type": "error", "message": "Jméno je již obsazené"})
                    continue
                
                # Vytvoří nového hráče
                player_id = str(uuid.uuid4())
                token = str(uuid.uuid4())
                
                # Zkontroluj, zda je požadovaná barva dostupná
                requested_color = message.get("color")
                available_colors = game_session.COLORS.copy()
                # Odeber barvy, které už mají jiní hráči
                for p in game_session.players:
                    if p.color and p.color in available_colors:
                        available_colors.remove(p.color)
                
                # Pokud je požadovaná barva dostupná, použij ji
                if requested_color and requested_color in available_colors:
                    selected_color = requested_color
                elif available_colors:
                    # Pokud není požadovaná barva dostupná, použij první dostupnou
                    selected_color = available_colors[0]
                else:
                    # Pokud nejsou žádné dostupné barvy, použij první barvu
                    selected_color = game_session.COLORS[0]
                
                player = Player(
                    player_id=player_id,
                    name=name,
                    token=token,
                    color=selected_color if game_session.status == GameStatus.WAITING else None
                )
                
                game_session.players.append(player)
                connected_clients[player_id] = websocket
                player_tokens[player_id] = token
                
                # V solo režimu nastav solo_player_id
                if solo_mode:
                    game_session.solo_player_id = player_id
                
                logger.info(f"[JOIN] Hráč se připojuje: name={name}, solo_mode={solo_mode}, player_id={player_id}, color={selected_color}")
                
                await websocket.send_json({
                    "type": "joined",
                    "player_id": player_id,
                    "token": token,
                    "solo_mode": solo_mode
                })
                
                # Vždy pošli lobby_state (nový hráč není ve hře, i když hra probíhá)
                await send_lobby_state()
            
            elif msg_type == "reconnect":
                # Reconnect hráče
                token = message.get("token")
                if not token:
                    await websocket.send_json({"type": "error", "message": "Token je povinný"})
                    continue
                
                # Najde hráče podle tokenu
                player_id = None
                for pid, t in player_tokens.items():
                    if t == token:
                        player_id = pid
                        break
                
                if not player_id:
                    await websocket.send_json({"type": "error", "message": "Neplatný token"})
                    continue
                
                # Obnoví připojení
                connected_clients[player_id] = websocket
                
                await websocket.send_json({
                    "type": "reconnected",
                    "player_id": player_id
                })
                
                if game_session.status == GameStatus.WAITING:
                    await send_lobby_state()
                else:
                    await send_game_state(for_player_id=player_id)
            
            elif msg_type == "select_color":
                # Výběr barvy
                if not player_id:
                    await websocket.send_json({"type": "error", "message": "Nejste připojeni"})
                    continue
                
                if game_session.status != GameStatus.WAITING:
                    await websocket.send_json({"type": "error", "message": "Barvu lze změnit pouze před začátkem hry"})
                    continue
                
                player = game_session.get_player(player_id)
                if not player:
                    await websocket.send_json({"type": "error", "message": "Hráč nenalezen"})
                    continue
                
                requested_color = message.get("color")
                if not requested_color:
                    await websocket.send_json({"type": "error", "message": "Barva je povinná"})
                    continue
                
                # Zkontroluj, zda je barva dostupná
                used_colors = {p.color for p in game_session.players if p.player_id != player_id and p.color}
                if requested_color in used_colors:
                    await websocket.send_json({"type": "error", "message": "Tato barva je již obsazena"})
                    continue
                
                if requested_color not in game_session.COLORS:
                    await websocket.send_json({"type": "error", "message": "Neplatná barva"})
                    continue
                
                # Nastav barvu
                player.color = requested_color
                
                await send_lobby_state()
            
            elif msg_type == "set_ready":
                # Nastavení ready stavu
                if not player_id:
                    await websocket.send_json({"type": "error", "message": "Nejste připojeni"})
                    continue
                
                player = game_session.get_player(player_id)
                if not player:
                    await websocket.send_json({"type": "error", "message": "Hráč nenalezen"})
                    continue
                
                ready = message.get("ready", False)
                player.ready = ready
                
                await send_lobby_state()
            
            elif msg_type == "start_game":
                # Spuštění hry
                if not player_id:
                    await websocket.send_json({"type": "error", "message": "Nejste připojeni"})
                    continue
                logger.info(f"[START_GAME] Hráč {player_id} ({player.name if player else 'unknown'}) spouští hru")
                
                if game_session.status != GameStatus.WAITING:
                    await websocket.send_json({"type": "error", "message": "Hra již běží"})
                    continue
                
                # Solo režim je už nastaven při join
                if game_session.solo_mode:
                    if len(game_session.players) < 1:
                        await websocket.send_json({"type": "error", "message": "Potřebujete alespoň 1 hráče"})
                        continue
                    # V solo režimu vytvoříme virtuální hráče pro zbývající barvy
                    available_colors = game_session.COLORS.copy()
                    for p in game_session.players:
                        if p.color and p.color in available_colors:
                            available_colors.remove(p.color)
                    # Vytvoříme virtuální hráče pro zbývající barvy (až do 4 hráčů celkem)
                    while len(game_session.players) < 4 and available_colors:
                        virtual_color = available_colors.pop(0)
                        virtual_player = Player(
                            player_id=str(uuid.uuid4()),
                            name=f"Bot {virtual_color.capitalize()}",
                            token=str(uuid.uuid4()),
                            color=virtual_color
                        )
                        virtual_player.ready = True
                        game_session.players.append(virtual_player)
                else:
                    if len(game_session.players) < 2:
                        await websocket.send_json({"type": "error", "message": "Potřebujete alespoň 2 hráče"})
                        continue
                
                if not all(p.ready for p in game_session.players):
                    await websocket.send_json({"type": "error", "message": "Všichni hráči musí být ready"})
                    continue
                
                try:
                    initialize_game(game_session)
                    await broadcast_to_all({
                        "type": "game_started",
                        "message": "Hra začala!",
                        "solo_mode": game_session.solo_mode
                    })
                    await send_game_state()
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": str(e)})
            
            elif msg_type == "roll_dice":
                # Hod kostkou
                if not player_id:
                    await websocket.send_json({"type": "error", "message": "Nejste připojeni"})
                    continue
                logger.info(f"[ROLL_DICE] Hráč {player_id} ({player.name if player else 'unknown'}) hází kostkou")
                
                if game_session.status != GameStatus.PLAYING:
                    await websocket.send_json({"type": "error", "message": "Hra neběží"})
                    continue
                
                # V solo režimu může hrát solo hráč za všechny
                if game_session.solo_mode:
                    if game_session.solo_player_id != player_id:
                        await websocket.send_json({"type": "error", "message": "Není váš tah"})
                        continue
                    # V solo režimu hráč hraje za current_player_id
                    current_player = game_session.get_current_player()
                    if not current_player:
                        await websocket.send_json({"type": "error", "message": "Aktuální hráč nenalezen"})
                        continue
                    player = current_player
                else:
                    if game_session.current_player_id != player_id:
                        await websocket.send_json({"type": "error", "message": "Není váš tah"})
                        continue
                    player = game_session.get_player(player_id)
                    if not player:
                        await websocket.send_json({"type": "error", "message": "Hráč nenalezen"})
                        continue
                
                if not game_session.can_roll_dice:
                    await websocket.send_json({"type": "error", "message": "Nemůžete házet kostkou"})
                    continue
                
                dice_roll = roll_dice()
                game_session.last_dice_roll = dice_roll
                logger.info(f"[ROLL_DICE] Hráč {player_id} ({player.name if player else 'unknown'}) hodil: {dice_roll}")
                
                # Aktualizuj statistiky - šestky
                if dice_roll == 6:
                    player.stats_sixes += 1
                
                # Zkontroluje, zda má hráč figurky na ploše
                has_on_board = has_pieces_on_board(game_session, player)
                
                # Pro solo režim použijeme current_player_id místo player_id
                current_player_id_for_turn = player.player_id if not game_session.solo_mode else game_session.current_player_id
                
                # Zkontroluj, zda má hráč nějaké možné tahy
                can_move_pawn_ids = get_can_move_pawn_ids(game_session, player, dice_roll)
                has_valid_moves = len(can_move_pawn_ids) > 0
                
                turn_ended_automatically = False
                
                if dice_roll == 6:
                    # Hodil 6 - může nasadit figurku nebo hýbat, pak hází znovu
                    if not has_valid_moves:
                        # Nemá žádné možné tahy - extra hod propadne (MVP)
                        logger.info(f"[TURN_END] Hráč {player_id} ({player.name if player else 'unknown'}) hodil 6, ale nemá žádné možné tahy - extra hod propadne")
                        end_turn(game_session, dice_roll, after_move=False)
                        turn_ended_automatically = True
                    else:
                        game_session.can_roll_dice = False  # Musí nejdříve pohnout figurkou
                elif has_on_board:
                    # Má figurky na ploše - může s nimi hýbat, tah končí po pohybu
                    if not has_valid_moves:
                        # Nemá žádné možné tahy - automaticky ukončit tah
                        logger.info(f"[TURN_END] Hráč {player_id} ({player.name if player else 'unknown'}) nemá žádné možné tahy - tah končí")
                        end_turn(game_session, dice_roll, after_move=False)
                        turn_ended_automatically = True
                    else:
                        game_session.can_roll_dice = False
                else:
                    # Nemá figurky na ploše - první nasazení
                    initial_rolls = game_session.initial_rolls_remaining.get(current_player_id_for_turn, 0)
                    if initial_rolls > 0:
                        # Může házet znovu (max 3x)
                        game_session.initial_rolls_remaining[current_player_id_for_turn] = initial_rolls - 1
                        game_session.can_roll_dice = True
                    else:
                        # Vyčerpal 3 pokusy - tah končí
                        game_session.can_roll_dice = False
                        end_turn(game_session, dice_roll, after_move=False)
                        turn_ended_automatically = True
                
                await broadcast_to_all({
                    "type": "dice_rolled",
                    "player_id": current_player_id_for_turn,
                    "player_name": player.name,
                    "dice_roll": dice_roll
                })
                
                await send_game_state()
            
            elif msg_type == "move_piece":
                # Pohyb figurkou
                if not player_id:
                    await websocket.send_json({"type": "error", "message": "Nejste připojeni"})
                    continue
                
                if game_session.status != GameStatus.PLAYING:
                    await websocket.send_json({"type": "error", "message": "Hra neběží"})
                    continue
                
                # V solo režimu může hrát solo hráč za všechny
                if game_session.solo_mode:
                    if game_session.solo_player_id != player_id:
                        await websocket.send_json({"type": "error", "message": "Není váš tah"})
                        continue
                    # V solo režimu může hráč hrát za current_player_id
                    # Pokud chce hrát za jiného hráče, můžeme to povolit přes piece_id
                else:
                    if game_session.current_player_id != player_id:
                        await websocket.send_json({"type": "error", "message": "Není váš tah"})
                        continue
                
                if game_session.can_roll_dice:
                    await websocket.send_json({"type": "error", "message": "Nejdříve hoďte kostkou"})
                    continue
                
                piece_id = message.get("piece_id")
                if not piece_id:
                    await websocket.send_json({"type": "error", "message": "piece_id je povinný"})
                    continue
                
                # V solo režimu může hráč hrát za current_player_id
                current_player = game_session.get_current_player()
                if not current_player:
                    await websocket.send_json({"type": "error", "message": "Aktuální hráč nenalezen"})
                    continue
                
                # V solo režimu použijeme current_player, jinak player_id
                if game_session.solo_mode:
                    player = current_player
                else:
                    player = game_session.get_player(player_id)
                    if not player:
                        await websocket.send_json({"type": "error", "message": "Hráč nenalezen"})
                        continue
                
                piece = next((p for p in player.pieces if p.piece_id == piece_id), None)
                if not piece:
                    await websocket.send_json({"type": "error", "message": "Figurka nenalezena"})
                    continue
                
                logger.info(f"[MOVE_REQUEST] Hráč {player_id} ({player.name if player else 'unknown'}) chce pohnout figurkou {piece_id}, dice={game_session.last_dice_roll}")
                
                if not can_move_piece(game_session, player, piece, game_session.last_dice_roll):
                    logger.warning(f"[MOVE_REJECTED] Hráč {player_id} ({player.name if player else 'unknown'}) - nelze pohnout figurkou {piece_id}")
                    await websocket.send_json({"type": "error", "message": "Nelze pohnout figurkou"})
                    continue
                
                try:
                    result = move_piece(game_session, player, piece, game_session.last_dice_roll)
                    logger.info(f"[MOVE_SUCCESS] Hráč {player_id} ({player.name}) pohnul figurkou {piece_id}, výsledek: {result.get('action', 'unknown')}")
                    
                    await broadcast_to_all({
                        "type": "piece_moved",
                        "player_id": player_id,
                        "player_name": player.name,
                        "result": result
                    })
                    
                    # Zkontroluje konec hry
                    winner_id = check_game_end(game_session)
                    if winner_id:
                        winner = game_session.get_player(winner_id)
                        await broadcast_to_all({
                            "type": "game_end",
                            "winner_id": winner_id,
                            "winner_name": winner.name
                        })
                    else:
                        # Ukončí tah (po pohybu figurky)
                        end_turn(game_session, game_session.last_dice_roll, after_move=True)
                    
                    await send_game_state()
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": str(e)})
            
            elif msg_type == "skip_turn":
                # Přeskočení tahu (pokud nelze pohnout žádnou figurkou)
                if not player_id:
                    await websocket.send_json({"type": "error", "message": "Nejste připojeni"})
                    continue
                
                if game_session.status != GameStatus.PLAYING:
                    await websocket.send_json({"type": "error", "message": "Hra neběží"})
                    continue
                
                if game_session.current_player_id != player_id:
                    await websocket.send_json({"type": "error", "message": "Není váš tah"})
                    continue
                
                if game_session.can_roll_dice:
                    await websocket.send_json({"type": "error", "message": "Nejdříve hoďte kostkou"})
                    continue
                
                # Ukončí tah
                end_turn(game_session, game_session.last_dice_roll)
                
                await broadcast_to_all({
                    "type": "turn_skipped",
                    "player_id": player_id,
                    "player_name": game_session.get_player(player_id).name
                })
                
                await send_game_state()
            
            elif msg_type == "leave_lobby":
                # Odejít z lobby
                if player_id:
                    game_session.players = [p for p in game_session.players if p.player_id != player_id]
                    connected_clients.pop(player_id, None)
                    player_tokens.pop(player_id, None)
                    
                    if game_session.status == GameStatus.WAITING:
                        await send_lobby_state()
                    elif len(game_session.players) < 2:
                        # Pokud zbývá méně než 2 hráči, resetuj hru
                        game_session.status = GameStatus.WAITING
                        game_session.current_player_id = None
                        await broadcast_to_all({
                            "type": "game_reset",
                            "message": "Hra byla resetována - příliš málo hráčů"
                        })
                        await send_lobby_state()
            
            elif msg_type == "end_solo_game":
                # Ukončení hry v solo režimu (bez potvrzování)
                if not player_id:
                    await websocket.send_json({"type": "error", "message": "Nejste připojeni"})
                    continue
                
                if not game_session.solo_mode or game_session.solo_player_id != player_id:
                    await websocket.send_json({"type": "error", "message": "Tuto akci lze provést pouze v solo režimu"})
                    continue
                
                # Odstranění hráče a všech virtuálních hráčů (botů) a reset hry
                game_session.players = []  # Odstraníme všechny hráče (včetně botů)
                connected_clients.pop(player_id, None)
                player_tokens.pop(player_id, None)
                
                # Reset hry
                game_session.status = GameStatus.WAITING
                game_session.current_player_id = None
                game_session.solo_mode = False
                game_session.solo_player_id = None
                
                # Reset dalších stavů hry
                game_session.last_dice_roll = 0
                game_session.can_roll_dice = True
                game_session.initial_rolls_remaining = {}
                game_session.winner_id = None
                
                # Odeslání potvrzení klientovi
                await websocket.send_json({
                    "type": "solo_game_ended",
                    "message": "Hra byla ukončena"
                })
            
            else:
                await websocket.send_json({"type": "error", "message": f"Neznámý typ zprávy: {msg_type}"})
    
    except WebSocketDisconnect:
        logger.info(f"[WS_DISCONNECT] Klient {player_id} se odpojil")
    except Exception as e:
        logger.error(f"Chyba v WebSocket: {e}")
    finally:
        if player_id:
            connected_clients.pop(player_id, None)

