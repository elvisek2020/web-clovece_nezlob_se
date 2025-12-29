import random
import time
import logging
from typing import Optional, Dict, Any, List
from app.models import GameSession, Player, Piece, PieceStatus, GameStatus

logger = logging.getLogger(__name__)

# Inicializace random generátoru s časem pro lepší random
_random_seed = int(time.time() * 1000) % 1000000
_random = random.Random(_random_seed)

# Konstanty podle specifikace
TRACK_LEN = 52  # track-0..51
LANE_LEN = 4  # lane-<color>-0..3

# Startovní indexy (pevné)
START_INDEX = {
    "red": 0,
    "blue": 13,
    "yellow": 26,
    "green": 39
}

# Entry indexy (vstup do cílové dráhy) - políčko těsně před startem
ENTRY_INDEX = {
    "red": (START_INDEX["red"] + TRACK_LEN - 1) % TRACK_LEN,      # 51
    "blue": (START_INDEX["blue"] + TRACK_LEN - 1) % TRACK_LEN,    # 12
    "yellow": (START_INDEX["yellow"] + TRACK_LEN - 1) % TRACK_LEN,  # 25
    "green": (START_INDEX["green"] + TRACK_LEN - 1) % TRACK_LEN    # 38
}


def initialize_game(session: GameSession) -> None:
    """Inicializuje hru"""
    if not session.solo_mode:
        if len(session.players) < 2:
            raise ValueError("Potřebujete alespoň 2 hráče")
    else:
        if len(session.players) < 1:
            raise ValueError("Potřebujete alespoň 1 hráče")
    
    if len(session.players) > 4:
        raise ValueError("Maximálně 4 hráči")
    
    # Přiřadí barvy a startovní pozice hráčům
    available_colors = session.COLORS.copy()
    
    for i, player in enumerate(session.players):
        # Pokud hráč nemá barvu, přiřadí se automaticky
        if not player.color:
            if available_colors:
                player.color = available_colors.pop(0)
        
        # Nastav startovní pozici podle barvy
        if player.color in START_INDEX:
            player.start_position = START_INDEX[player.color]
        
        # Resetuje figurky a statistiky
        for piece in player.pieces:
            piece.status = PieceStatus.HOME
            piece.position = piece.home_position  # home slot (0-3)
        player.stats_turns = 0
        player.stats_deployments = 0
        player.stats_moves = 0
        player.stats_captures = 0
        player.stats_sixes = 0
    
    session.status = GameStatus.PLAYING
    session.current_player_id = session.players[0].player_id
    session.can_roll_dice = True
    session.last_dice_roll = 0
    # Inicializace počítadla pro první nasazení (3 pokusy pro každého hráče)
    session.initial_rolls_remaining = {player.player_id: 3 for player in session.players}


def roll_dice() -> int:
    """Hodí kostkou (1-6) - používá lepší random generátor"""
    _random.seed(int(time.time() * 1000) % 1000000)
    return _random.randint(1, 6)


def get_piece_at_position(session: GameSession, color: str, state: str, position: int) -> Optional[Piece]:
    """Najde figuru na dané pozici (track nebo lane)"""
    for player in session.players:
        if player.color == color:
            continue  # Vlastní figurky kontrolujeme jinde
        for piece in player.pieces:
            if piece.status.value == state and piece.position == position:
                return piece
    return None


def get_own_piece_at_position(player: Player, state: str, position: int) -> Optional[Piece]:
    """Najde vlastní figuru na dané pozici"""
    for piece in player.pieces:
        if piece.status.value == state and piece.position == position:
            return piece
    return None


def can_move_piece(session: GameSession, player: Player, piece: Piece, dice_roll: int) -> bool:
    """Zkontroluje, zda může hráč pohnout figurkou"""
    if piece.status == PieceStatus.FINISHED:
        return False
    
    color = player.color
    if not color:
        return False
    
    # 1) Start z domku (home → track)
    if piece.status == PieceStatus.HOME:
        if dice_roll != 6:
            return False
        
        start_pos = START_INDEX[color]
        
        # Zkontroluj, zda na startu není vlastní figurka
        if get_own_piece_at_position(player, "track", start_pos):
            return False
        
        # Start může být obsazen soupeřem (vyhodí se)
        return True
    
    # 2) Pohyb po tracku (track → track / track → home_lane)
    if piece.status == PieceStatus.TRACK:
        cur = piece.position
        entry = ENTRY_INDEX[color]
        steps_to_entry = (entry - cur + TRACK_LEN) % TRACK_LEN
        
        if dice_roll > steps_to_entry:
            # Vstupuje do lane
            lane_step = dice_roll - steps_to_entry - 1
            
            if lane_step >= LANE_LEN:
                return False  # Přestřelení cíle
            
            # Zkontroluj obsazení lane políčka
            if get_own_piece_at_position(player, "home_lane", lane_step):
                return False
            
            # Lane je jen vlastní, soupeř tam nemůže být
            return True
        else:
            # Normální posun po tracku
            new_pos = (cur + dice_roll) % TRACK_LEN
            
            # Zkontroluj, zda na nové pozici není vlastní figurka
            if get_own_piece_at_position(player, "track", new_pos):
                return False
            
            # Soupeř se může vyhodit (to je OK)
            return True
    
    # 3) Pohyb v cílové dráze (home_lane → home_lane / finished)
    if piece.status == PieceStatus.HOME_LANE:
        cur_lane_pos = piece.position
        new_lane_pos = cur_lane_pos + dice_roll
        
        if new_lane_pos > LANE_LEN - 1:
            return False  # Přestřelení - musí se trefit přesně
        
        if new_lane_pos == LANE_LEN - 1:
            # Dojde do cíle (finished)
            return True
        
        # Zkontroluj obsazení cílového lane políčka
        if get_own_piece_at_position(player, "home_lane", new_lane_pos):
            return False
        
        return True
    
    return False


