from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
import uuid


class GameStatus(Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    FINISHED = "finished"


class PieceStatus(Enum):
    HOME = "home"  # V domečku
    TRACK = "track"  # Na hlavní dráze
    HOME_LANE = "home_lane"  # V cílové dráze (lane)
    FINISHED = "finished"  # V cíli


@dataclass
class Piece:
    """Figurka hráče"""
    piece_id: str
    player_id: str
    status: PieceStatus = PieceStatus.HOME
    position: Optional[int] = 0  # home:0..3, track:0..51, home_lane:0..3, finished:None
    home_position: int = 0  # Pořadí v domečku (0-3) - stabilní home slot
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "piece_id": self.piece_id,
            "player_id": self.player_id,
            "status": self.status.value,
            "position": self.position,
            "home_position": self.home_position
        }


@dataclass
class Player:
    """Hráč"""
    player_id: str
    name: str
    token: str
    color: Optional[str] = None  # Barva hráče (red, blue, green, yellow) - nastaví se při inicializaci hry
    pieces: List[Piece] = field(default_factory=list)
    ready: bool = False
    start_position: int = 0  # Startovní pozice na hrací ploše
    # Statistiky
    stats_turns: int = 0  # Počet tahů
    stats_deployments: int = 0  # Počet nasazení figurek
    stats_moves: int = 0  # Počet pohybů figurek
    stats_captures: int = 0  # Počet zajatých figurek
    stats_sixes: int = 0  # Počet hozených šestek
    
    def __post_init__(self):
        if not self.pieces:
            # Vytvoří 4 figurky pro hráče
            for i in range(4):
                self.pieces.append(Piece(
                    piece_id=str(uuid.uuid4()),
                    player_id=self.player_id,
                    home_position=i
                ))
    
    def to_dict(self, hide_pieces: bool = False) -> Dict[str, Any]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "color": self.color,
            "ready": self.ready,
            "start_position": self.start_position,
            "pieces": [] if hide_pieces else [p.to_dict() for p in self.pieces],
            "pieces_count": len([p for p in self.pieces if p.status == PieceStatus.FINISHED]),
            "stats": {
                "turns": self.stats_turns,
                "deployments": self.stats_deployments,
                "moves": self.stats_moves,
                "captures": self.stats_captures,
                "sixes": self.stats_sixes
            }
        }


@dataclass
class GameSession:
    """Herní session"""
    status: GameStatus = GameStatus.WAITING
    players: List[Player] = field(default_factory=list)
    current_player_id: Optional[str] = None
    last_dice_roll: int = 0
    can_roll_dice: bool = True
    winner_id: Optional[str] = None
    initial_rolls_remaining: Dict[str, int] = field(default_factory=dict)  # Počítadlo pro první nasazení (3 pokusy)
    solo_mode: bool = False  # Solo režim - jeden hráč hraje za všechny
    solo_player_id: Optional[str] = None  # ID hráče v solo režimu
    
    # Barvy pro hráče (standardní Ludo barvy)
    COLORS = ["red", "blue", "green", "yellow"]
    START_POSITIONS = [0, 13, 26, 39]  # Startovní pozice pro každou barvu
    
    def get_player(self, player_id: str) -> Optional[Player]:
        """Získá hráče podle ID"""
        for player in self.players:
            if player.player_id == player_id:
                return player
        return None
    
    def get_current_player(self) -> Optional[Player]:
        """Získá aktuálního hráče"""
        if not self.current_player_id:
            return None
        return self.get_player(self.current_player_id)
    
    def get_next_player(self) -> Optional[Player]:
        """Získá dalšího hráče"""
        if not self.players:
            return None
        
        if not self.current_player_id:
            return self.players[0]
        
        current_index = next(
            (i for i, p in enumerate(self.players) if p.player_id == self.current_player_id),
            -1
        )
        
        if current_index == -1:
            return self.players[0]
        
        next_index = (current_index + 1) % len(self.players)
        return self.players[next_index]
    
    def to_dict(self, for_player_id: Optional[str] = None) -> Dict[str, Any]:
        """Serializuje herní stav"""
        hide_pieces = for_player_id is not None
        
        return {
            "status": self.status.value,
            "current_player_id": self.current_player_id,
            "last_dice_roll": self.last_dice_roll,
            "can_roll_dice": self.can_roll_dice,
            "winner_id": self.winner_id,
            "solo_mode": self.solo_mode,
            "solo_player_id": self.solo_player_id,
            "players": [
                p.to_dict(hide_pieces=(hide_pieces and p.player_id != for_player_id))
                for p in self.players
            ]
        }

