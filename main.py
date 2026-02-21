from contextlib import asynccontextmanager
import asyncio
import string
import secrets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import json
import re
import uuid
import logging
import time
import os
from collections import defaultdict
from typing import Dict, Optional
from app.models import GameSession, Player, GameStatus, PieceStatus
from app.game_logic import (
    initialize_game, roll_dice, move_piece, end_turn,
    check_game_end, can_move_piece, has_pieces_on_board, get_can_move_pawn_ids,
)

log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

# --- Konfigurace ---
MAX_WS_MESSAGE_SIZE = 4096
MAX_CONNECTIONS_PER_IP = 10
RATE_LIMIT_MESSAGES = 30
RATE_LIMIT_WINDOW = 10
PLAYER_NAME_MAX_LENGTH = 20
PLAYER_NAME_PATTERN = re.compile(r'^[\w\s\-áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]{1,20}$')
WS_PING_INTERVAL = 30
PLAYER_DISCONNECT_TIMEOUT = 120
CLEANUP_CHECK_INTERVAL = 15
MAX_ROOMS = 50
EMPTY_ROOM_TIMEOUT = 300  # smazat prázdnou místnost po 5 min
ROOM_CODE_LENGTH = 4


# ╔══════════════════════════════════════════════╗
# ║  Globální stav                               ║
# ╚══════════════════════════════════════════════╝

rooms: Dict[str, GameSession] = {}          # room_code -> session
connected_clients: Dict[str, WebSocket] = {}  # player_id -> ws
player_tokens: Dict[str, str] = {}          # player_id -> token
player_room: Dict[str, str] = {}            # player_id -> room_code
player_last_activity: Dict[str, float] = {}

ip_connections: Dict[str, int] = defaultdict(int)
rate_limit_buckets: Dict[str, list] = defaultdict(list)


# ╔══════════════════════════════════════════════╗
# ║  Pomocné funkce                              ║
# ╚══════════════════════════════════════════════╝

def generate_room_code() -> str:
    while True:
        code = ''.join(secrets.choice(string.ascii_uppercase) for _ in range(ROOM_CODE_LENGTH))
        if code not in rooms:
            return code


def get_client_ip(websocket: WebSocket) -> str:
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if websocket.client:
        return websocket.client.host
    return "unknown"


def check_rate_limit(client_key: str) -> bool:
    now = time.time()
    bucket = rate_limit_buckets[client_key]
    bucket[:] = [t for t in bucket if now - t < RATE_LIMIT_WINDOW]
    if len(bucket) >= RATE_LIMIT_MESSAGES:
        return True
    bucket.append(now)
    return False


def validate_player_name(name: str) -> Optional[str]:
    if not name:
        return "Jméno je povinné"
    if len(name) > PLAYER_NAME_MAX_LENGTH:
        return f"Jméno může mít maximálně {PLAYER_NAME_MAX_LENGTH} znaků"
    if not PLAYER_NAME_PATTERN.match(name):
        return "Jméno obsahuje nepovolené znaky"
    return None


def get_player_room(pid: str) -> Optional[GameSession]:
    code = player_room.get(pid)
    if code:
        return rooms.get(code)
    return None


def reset_room(room: GameSession):
    room.status = GameStatus.WAITING
    room.current_player_id = None
    room.last_dice_roll = 0
    room.can_roll_dice = True
    room.initial_rolls_remaining = {}
    room.winner_id = None
    room.solo_mode = False
    room.solo_player_id = None
    room.last_activity = time.time()


def delete_room(room_code: str):
    room = rooms.pop(room_code, None)
    if room:
        for p in room.players:
            player_room.pop(p.player_id, None)
            player_tokens.pop(p.player_id, None)
            player_last_activity.pop(p.player_id, None)
        logger.info(f"[ROOM] Místnost {room_code} smazána")


def remove_player_from_room(pid: str, room: GameSession):
    room.players = [p for p in room.players if p.player_id != pid]
    player_room.pop(pid, None)
    player_tokens.pop(pid, None)
    player_last_activity.pop(pid, None)
    connected_clients.pop(pid, None)
    room.last_activity = time.time()


# ╔══════════════════════════════════════════════╗
# ║  Broadcast / send                            ║
# ╚══════════════════════════════════════════════╝