def move_piece(session: GameSession, player: Player, piece: Piece, dice_roll: int) -> Dict[str, Any]:
    """Pohne figurkou podle specifikace"""
    if not can_move_piece(session, player, piece, dice_roll):
        raise ValueError("Nelze pohnout figurkou")
    
    color = player.color
    if not color:
        raise ValueError("Hráč nemá barvu")
    
    # Debug log (pouze pokud je LOG_LEVEL=DEBUG nebo INFO)
    logger.debug(f"[MOVE] pawn_id={piece.piece_id}, color={color}, state={piece.status.value}, position={piece.position}, dice={dice_roll}")
    
    # 1) Start z domku (home → track)
    if piece.status == PieceStatus.HOME:
        start_pos = START_INDEX[color]
        
        # Zkontroluj vyhození na startu
        captured_piece = None
        for other_player in session.players:
            if other_player.player_id == player.player_id:
                continue
            for other_piece in other_player.pieces:
                if other_piece.status == PieceStatus.TRACK and other_piece.position == start_pos:
                    captured_piece = other_piece
                    break
            if captured_piece:
                break
        
        if captured_piece:
            # Vyhození soupeře
            captured_piece.status = PieceStatus.HOME
            captured_piece.position = captured_piece.home_position  # Vrátí se na svůj home slot
            player.stats_captures += 1
            logger.info(f"[CAPTURE] Captured piece {captured_piece.piece_id} at start position")
        
        piece.status = PieceStatus.TRACK
        piece.position = start_pos
        player.stats_deployments += 1
        
        logger.info(f"[MOVE] Exited home, new position: track-{start_pos}")
        
        if captured_piece:
            return {
                "action": "piece_exited_home_and_captured",
                "piece_id": piece.piece_id,
                "new_position": piece.position,
                "captured_piece_id": captured_piece.piece_id,
                "captured_player_id": captured_piece.player_id
            }
        
        return {
            "action": "piece_exited_home",
            "piece_id": piece.piece_id,
            "new_position": piece.position
        }
    
    # 2) Pohyb po tracku (track → track / track → home_lane)
    if piece.status == PieceStatus.TRACK:
        cur = piece.position
        entry = ENTRY_INDEX[color]
        steps_to_entry = (entry - cur + TRACK_LEN) % TRACK_LEN
        
        logger.debug(f"[MOVE] cur={cur}, entry={entry}, stepsToEntry={steps_to_entry}")
        
        if dice_roll > steps_to_entry:
            # Vstupuje do lane
            lane_step = dice_roll - steps_to_entry - 1
            
            logger.info(f"[MOVE] Entering lane, laneStep={lane_step}")
            
            if lane_step >= LANE_LEN:
                raise ValueError("Přestřelení cíle")
            
            # Zkontroluj obsazení lane políčka (vlastní figurka)
            if get_own_piece_at_position(player, "home_lane", lane_step):
                raise ValueError("Lane políčko je obsazené vlastní figurkou")
            
            # Přesun do lane
            old_position = piece.position
            piece.status = PieceStatus.HOME_LANE
            piece.position = lane_step
            
            # Pokud je na posledním lane políčku, je finished
            if lane_step == LANE_LEN - 1:
                piece.status = PieceStatus.FINISHED
                piece.position = None
            
            logger.info(f"[MOVE] Entered lane, new position: lane-{color}-{lane_step}")
            
            return {
                "action": "piece_entered_lane",
                "piece_id": piece.piece_id,
                "old_position": old_position,
                "new_position": piece.position,
                "lane_position": lane_step
            }
        else:
            # Normální posun po tracku
            new_pos = (cur + dice_roll) % TRACK_LEN
            
            # Zkontroluj obsazení (vlastní figurka)
            if get_own_piece_at_position(player, "track", new_pos):
                raise ValueError("Track políčko je obsazené vlastní figurkou")
            
            old_position = piece.position
            piece.position = new_pos
            
            # Zkontroluj vyhození soupeře
            captured_piece = None
            for other_player in session.players:
                if other_player.player_id == player.player_id:
                    continue
                for other_piece in other_player.pieces:
                    if other_piece.status == PieceStatus.TRACK and other_piece.position == new_pos:
                        captured_piece = other_piece
                        break
                if captured_piece:
                    break
            
            if captured_piece:
                # Vyhození soupeře
                captured_piece.status = PieceStatus.HOME
                captured_piece.position = captured_piece.home_position  # Vrátí se na svůj home slot
                player.stats_captures += 1
                logger.info(f"[CAPTURE] Captured piece {captured_piece.piece_id} at track-{new_pos}")
            
            player.stats_moves += 1
            logger.info(f"[MOVE] Moved on track, new position: track-{new_pos}")
            
            if captured_piece:
                return {
                    "action": "piece_moved_and_captured",
                    "piece_id": piece.piece_id,
                    "old_position": old_position,
                    "new_position": piece.position,
                    "captured_piece_id": captured_piece.piece_id,
                    "captured_player_id": captured_piece.player_id
                }
            
            return {
                "action": "piece_moved",
                "piece_id": piece.piece_id,
                "old_position": old_position,
                "new_position": piece.position
            }
    
    # 3) Pohyb v cílové dráze (home_lane → home_lane / finished)
    if piece.status == PieceStatus.HOME_LANE:
        cur_lane_pos = piece.position
        new_lane_pos = cur_lane_pos + dice_roll
        
        if new_lane_pos > LANE_LEN - 1:
            raise ValueError("Přestřelení cíle - musí se trefit přesně")
        
        # Zkontroluj obsazení (vlastní figurka)
        if new_lane_pos < LANE_LEN - 1:
            if get_own_piece_at_position(player, "home_lane", new_lane_pos):
                raise ValueError("Lane políčko je obsazené vlastní figurkou")
        
        old_position = piece.position
        
        if new_lane_pos == LANE_LEN - 1:
            # Dojde do cíle (finished)
            piece.status = PieceStatus.FINISHED
            piece.position = None
            logger.info(f"[MOVE] Finished, position: lane-{color}-3")
        else:
            piece.position = new_lane_pos
            logger.info(f"[MOVE] Moved in lane, new position: lane-{color}-{new_lane_pos}")
        
        player.stats_moves += 1
        
        return {
            "action": "piece_moved_in_lane" if new_lane_pos < LANE_LEN - 1 else "piece_finished",
            "piece_id": piece.piece_id,
            "old_position": old_position,
            "new_position": piece.position,
            "lane_position": new_lane_pos if new_lane_pos < LANE_LEN - 1 else LANE_LEN - 1
        }
    
    raise ValueError(f"Neznámý stav figurky: {piece.status}")