async def broadcast_to_room(room: GameSession, message: dict):
    disconnected = []
    for p in room.players:
        ws = connected_clients.get(p.player_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(p.player_id)
    for pid in disconnected:
        connected_clients.pop(pid, None)


async def send_to_player(pid: str, message: dict):
    ws = connected_clients.get(pid)
    if ws:
        try:
            await ws.send_json(message)
        except Exception:
            logger.error(f"Chyba při odesílání zprávy hráči {pid}")


async def send_lobby_state(room: GameSession):
    can_start = (
        len(room.players) >= 2
        and all(p.ready for p in room.players)
        and room.status == GameStatus.WAITING
    ) or (
        room.solo_mode
        and len(room.players) >= 1
        and all(p.ready for p in room.players)
        and room.status == GameStatus.WAITING
    )

    used_colors = {p.color for p in room.players if p.color}
    available_colors = [c for c in room.COLORS if c not in used_colors]

    await broadcast_to_room(room, {
        "type": "lobby_state",
        "room_code": room.room_code,
        "status": room.status.value,
        "players": [p.to_dict() for p in room.players],
        "can_start": can_start,
        "available_colors": available_colors,
        "all_colors": room.COLORS,
        "solo_mode": room.solo_mode,
    })


async def send_game_state(room: GameSession):
    state = room.to_dict()
    state["type"] = "game_state"
    await broadcast_to_room(room, state)


async def send_game_state_to_player(pid: str, room: GameSession):
    state = room.to_dict()
    state["type"] = "game_state"
    await send_to_player(pid, state)


# ╔══════════════════════════════════════════════╗
# ║  Background tasky                            ║
# ╚══════════════════════════════════════════════╝

async def remove_dead_player(pid: str):
    room = get_player_room(pid)
    if not room:
        player_room.pop(pid, None)
        player_tokens.pop(pid, None)
        player_last_activity.pop(pid, None)
        connected_clients.pop(pid, None)
        return

    logger.info(f"[CLEANUP] Odstraňuji neaktivního hráče {pid} z místnosti {room.room_code}")
    was_current = room.current_player_id == pid
    remove_player_from_room(pid, room)

    if room.status == GameStatus.PLAYING:
        if len(room.players) < 2 and not room.solo_mode:
            reset_room(room)
            room.players = []
            await broadcast_to_room(room, {
                "type": "game_reset",
                "message": "Hra byla resetována — hráč se odpojil",
            })
        elif was_current:
            nxt = room.get_next_player()
            if nxt:
                room.current_player_id = nxt.player_id
                room.can_roll_dice = True
                room.last_dice_roll = 0
                if not has_pieces_on_board(room, nxt):
                    room.initial_rolls_remaining[nxt.player_id] = 3
            await broadcast_to_room(room, {
                "type": "player_disconnected",
                "message": "Hráč se odpojil, pokračuje další",
            })
            await send_game_state(room)
        else:
            await broadcast_to_room(room, {"type": "player_disconnected", "message": "Hráč se odpojil"})
            await send_game_state(room)
    elif room.status == GameStatus.WAITING:
        await send_lobby_state(room)


async def cleanup_task():
    while True:
        await asyncio.sleep(CLEANUP_CHECK_INTERVAL)
        try:
            now = time.time()

            # Mrtvé hráče (odpojení + timeout)
            dead = [
                pid for pid, ts in list(player_last_activity.items())
                if now - ts > PLAYER_DISCONNECT_TIMEOUT and pid not in connected_clients
            ]
            for pid in dead:
                await remove_dead_player(pid)

            # Prázdné místnosti
            empty = [
                code for code, room in list(rooms.items())
                if not room.players and now - room.last_activity > EMPTY_ROOM_TIMEOUT
            ]
            for code in empty:
                delete_room(code)

        except Exception as e:
            logger.error(f"[CLEANUP] Chyba: {e}")


async def ping_clients():
    while True:
        await asyncio.sleep(WS_PING_INTERVAL)
        disconnected = []
        for pid, ws in list(connected_clients.items()):
            try:
                await ws.send_json({"type": "ping"})
            except Exception:
                disconnected.append(pid)
        for pid in disconnected:
            logger.info(f"[PING] Hráč {pid} nereaguje")
            connected_clients.pop(pid, None)


# ╔══════════════════════════════════════════════╗
# ║  FastAPI app                                 ║
# ╚══════════════════════════════════════════════╝

@asynccontextmanager
async def lifespan(_app):
    t1 = asyncio.create_task(cleanup_task())
    t2 = asyncio.create_task(ping_clients())
    yield
    t1.cancel()
    t2.cancel()

app = FastAPI(title="Online Člověče, nezlob se", docs_url=None, redoc_url=None, lifespan=lifespan)

allowed_origins = os.getenv('CORS_ORIGINS', '*').split(',')
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["GET"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def get_index():
    return FileResponse("static/index.html")


@app.get("/health")
async def health_check():
    return {"status": "ok", "rooms": len(rooms)}


# ╔══════════════════════════════════════════════╗
# ║  WebSocket endpoint                          ║
# ╚══════════════════════════════════════════════╝

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_ip = get_client_ip(websocket)

    if ip_connections[client_ip] >= MAX_CONNECTIONS_PER_IP:
        await websocket.close(code=1008, reason="Příliš mnoho spojení")
        return

    await websocket.accept()
    ip_connections[client_ip] += 1
    player_id = None

    try:
        while True:
            data = await websocket.receive_text()

            if len(data) > MAX_WS_MESSAGE_SIZE:
                await websocket.send_json({"type": "error", "message": "Zpráva je příliš velká"})
                continue

            if check_rate_limit(client_ip):
                await websocket.send_json({"type": "error", "message": "Příliš mnoho požadavků"})
                continue

            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Neplatný formát zprávy"})
                continue

            msg_type = message.get("type", "unknown")

            if msg_type == "pong":
                if player_id:
                    player_last_activity[player_id] = time.time()
                continue

            if player_id:
                player_last_activity[player_id] = time.time()
                room = get_player_room(player_id)
                if room:
                    room.last_activity = time.time()

            if msg_type not in ("game_state", "lobby_state", "pong"):
                logger.info(f"[WS] {player_id or 'anon'}: {msg_type}")

            # ── create_room ───────────────────────────────
            if msg_type == "create_room":
                name = message.get("name", "").strip()
                name_error = validate_player_name(name)
                if name_error:
                    await websocket.send_json({"type": "error", "message": name_error})
                    continue

                if len(rooms) >= MAX_ROOMS:
                    await websocket.send_json({"type": "error", "message": "Maximální počet místností dosažen"})
                    continue

                solo_mode = message.get("solo_mode", False)
                code = generate_room_code()
                room = GameSession(room_code=code, solo_mode=solo_mode)
                rooms[code] = room

                player_id = str(uuid.uuid4())
                token = str(uuid.uuid4())
                selected_color = room.COLORS[0]

                player = Player(player_id=player_id, name=name, token=token, color=selected_color)
                room.players.append(player)

                connected_clients[player_id] = websocket
                player_tokens[player_id] = token
                player_room[player_id] = code
                player_last_activity[player_id] = time.time()

                if solo_mode:
                    room.solo_player_id = player_id

                logger.info(f"[ROOM] Vytvořena místnost {code} hráčem {name} (solo={solo_mode})")

                await websocket.send_json({
                    "type": "joined",
                    "player_id": player_id,
                    "token": token,
                    "room_code": code,
                    "solo_mode": solo_mode,
                })
                await send_lobby_state(room)

            # ── join_room ─────────────────────────────────
            elif msg_type == "join_room":
                name = message.get("name", "").strip()
                name_error = validate_player_name(name)
                if name_error:
                    await websocket.send_json({"type": "error", "message": name_error})
                    continue

                code = message.get("room_code", "").strip().upper()
                if not code or len(code) != ROOM_CODE_LENGTH:
                    await websocket.send_json({"type": "error", "message": "Neplatný kód místnosti"})
                    continue

                room = rooms.get(code)
                if not room:
                    await websocket.send_json({"type": "error", "message": "Místnost nenalezena"})
                    continue

                if room.status != GameStatus.WAITING:
                    await websocket.send_json({"type": "error", "message": "Hra v této místnosti už běží"})
                    continue

                if room.solo_mode:
                    await websocket.send_json({"type": "error", "message": "Místnost je v solo režimu"})
                    continue

                if len(room.players) >= 4:
                    await websocket.send_json({"type": "error", "message": "Místnost je plná"})
                    continue

                if any(p.name.lower() == name.lower() for p in room.players):
                    await websocket.send_json({"type": "error", "message": "Jméno je již obsazené"})
                    continue

                player_id = str(uuid.uuid4())
                token = str(uuid.uuid4())

                used_colors = {p.color for p in room.players if p.color}
                available = [c for c in room.COLORS if c not in used_colors]
                selected_color = available[0] if available else room.COLORS[0]

                player = Player(player_id=player_id, name=name, token=token, color=selected_color)
                room.players.append(player)

                connected_clients[player_id] = websocket
                player_tokens[player_id] = token
                player_room[player_id] = code
                player_last_activity[player_id] = time.time()

                logger.info(f"[JOIN] {name} se připojil do místnosti {code}")

                await websocket.send_json({
                    "type": "joined",
                    "player_id": player_id,
                    "token": token,
                    "room_code": code,
                    "solo_mode": False,
                })
                await send_lobby_state(room)

            # ── reconnect ─────────────────────────────────
            elif msg_type == "reconnect":
                token = message.get("token")
                if not token:
                    await websocket.send_json({"type": "error", "message": "Token je povinný"})
                    continue

                player_id = None
                for pid, t in player_tokens.items():
                    if t == token:
                        player_id = pid
                        break

                if not player_id:
                    await websocket.send_json({"type": "error", "message": "Neplatný token"})
                    continue

                room = get_player_room(player_id)
                if not room:
                    await websocket.send_json({"type": "error", "message": "Místnost již neexistuje"})
                    player_tokens.pop(player_id, None)
                    player_id = None
                    continue

                connected_clients[player_id] = websocket
                player_last_activity[player_id] = time.time()

                await websocket.send_json({
                    "type": "reconnected",
                    "player_id": player_id,
                    "room_code": room.room_code,
                })

                if room.status == GameStatus.WAITING:
                    await send_lobby_state(room)
                else:
                    await send_game_state_to_player(player_id, room)

            # ── Ostatní zprávy vyžadují room context ──────
            else:
                if not player_id:
                    await websocket.send_json({"type": "error", "message": "Nejste připojeni"})
                    continue

                room = get_player_room(player_id)
                if not room:
                    await websocket.send_json({"type": "error", "message": "Nejste v žádné místnosti"})
                    continue

                await handle_room_message(websocket, player_id, room, msg_type, message)

    except WebSocketDisconnect:
        logger.info(f"[WS_DISCONNECT] {player_id}")
    except Exception as e:
        logger.error(f"Chyba v WebSocket: {e}")
    finally:
        ip_connections[client_ip] = max(0, ip_connections[client_ip] - 1)
        if player_id:
            connected_clients.pop(player_id, None)
            room = get_player_room(player_id)
            if room:
                p = room.get_player(player_id)
                if p and room.status == GameStatus.PLAYING:
                    await broadcast_to_room(room, {
                        "type": "player_connection_lost",
                        "player_id": player_id,
                        "player_name": p.name,
                        "message": f"Hráč {p.name} ztratil spojení",
                    })


# ╔══════════════════════════════════════════════╗
# ║  Herní zprávy (v kontextu místnosti)         ║
# ╚══════════════════════════════════════════════╝

async def handle_room_message(
    websocket: WebSocket,
    player_id: str,
    room: GameSession,
    msg_type: str,
    message: dict,
):
    # ── select_color ──────────────────────────────
    if msg_type == "select_color":
        if room.status != GameStatus.WAITING:
            await websocket.send_json({"type": "error", "message": "Barvu lze změnit pouze před začátkem hry"})
            return

        player = room.get_player(player_id)
        if not player:
            return

        color = message.get("color")
        if not color or color not in room.COLORS:
            await websocket.send_json({"type": "error", "message": "Neplatná barva"})
            return

        used = {p.color for p in room.players if p.player_id != player_id and p.color}
        if color in used:
            await websocket.send_json({"type": "error", "message": "Tato barva je již obsazena"})
            return

        player.color = color
        await send_lobby_state(room)

    # ── set_ready ─────────────────────────────────
    elif msg_type == "set_ready":
        player = room.get_player(player_id)
        if not player:
            return
        player.ready = message.get("ready", False)
        await send_lobby_state(room)

    # ── start_game ────────────────────────────────
    elif msg_type == "start_game":
        player = room.get_player(player_id)
        if room.status != GameStatus.WAITING:
            await websocket.send_json({"type": "error", "message": "Hra již běží"})
            return

        if room.solo_mode:
            if len(room.players) < 1:
                await websocket.send_json({"type": "error", "message": "Potřebujete alespoň 1 hráče"})
                return
            available_colors = room.COLORS.copy()
            for p in room.players:
                if p.color and p.color in available_colors:
                    available_colors.remove(p.color)
            while len(room.players) < 4 and available_colors:
                vc = available_colors.pop(0)
                vp = Player(
                    player_id=str(uuid.uuid4()),
                    name=f"Bot {vc.capitalize()}",
                    token=str(uuid.uuid4()),
                    color=vc,
                )
                vp.ready = True
                room.players.append(vp)
        else:
            if len(room.players) < 2:
                await websocket.send_json({"type": "error", "message": "Potřebujete alespoň 2 hráče"})
                return

        if not all(p.ready for p in room.players):
            await websocket.send_json({"type": "error", "message": "Všichni hráči musí být ready"})
            return

        try:
            initialize_game(room)
            await broadcast_to_room(room, {
                "type": "game_started",
                "message": "Hra začala!",
                "solo_mode": room.solo_mode,
            })
            await send_game_state(room)
        except Exception as e:
            logger.error(f"[START_GAME] Chyba: {e}")
            await websocket.send_json({"type": "error", "message": "Chyba při spuštění hry"})

    # ── roll_dice ─────────────────────────────────
    elif msg_type == "roll_dice":
        if room.status != GameStatus.PLAYING:
            await websocket.send_json({"type": "error", "message": "Hra neběží"})
            return

        if room.solo_mode:
            if room.solo_player_id != player_id:
                await websocket.send_json({"type": "error", "message": "Není váš tah"})
                return
            current_player = room.get_current_player()
            if not current_player:
                return
            player = current_player
        else:
            if room.current_player_id != player_id:
                await websocket.send_json({"type": "error", "message": "Není váš tah"})
                return
            player = room.get_player(player_id)
            if not player:
                return

        if not room.can_roll_dice:
            await websocket.send_json({"type": "error", "message": "Nemůžete házet kostkou"})
            return

        dice_value = roll_dice()
        room.last_dice_roll = dice_value

        if dice_value == 6:
            player.stats_sixes += 1

        has_on_board = has_pieces_on_board(room, player)
        current_pid = player.player_id if not room.solo_mode else room.current_player_id
        can_move_ids = get_can_move_pawn_ids(room, player, dice_value)
        has_valid = len(can_move_ids) > 0

        if dice_value == 6:
            if not has_valid:
                end_turn(room, dice_value, after_move=False)
            else:
                room.can_roll_dice = False
        elif has_on_board:
            if not has_valid:
                end_turn(room, dice_value, after_move=False)
            else:
                room.can_roll_dice = False
        else:
            initial = room.initial_rolls_remaining.get(current_pid, 0)
            if initial > 0:
                room.initial_rolls_remaining[current_pid] = initial - 1
                room.can_roll_dice = True
            else:
                room.can_roll_dice = False
                end_turn(room, dice_value, after_move=False)

        await broadcast_to_room(room, {
            "type": "dice_rolled",
            "player_id": current_pid,
            "player_name": player.name,
            "dice_roll": dice_value,
        })
        await send_game_state(room)

    # ── move_piece ────────────────────────────────
    elif msg_type == "move_piece":
        if room.status != GameStatus.PLAYING:
            await websocket.send_json({"type": "error", "message": "Hra neběží"})
            return

        if room.solo_mode:
            if room.solo_player_id != player_id:
                await websocket.send_json({"type": "error", "message": "Není váš tah"})
                return
        else:
            if room.current_player_id != player_id:
                await websocket.send_json({"type": "error", "message": "Není váš tah"})
                return

        if room.can_roll_dice:
            await websocket.send_json({"type": "error", "message": "Nejdříve hoďte kostkou"})
            return

        piece_id = message.get("piece_id")
        if not piece_id:
            await websocket.send_json({"type": "error", "message": "piece_id je povinný"})
            return

        current_player = room.get_current_player()
        if not current_player:
            return

        player = current_player if room.solo_mode else room.get_player(player_id)
        if not player:
            return

        piece = next((p for p in player.pieces if p.piece_id == piece_id), None)
        if not piece:
            await websocket.send_json({"type": "error", "message": "Figurka nenalezena"})
            return

        if not can_move_piece(room, player, piece, room.last_dice_roll):
            await websocket.send_json({"type": "error", "message": "Nelze pohnout figurkou"})
            return

        try:
            result = move_piece(room, player, piece, room.last_dice_roll)
            await broadcast_to_room(room, {
                "type": "piece_moved",
                "player_id": player_id,
                "player_name": player.name,
                "result": result,
            })

            winner_id = check_game_end(room)
            if winner_id:
                winner = room.get_player(winner_id)
                await broadcast_to_room(room, {
                    "type": "game_end",
                    "winner_id": winner_id,
                    "winner_name": winner.name,
                })
            else:
                end_turn(room, room.last_dice_roll, after_move=True)

            await send_game_state(room)
        except Exception as e:
            logger.error(f"[MOVE] Chyba: {e}")
            await websocket.send_json({"type": "error", "message": "Nelze pohnout figurkou"})

    # ── skip_turn ─────────────────────────────────
    elif msg_type == "skip_turn":
        if room.status != GameStatus.PLAYING:
            return

        if room.solo_mode:
            if room.solo_player_id != player_id:
                return
        else:
            if room.current_player_id != player_id:
                return

        if room.can_roll_dice:
            await websocket.send_json({"type": "error", "message": "Nejdříve hoďte kostkou"})
            return

        cp = room.get_current_player()
        end_turn(room, room.last_dice_roll)
        await broadcast_to_room(room, {
            "type": "turn_skipped",
            "player_id": cp.player_id if cp else player_id,
            "player_name": cp.name if cp else "unknown",
        })
        await send_game_state(room)

    # ── leave_lobby ───────────────────────────────
    elif msg_type == "leave_lobby":
        remove_player_from_room(player_id, room)

        if room.status == GameStatus.WAITING:
            if room.players:
                await send_lobby_state(room)
            else:
                delete_room(room.room_code)
        elif len(room.players) < 2 and not room.solo_mode:
            reset_room(room)
            room.players = []
            await broadcast_to_room(room, {
                "type": "game_reset",
                "message": "Hra byla resetována — příliš málo hráčů",
            })
            delete_room(room.room_code)

    # ── end_solo_game ─────────────────────────────
    elif msg_type == "end_solo_game":
        if not room.solo_mode or room.solo_player_id != player_id:
            await websocket.send_json({"type": "error", "message": "Tuto akci lze provést pouze v solo režimu"})
            return

        code = room.room_code
        await websocket.send_json({"type": "solo_game_ended", "message": "Hra byla ukončena"})
        delete_room(code)

    # ── new_game ──────────────────────────────────
    elif msg_type == "new_game":
        if room.status != GameStatus.FINISHED:
            await websocket.send_json({"type": "error", "message": "Hra ještě neskončila"})
            return

        was_solo = room.solo_mode
        reset_room(room)

        if was_solo:
            room.players = [p for p in room.players if p.player_id in player_tokens]

        for p in room.players:
            p.ready = False
            p.stats_turns = 0
            p.stats_deployments = 0
            p.stats_moves = 0
            p.stats_captures = 0
            p.stats_sixes = 0
            for piece in p.pieces:
                piece.status = PieceStatus.HOME
                piece.position = piece.home_position

        await broadcast_to_room(room, {
            "type": "return_to_lobby",
            "message": "Nová hra — vracíme se do lobby",
        })
        await send_lobby_state(room)

    else:
        await websocket.send_json({"type": "error", "message": f"Neznámý typ zprávy: {msg_type}"})