def has_pieces_on_board(session: GameSession, player: Player) -> bool:
    """Zkontroluje, zda má hráč nějaké figurky na hrací ploše (track nebo home_lane)"""
    return any(
        piece.status == PieceStatus.TRACK or piece.status == PieceStatus.HOME_LANE
        for piece in player.pieces
    )


def get_can_move_pawn_ids(session: GameSession, player: Player, dice_roll: int) -> List[str]:
    """Vrátí seznam ID figurek, kterými může hráč táhnout"""
    can_move = []
    for piece in player.pieces:
        if can_move_piece(session, player, piece, dice_roll):
            can_move.append(piece.piece_id)
    return can_move


def end_turn(session: GameSession, dice_roll: int, after_move: bool = False) -> None:
    """Ukončí tah hráče"""
    current_player = session.get_current_player()
    if not current_player:
        return
    
    # Aktualizuj statistiky - tah
    if not after_move or dice_roll != 6:
        current_player.stats_turns += 1
    
    # Pokud hráč hodil 6 a pohnul figurkou, může házet znovu
    if dice_roll == 6 and after_move:
        session.can_roll_dice = True
        return
    
    # Pokud hráč hodil 6, ale neměl žádný legální tah, extra hod propadne (MVP)
    if dice_roll == 6 and not after_move:
        # Propadne - přejde na dalšího hráče
        session.last_dice_roll = 0
        next_player = session.get_next_player()
        if next_player:
            session.current_player_id = next_player.player_id
            # Pokud nový hráč nemá figurky na ploše, reset počítadla
            if not has_pieces_on_board(session, next_player):
                session.initial_rolls_remaining[next_player.player_id] = 3
        session.can_roll_dice = True
        return
    
    # Pokud hráč nehodil 6, přejde na dalšího hráče
    if dice_roll != 6 or not after_move:
        # Vynuluj kostku před předáním tahu dalšímu hráči
        session.last_dice_roll = 0
        # Reset počítadla pro nového hráče (pokud nemá figurky na ploše)
        next_player = session.get_next_player()
        if next_player:
            session.current_player_id = next_player.player_id
            # Pokud nový hráč nemá figurky na ploše, reset počítadla
            if not has_pieces_on_board(session, next_player):
                session.initial_rolls_remaining[next_player.player_id] = 3
        session.can_roll_dice = True


def check_game_end(session: GameSession) -> Optional[str]:
    """Zkontroluje, zda hra skončila (někdo vyhrál)"""
    for player in session.players:
        finished_pieces = [p for p in player.pieces if p.status == PieceStatus.FINISHED]
        if len(finished_pieces) == 4:
            # Hráč má všechny figurky v cíli - vyhrál!
            session.status = GameStatus.FINISHED
            session.winner_id = player.player_id
            return player.player_id
    
    return None
