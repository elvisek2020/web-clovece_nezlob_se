// Globální proměnné
let ws = null;
let playerId = null;
let token = null;
let playerName = null;
let currentGameState = null;
let pendingJoinName = null; // Jméno čekající na připojení WebSocket
let pendingSoloMode = false; // Solo režim čekající na připojení WebSocket

// Barvy pro hráče
const COLORS = {
    red: "#e74c3c",
    blue: "#3498db",
    green: "#2ecc71",
    yellow: "#f1c40f"
};

// Board konfigurace - anchor body se načtou ze SVG
let boardAnchors = {}; // Mapování anchor ID na {x, y}
let boardSvgElement = null; // Root SVG element
let pawnsLayer = null; // SVG group pro figurky

// Offsety pro stacking figurek na stejném políčku
const STACK_OFFSETS = [
    { dx: 0, dy: 0 },
    { dx: 10, dy: 0 },
    { dx: -10, dy: 0 },
    { dx: 0, dy: 10 },
    { dx: 0, dy: -10 }
];

// Načtení SVG boardu a extrakce anchor body
async function loadBoardSvg() {
    try {
        const response = await fetch('/static/images/board_modern_52.svg');
        if (!response.ok) {
            throw new Error(`Failed to load SVG: ${response.status}`);
        }
        const svgText = await response.text();
        return svgText;
    } catch (error) {
        console.error('Error loading board SVG:', error);
        throw error;
    }
}

// Extrakce anchor souřadnic ze SVG
function readAnchors(svgEl) {
    const anchors = {};
    const selector = '[id^="track-"], [id^="home-"], [id^="lane-"]';
    
    svgEl.querySelectorAll(selector).forEach(el => {
        const id = el.id;
        const cx = Number(el.getAttribute("cx"));
        const cy = Number(el.getAttribute("cy"));
        anchors[id] = { x: cx, y: cy };
    });
    
    return anchors;
}

// Tvrdá validace anchor body - fail fast při startu
function validateAnchors(anchors) {
    const errors = [];
    
    // Validace track-0 až track-51 (celkem 52)
    for (let i = 0; i < 52; i++) {
        const trackId = `track-${i}`;
        if (!anchors[trackId]) {
            errors.push(`Chybí anchor: ${trackId}`);
            console.error(`Missing anchor: ${trackId}`);
        }
    }
    
    // Validace pro každou barvu: red, blue, yellow, green
    const colors = ['red', 'blue', 'yellow', 'green'];
    colors.forEach(color => {
        // Validace home-<color>-0..3
        for (let i = 0; i < 4; i++) {
            const homeId = `home-${color}-${i}`;
            if (!anchors[homeId]) {
                errors.push(`Chybí anchor: ${homeId}`);
                console.error(`Missing anchor: ${homeId}`);
            }
        }
        
        // Validace lane-<color>-0..3
        for (let i = 0; i < 4; i++) {
            const laneId = `lane-${color}-${i}`;
            if (!anchors[laneId]) {
                errors.push(`Chybí anchor: ${laneId}`);
                console.error(`Missing anchor: ${laneId}`);
            }
        }
    });
    
    // Pokud jsou chyby, zobraz alert a zaloguj detail
    if (errors.length > 0) {
        const errorMessage = `Chyba při načítání hrací plochy!\n\nChybí ${errors.length} anchor body:\n${errors.slice(0, 10).join('\n')}${errors.length > 10 ? `\n... a dalších ${errors.length - 10} chyb` : ''}\n\nZkontrolujte prosím SVG soubor board_modern_52.svg.`;
        
        console.error('SVG Anchor Validation Failed:', {
            totalErrors: errors.length,
            errors: errors,
            loadedAnchors: Object.keys(anchors).length,
            anchorIds: Object.keys(anchors).sort()
        });
        
        alert(errorMessage);
        throw new Error(`SVG validation failed: ${errors.length} missing anchors`);
    }
    
    return true;
}

// Mapování herního stavu figurky na anchor ID
// Přesné mapování podle požadavků:
// - track-${position} pro state="track"
// - home-${color}-${position} pro state="home"
// - lane-${color}-${position} pro state="home_lane"
// - lane-${color}-3 pro state="finished" (MVP)
function pawnToAnchorId(pawn) {
    const color = pawn.color || 'red';
    
    // Normalizace statusu (podporujeme různé varianty)
    const status = (pawn.status || '').toLowerCase();
    
    if (status === "track") {
        const pos = pawn.position;
        // Je na hlavní dráze (track)
        const trackPos = pos % 52; // Zajistíme, že je v rozsahu 0-51
        return `track-${trackPos}`;
    }
    
    if (status === "home") {
        // Použij home_position z piece objektu (0-3)
        const homePos = pawn.home_position !== undefined ? pawn.home_position : 0;
        return `home-${color}-${homePos}`;
    }
    
    if (status === "home_lane") {
        // Pro home_lane je position přímo 0-3
        let lanePos = 0;
        if (pawn.position !== undefined && pawn.position !== null) {
            lanePos = Math.min(Math.max(pawn.position, 0), 3);
        }
        return `lane-${color}-${lanePos}`;
    }
    
    if (status === "finished") {
        // MVP: poslední lane políčko (index 3)
        return `lane-${color}-3`;
    }
    
    console.warn('Unknown pawn state:', pawn.status, pawn);
    return `home-${color}-0`; // Fallback
}

// Inicializace při načtení stránky
document.addEventListener("DOMContentLoaded", () => {
    // Kliknutí na hlavní nadpis - vždy obnoví stránku
    const mainTitle = document.getElementById('main-title');
    if (mainTitle) {
        mainTitle.addEventListener('click', () => {
            window.location.reload();
        });
    }
    // Načtení tokenu ze sessionStorage (pro reconnect)
    token = sessionStorage.getItem("token");
    playerId = sessionStorage.getItem("player_id");
    playerName = sessionStorage.getItem("player_name");
    
    // Předvyplnění jména hráče a solo režimu, pokud existuje v sessionStorage
    const savedPlayerName = sessionStorage.getItem("player_name");
    const savedSoloMode = sessionStorage.getItem("solo_mode") === "true";
    const nameInput = document.getElementById("player-name");
    const soloBtn = document.getElementById("solo-mode-btn");
    
    if (savedPlayerName && nameInput) {
        nameInput.value = savedPlayerName;
    }
    if (savedSoloMode && soloBtn) {
        soloBtn.classList.add("active");
    }
    
    // Event listener pro solo režim tlačítko
    if (soloBtn) {
        soloBtn.addEventListener("click", function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            // Získej jméno hráče
            const nameInput = document.getElementById("player-name");
            const name = nameInput ? nameInput.value.trim() : "";
            
            // Pokud není zadané jméno, použij výchozí
            const playerName = name || "Solo Hráč";
            
            // Nastav solo režim
            sessionStorage.setItem("solo_mode", "true");
            sessionStorage.setItem("player_name", playerName);
            
            // Pokud máme jméno v inputu, ulož ho
            if (nameInput && name) {
                nameInput.value = playerName;
            }
            
            // Uložení jména a solo režimu do dočasné proměnné pro pozdější použití
            pendingJoinName = playerName;
            pendingSoloMode = true;
            
            // Zavření existujícího WebSocket, pokud není otevřený
            if (ws && ws.readyState !== WebSocket.OPEN) {
                ws.onclose = null;
                ws.close();
                ws = null;
            }
            
            // Pokud nemáme token, vytvoříme nový WebSocket
            if (!token && ws) {
                ws.onclose = null;
                ws.close();
                ws = null;
            }
            
            // Vytvoření nového WebSocket a připojení
            connectWebSocket();
        });
    } else {
        console.error("Solo režim tlačítko nenalezeno!");
    }
    
    // Přidání event listeneru pro tlačítko Připojit se
    const joinBtn = document.getElementById("join-btn");
    if (joinBtn) {
        joinBtn.addEventListener("click", handleJoin);
    }
    
    // Enter klávesa pro submit
    if (nameInput) {
        nameInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                handleJoin();
            }
        });
    }
    
    // Ready button
    const readyBtn = document.getElementById("ready-btn");
    if (readyBtn) {
        readyBtn.addEventListener("click", handleSetReady);
    }
    
    // Start game button
    const startGameBtn = document.getElementById("start-game-btn");
    if (startGameBtn) {
        startGameBtn.addEventListener("click", () => {
            sendMessage({ type: "start_game" });
        });
    }
    
    // Leave button
    const leaveBtn = document.getElementById("leave-btn");
    if (leaveBtn) {
        leaveBtn.addEventListener("click", handleLeaveLobby);
    }
    
    // Game buttons
    const rollDiceBtn = document.getElementById("roll-dice-btn");
    if (rollDiceBtn) {
        rollDiceBtn.addEventListener("click", handleRollDice);
    }
    
    // End game button (solo mode)
    const endGameBtn = document.getElementById("end-game-btn");
    if (endGameBtn) {
        endGameBtn.addEventListener("click", handleEndGame);
    }
    
    
    // Pokud máme token, zkusíme reconnect
    if (token && playerId) {
        connectWebSocket();
    }
    
    // Inicializuj board při načtení stránky
    initializeBoard();
    
});

function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        // Pokud čeká jméno na připojení, pošli join zprávu
        if (pendingJoinName) {
            sendMessage({ type: "join", name: pendingJoinName, solo_mode: pendingSoloMode });
            pendingJoinName = null;
            pendingSoloMode = false;
        } else if (token && !pendingJoinName) {
            // Pokud máme token ale žádné jméno, zkus reconnect
            // (pouze pokud uživatel nechce vytvořit nové připojení)
            sendMessage({ type: "reconnect", token: token });
        }
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleMessage(message);
    };

    ws.onerror = (error) => {
        console.error("WebSocket chyba:", error);
        showError("Chyba připojení k serveru");
    };

    ws.onclose = () => {
        // Zkus reconnect po 3 sekundách
        setTimeout(() => {
            if (token) {
                connectWebSocket();
            }
        }, 3000);
    };
}

function sendMessage(message) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(message));
    } else {
        console.error("WebSocket není připojen");
    }
}

function handleJoin() {
    const nameInput = document.getElementById("player-name");
    if (!nameInput) return;
    
    const name = nameInput.value.trim();
    
    // Validace jména
    if (!name) {
        showError("Zadejte jméno");
        return;
    }
    
    // Získej solo režim z tlačítka
    const soloBtn = document.getElementById("solo-mode-btn");
    const soloMode = soloBtn ? soloBtn.classList.contains("active") : false;
    
    // Uložení jména a solo režimu do sessionStorage pro příští hraní
    sessionStorage.setItem("player_name", name);
    sessionStorage.setItem("solo_mode", soloMode ? "true" : "false");
    
    // Pokud nemáme token, vytvoříme nový WebSocket
    if (!token && ws) {
        ws.onclose = null; // Zrušíme reconnect
        ws.close();
        ws = null;
    }
    
    // Uložení jména a solo režimu do dočasné proměnné pro pozdější použití
    pendingJoinName = name;
    pendingSoloMode = soloMode;
    
    // Zavření existujícího WebSocket, pokud není otevřený
    if (ws && ws.readyState !== WebSocket.OPEN) {
        ws.onclose = null;
        ws.close();
        ws = null;
    }
    
    // Vytvoření nového WebSocket
    connectWebSocket();
}

function handleSetReady() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        showError("Není připojení k serveru");
        return;
    }
    
    isReady = !isReady;
    
    // Odeslání zprávy serveru
    sendMessage({ type: "set_ready", ready: isReady });
    
    // Aktualizace textu tlačítka
    const readyBtn = document.getElementById("ready-btn");
    if (readyBtn) {
        readyBtn.textContent = isReady ? "Zrušit" : "Připraven";
    }
}


function handleLeaveLobby() {
    // Odeslání zprávy serveru (pokud je WebSocket otevřený)
    if (ws && ws.readyState === WebSocket.OPEN) {
        sendMessage({ type: "leave_lobby" });
    }
    
    // Smazání tokenu a player_id
    sessionStorage.removeItem("token");
    sessionStorage.removeItem("player_id");
    sessionStorage.removeItem("player_name");
    sessionStorage.removeItem("solo_mode");
    playerId = null;
    token = null;
    playerName = null;
    isReady = false;
    
    // Zavření WebSocket
    if (ws) {
        ws.onclose = null; // Zrušíme reconnect
        ws.close();
        ws = null;
    }
    
    // Přepnutí na login screen
    showScreen("login-screen");
}

function handleEndGame() {
    // Odeslání zprávy serveru pro ukončení hry v solo režimu (bez potvrzování)
    if (ws && ws.readyState === WebSocket.OPEN) {
        sendMessage({ type: "end_solo_game" });
    }
    
    // Smazání tokenu a player_id
    sessionStorage.removeItem("token");
    sessionStorage.removeItem("player_id");
    sessionStorage.removeItem("player_name");
    sessionStorage.removeItem("solo_mode");
    playerId = null;
    token = null;
    playerName = null;
    isReady = false;
    
    // Zavření WebSocket
    if (ws) {
        ws.onclose = null; // Zrušíme reconnect
        ws.close();
        ws = null;
    }
    
    // Přepnutí na login screen
    showScreen("login-screen");
}

function handleRollDice() {
    sendMessage({ type: "roll_dice" });
}


function handleMessage(message) {
    switch (message.type) {
        case "joined":
            playerId = message.player_id;
            token = message.token;
            playerName = document.getElementById("player-name") ? document.getElementById("player-name").value.trim() : pendingJoinName || "Solo Hráč";
            const soloMode = message.solo_mode || false;
            
            // Ulož do sessionStorage
            sessionStorage.setItem("token", token);
            sessionStorage.setItem("player_id", playerId);
            sessionStorage.setItem("player_name", playerName);
            sessionStorage.setItem("solo_mode", soloMode ? "true" : "false");
            
            // Pokud je solo režim, automaticky nastav ready a spusť hru
            if (soloMode) {
                // Počkej chvíli, aby se lobby_state načetl, pak nastav ready
                setTimeout(() => {
                    sendMessage({ type: "set_ready", ready: true });
                    // Po dalším krátkém čekání spusť hru
                    setTimeout(() => {
                        sendMessage({ type: "start_game" });
                    }, 500);
                }, 500);
            }
            
            showScreen("lobby-screen");
            break;

        case "reconnected":
            playerId = message.player_id;
            // Pokud jsme na login screen a máme reconnect, počkáme na game_state nebo lobby_state
            const loginScreen = document.getElementById("login-screen");
            if (loginScreen && !loginScreen.classList.contains("hidden")) {
                // Necháme server poslat game_state nebo lobby_state, který nás přepne na správnou obrazovku
                // Nepřepínáme hned, protože nevíme, jestli hra probíhá
            }
            break;

        case "lobby_state":
            // Aktualizace stavu lobby
            updateLobby(message);
            
            // Přepnutí na lobby screen
            const isGameActive = message.status === "playing" || message.status === "finished";
            const currentScreen = document.querySelector(".screen:not(.hidden)");
            const isOnGameScreen = currentScreen && currentScreen.id === "game-screen";
            
            // Pokud hra probíhá a hráč je ve hře (je na game-screen), necháme ho tam
            // Jinak přepneme na lobby-screen
            if (isGameActive && isOnGameScreen) {
                // Hráč je ve hře - necháme ho na game-screen
                // Server by měl poslat game_state, který aktualizuje stav
                break;
            }
            
            // Jinak přepneme na lobby-screen
            showScreen("lobby-screen");
            break;
        
        case "color_selected":
            // Barva byla vybrána - aktualizuj lobby
            break;

        case "game_started":
            // Hra začala - zprávy nejsou zobrazovány
            showScreen("game-screen");
            // Pokud je solo režim, zobraz upozornění
            if (message.solo_mode) {
            }
            break;

        case "game_state":
            currentGameState = message;
            // Pokud hra probíhá, přepneme na game-screen
            if (message.status === "playing" || message.status === "finished") {
                showScreen("game-screen");
            }
            updateGame(message);
            break;

        case "dice_rolled":
            // Získej barvu aktuálního hráče
            const currentPlayer = currentGameState?.players?.find(p => p.player_id === currentGameState?.current_player_id);
            const currentPlayerColor = currentPlayer?.color || null;
            updateDice(message.dice_roll, currentPlayerColor);
            // Zprávy o hodu kostkou nejsou zobrazovány
            break;

        case "piece_moved":
            // Zprávy o pohybu figurek nejsou zobrazovány
            break;

        case "game_end":
            // Zprávy o vítězi nejsou zobrazovány
            setTimeout(() => {
                if (confirm("Hra skončila. Chcete se vrátit do lobby?")) {
                    sendMessage({ type: "leave_lobby" });
                }
            }, 2000);
            break;

        case "solo_game_ended":
            // Hra v solo režimu byla ukončena - přesměrování na login
            showScreen("login-screen");
            break;

        case "error":
            showError(message.message);
            break;

        default:
            console.error("Neznámý typ zprávy:", message.type);
    }
}

function showScreen(screenId) {
    // Skryje všechny obrazovky
    document.querySelectorAll(".screen").forEach(screen => {
        screen.classList.add("hidden");
    });
    
    // Zobrazí požadovanou obrazovku
    const targetScreen = document.getElementById(screenId);
    if (targetScreen) {
        targetScreen.classList.remove("hidden");
    }
}

function showError(message) {
    const errorEl = document.getElementById("login-error");
    if (errorEl) {
        errorEl.textContent = message;
        errorEl.classList.add("show");
        setTimeout(() => {
            errorEl.classList.remove("show");
        }, 5000);
    } else {
        alert(message);
    }
}

let isReady = false;

function updateLobby(state) {
    const playersList = document.getElementById("players-list");
    if (!playersList) return;
    
    // Zjištění, zda hra probíhá
    const isGameActive = state.status === "playing" || state.status === "finished";
    
    // Vymazání seznamu hráčů
    playersList.innerHTML = "";
    
    // Vytvoření elementů pro každého hráče
    state.players.forEach(player => {
        const div = document.createElement("div");
        div.className = `player-item ${player.ready ? "ready" : ""}`;
        
        // Určení status textu podle stavu hry
        let statusText = "Čeká...";
        
        if (isGameActive) {
            // Během hry zobrazujeme jiný status
            const piecesCount = player.pieces_count || 0;
            statusText = piecesCount === 4 ? "Vyhrál!" : "Ve hře";
        } else {
            // Hra neprobíhá - zobrazujeme ready status
            statusText = player.ready ? "✓ Připraven" : "Čeká...";
        }
        
        // Získej barvu hráče
        const colorName = player.color || '';
        const colorHex = colorName ? COLORS[colorName] : '';
        const colorDisplay = colorName ? `<span style="display: inline-block; width: 20px; height: 20px; background: ${colorHex}; border-radius: 50%; margin-right: 8px; border: 2px solid #333;"></span>` : '';
        
        // Vytvoření HTML pro player item
        div.innerHTML = `
            <div class="player-item-left">
                ${colorDisplay}
                <span class="player-name">${escapeHtml(player.name)}</span>
            </div>
            <span class="ready-status">${statusText}</span>
        `;
        
        playersList.appendChild(div);
    });
    
    // Aktualizace výběru barev
    updateColorSelection(state);
    
    // Aktualizace ready button podle stavu aktuálního hráče
    const myPlayer = state.players.find(p => p.player_id === playerId);
    const readyBtn = document.getElementById("ready-btn");
    const startGameBtn = document.getElementById("start-game-btn");
    
    if (isGameActive) {
        // Během hry skryjeme ready button
        if (readyBtn) {
            readyBtn.style.display = "none";
        }
        if (startGameBtn) {
            startGameBtn.style.display = "none";
        }
    } else {
        // Když hra neprobíhá, zobrazíme ready button
        if (readyBtn) {
            readyBtn.style.display = "";
            if (myPlayer) {
                isReady = myPlayer.ready || false;
                readyBtn.textContent = isReady ? "Zrušit" : "Připraven";
            }
        }
        // Zobraz tlačítko pro spuštění hry, pokud jsou všichni ready
        if (startGameBtn && state.can_start) {
            startGameBtn.style.display = "";
        } else if (startGameBtn) {
            startGameBtn.style.display = "none";
        }
    }
    
    // Aktualizace status zprávy
    updateLobbyStatus(state, isGameActive);
}

function updateColorSelection(state) {
    const colorSelection = document.getElementById("color-selection");
    const colorButtons = document.getElementById("color-buttons");
    if (!colorSelection || !colorButtons) return;
    
    const myPlayer = state.players.find(p => p.player_id === playerId);
    if (!myPlayer) {
        colorSelection.style.display = "none";
        return;
    }
    
    // Zobraz výběr barev pouze pokud hra neprobíhá a hráč ještě nemá barvu nebo může změnit
    if (state.status === "waiting" && (!myPlayer.color || state.available_colors && state.available_colors.length > 0)) {
        colorSelection.style.display = "block";
        colorButtons.innerHTML = "";
        
        const allColors = state.all_colors || ["red", "blue", "green", "yellow"];
        const usedColors = new Set(state.players.filter(p => p.player_id !== playerId).map(p => p.color).filter(Boolean));
        
        allColors.forEach(color => {
            const button = document.createElement("button");
            button.className = "color-btn";
            button.style.backgroundColor = COLORS[color];
            button.style.border = myPlayer.color === color ? "3px solid #333" : "1px solid #ccc";
            button.title = usedColors.has(color) ? "Obsazeno" : color;
            button.disabled = usedColors.has(color) && myPlayer.color !== color;
            
            if (myPlayer.color === color) {
                button.innerHTML = "✓";
            }
            
            button.onclick = () => {
                if (!usedColors.has(color) || myPlayer.color === color) {
                    sendMessage({ type: "select_color", color: color });
                }
            };
            
            colorButtons.appendChild(button);
        });
    } else {
        colorSelection.style.display = "none";
    }
}

function updateLobbyStatus(state, isGameActive) {
    const statusDiv = document.getElementById("lobby-status");
    if (!statusDiv) return;
    
    // Odstranění všech tříd
    statusDiv.className = "status-message";
    
    if (isGameActive) {
        // Během hry
        if (state.status === "playing") {
            statusDiv.textContent = "Probíhá hra";
            statusDiv.classList.add("playing");
        } else if (state.status === "finished") {
            statusDiv.textContent = "Hra skončila";
            statusDiv.classList.add("finished");
        }
    } else if (state.can_start) {
        // Všichni jsou připraveni
        if (state.solo_mode) {
            statusDiv.textContent = "Všichni jsou připraveni! Klikněte na 'Spustit hru' pro solo režim.";
            statusDiv.classList.add("ready");
        } else {
            statusDiv.textContent = "Všichni jsou připraveni! Hra začne automaticky...";
            statusDiv.classList.add("ready");
            
            // Automaticky spustit hru (pouze pokud není solo režim)
            setTimeout(() => {
                if (state.can_start && state.status === "waiting") {
                    sendMessage({ type: "start_game" });
                }
            }, 1000);
        }
    } else {
        // Čekáme na hráče
        const maxPlayers = 4;
        statusDiv.textContent = `Čekáme na hráče... (${state.players.length}/${maxPlayers})`;
        statusDiv.classList.add("waiting");
    }
}

function updateGame(state) {
    // Aktualizace statistik
    if (state.players) {
        // V solo režimu zobrazuj statistiky pro solo hráče, jinak pro aktuálního hráče
        const statsPlayerId = state.solo_mode && state.solo_player_id ? state.solo_player_id : playerId;
        updateStatistics(state.players, statsPlayerId);
    }
    
    // Zobrazení/skrytí tlačítka pro ukončení hry v solo režimu
    const soloEndGameBox = document.getElementById("solo-end-game-box");
    if (soloEndGameBox) {
        if (state.solo_mode && state.solo_player_id === playerId) {
            soloEndGameBox.style.display = "block";
        } else {
            soloEndGameBox.style.display = "none";
        }
    }
    
    // Aktualizace kostky
    const diceBtn = document.getElementById("roll-dice-btn");
    // V solo režimu může hráč hrát za všechny (pokud je solo_mode aktivní)
    // V solo režimu je solo hráč vždy na tahu, protože hraje za current_player_id
    const isMyTurn = state.solo_mode ? (state.solo_player_id === playerId) : (state.current_player_id === playerId);
    
    if (diceBtn) {
        if (isMyTurn && state.can_roll_dice) {
            diceBtn.disabled = false;
        } else {
            diceBtn.disabled = true;
        }
    }
    
    // Aktualizace kostky s barvou aktuálního hráče
    const currentPlayer = state.players?.find(p => p.player_id === state.current_player_id);
    const currentPlayerColor = currentPlayer?.color || null;
    if (state.last_dice_roll > 0) {
        updateDice(state.last_dice_roll, currentPlayerColor);
    } else {
        updateDice(null, currentPlayerColor);
    }
    
    // Aktualizace hráčů
    updatePlayers(state.players, state.current_player_id);
    
    // Aktualizace hrací plochy
    updateGameBoard(state);
}

function updateDice(value, currentPlayerColor = null) {
    const diceEl = document.getElementById("dice");
    if (!diceEl) return;
    
    diceEl.textContent = value || "?";
    
    // Nastav třídu pro hodnotu
    diceEl.className = `dice dice-${value || "unknown"}`;
    
    // Nastav barvu kostky podle aktuálního hráče
    if (currentPlayerColor && COLORS[currentPlayerColor]) {
        diceEl.style.backgroundColor = COLORS[currentPlayerColor];
        diceEl.style.color = "#ffffff";
        diceEl.style.borderColor = COLORS[currentPlayerColor];
    } else {
        // Výchozí barva
        diceEl.style.backgroundColor = "#667eea";
        diceEl.style.color = "#ffffff";
        diceEl.style.borderColor = "#667eea";
    }
}

// Funkce updateMyPieces byla odstraněna - figurky jsou zobrazovány přímo na hrací ploše

function updatePlayers(players, currentPlayerId) {
    const container = document.getElementById("players-container");
    if (!container) return;
    
    container.innerHTML = "";
    
    players.forEach(player => {
        const div = document.createElement("div");
        div.className = `player-card ${player.player_id === currentPlayerId ? "current" : ""}`;
        
        // Získej barvu hráče
        const colorName = player.color || 'red';
        const colorHex = COLORS[colorName] || COLORS.red;
        
        div.innerHTML = `
            <div class="player-name" style="color: ${colorHex}; font-weight: bold;">
                ${escapeHtml(player.name)}
            </div>
        `;
        container.appendChild(div);
    });
}

function updateStatistics(players, currentPlayerId) {
    const container = document.getElementById("statistics-container");
    if (!container) return;
    
    const myPlayer = players.find(p => p.player_id === currentPlayerId);
    if (!myPlayer || !myPlayer.stats) {
        container.innerHTML = "<div class='stat-item'>Žádné statistiky</div>";
        return;
    }
    
    const stats = myPlayer.stats;
    container.innerHTML = `
        <div class="stat-item">
            <span class="stat-label">Tahy:</span>
            <span class="stat-value">${stats.turns || 0}</span>
        </div>
        <div class="stat-item">
            <span class="stat-label">Nasazení:</span>
            <span class="stat-value">${stats.deployments || 0}</span>
        </div>
        <div class="stat-item">
            <span class="stat-label">Pohyby:</span>
            <span class="stat-value">${stats.moves || 0}</span>
        </div>
        <div class="stat-item">
            <span class="stat-label">Vyhození:</span>
            <span class="stat-value">${stats.captures || 0}</span>
        </div>
        <div class="stat-item">
            <span class="stat-label">Šestky:</span>
            <span class="stat-value">${stats.sixes || 0}</span>
        </div>
    `;
}

// Inicializace boardu - načte SVG a extrahuje anchor body
async function initializeBoard() {
    if (boardSvgElement) {
        return; // Už inicializováno
    }
    
    try {
        const svgText = await loadBoardSvg();
        const boardEl = document.getElementById("game-board");
        if (!boardEl) {
            console.error('Game board element not found');
            return;
        }
        
        // Vlož SVG do DOM
        boardEl.innerHTML = svgText;
        
        // Najdi root SVG element
        boardSvgElement = boardEl.querySelector('svg');
        if (!boardSvgElement) {
            throw new Error('SVG element not found in loaded content');
        }
        
        // Nastav třídu pro styling
        boardSvgElement.setAttribute("class", "ludo-board-svg");
        
        // Extrahuj anchor body
        boardAnchors = readAnchors(boardSvgElement);
        
        // Tvrdá validace anchor body - fail fast
        validateAnchors(boardAnchors);
        
        // Vytvoř nebo najdi vrstvu pro figurky
        pawnsLayer = boardSvgElement.querySelector('#pawns-layer');
        if (!pawnsLayer) {
            pawnsLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
            pawnsLayer.setAttribute("id", "pawns-layer");
            boardSvgElement.appendChild(pawnsLayer);
        }
        
        // Přidej event delegation pro klikání na figurky
        pawnsLayer.addEventListener('click', handlePawnClick);
        
    } catch (error) {
        console.error('Error initializing board:', error);
        alert('Chyba při načítání hrací plochy. Obnovte stránku.');
    }
}

// Aktualizace hrací plochy podle herního stavu
function updateGameBoard(state) {
    // Zajisti, že je board inicializován
    if (!boardSvgElement || !pawnsLayer) {
        initializeBoard().then(() => {
            if (boardSvgElement && pawnsLayer) {
                renderPiecesSVG(state);
            }
        });
        return;
    }
    
    renderPiecesSVG(state);
}

// Renderování figurek pomocí anchor body ze SVG
function renderPiecesSVG(state) {
    if (!pawnsLayer || !boardAnchors) {
        return;
    }
    
    // Vymaž staré figurky
    pawnsLayer.innerHTML = "";
    
    // Seskup figurky podle anchor ID pro stacking
    const groups = {};
    
    state.players.forEach((player, playerIndex) => {
        const colorName = player.color || ['red', 'blue', 'green', 'yellow'][playerIndex] || 'red';
        
        player.pieces.forEach((piece, pieceIndex) => {
            // Získej anchor ID pro figuru - předáme barvu hráče a home_position z piece
            const prevStatus = piece.prev_status || piece.status;
            const prevPos = piece.prev_position !== undefined ? piece.prev_position : piece.position;
            
            const anchorId = pawnToAnchorId({ 
                ...piece, 
                color: colorName,
                home_position: piece.home_position !== undefined ? piece.home_position : pieceIndex
            });
            
            const anchor = boardAnchors[anchorId];
            
            if (!anchor) {
                console.warn(`Anchor not found: ${anchorId}`, {
                    piece: piece,
                    color: colorName,
                    status: piece.status,
                    position: piece.position,
                    home_position: piece.home_position
                });
                return;
            }
            
            // Seskup podle anchor ID
            if (!groups[anchorId]) {
                groups[anchorId] = [];
            }
            groups[anchorId].push({ piece, player, colorName, pieceIndex, anchor });
        });
    });
    
    // Render každou skupinu figurek
    Object.entries(groups).forEach(([anchorId, group]) => {
        group.forEach((item, index) => {
            const { piece, player, colorName, pieceIndex, anchor } = item;
            const offset = STACK_OFFSETS[index] || { dx: 0, dy: 0 };
            
            // Vytvoř SVG group pro figuru
            const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
            g.setAttribute("data-pawn-id", piece.piece_id);
            g.setAttribute("data-player-id", player.player_id);
            g.setAttribute("class", `piece-group piece-${colorName}`);
            
            // Kruh pro figuru (MVP - později může být obrázek)
            const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            circle.setAttribute("cx", anchor.x + offset.dx);
            circle.setAttribute("cy", anchor.y + offset.dy);
            circle.setAttribute("r", 18);
            circle.setAttribute("fill", COLORS[colorName] || "#ccc");
            circle.setAttribute("stroke", "#333");
            circle.setAttribute("stroke-width", "3");
            
            // Text s číslem figury
            const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
            text.setAttribute("x", anchor.x + offset.dx);
            text.setAttribute("y", anchor.y + offset.dy + 6);
            text.setAttribute("text-anchor", "middle");
            text.setAttribute("font-size", "16");
            text.setAttribute("font-weight", "bold");
            text.setAttribute("fill", colorName === 'yellow' ? "#333" : "#fff");
            text.textContent = pieceIndex + 1;
            
            g.appendChild(circle);
            g.appendChild(text);
            
            // Určení, zda je figurka kliknutelná
            // V solo režimu může hráč hrát za všechny (pokud je solo_mode aktivní)
            const isMyTurn = state.solo_mode ? (state.solo_player_id === playerId) : (state.current_player_id === playerId);
            const hasDiceRoll = !state.can_roll_dice && state.last_dice_roll > 0;
            // V solo režimu může hráč klikat na figurky aktuálního hráče (current_player_id)
            const isMyPiece = state.solo_mode ? player.player_id === state.current_player_id : player.player_id === playerId;
            const isNotFinished = piece.status !== "finished" && piece.status !== "FINISHED";
            
            // Pro figurky v domečku (HOME) je potřeba 6ka
            const isInHome = piece.status === "home" || piece.status === "HOME";
            const canPlaceFromHome = isInHome && state.last_dice_roll === 6;
            
            // Pro figurky na hrací ploše stačí jakýkoliv hod
            const isOnBoard = piece.status === "track" || piece.status === "home_lane";
            const canMoveOnBoard = isOnBoard && state.last_dice_roll > 0;
            
            // Figurka je kliknutelná pouze pokud:
            // - je hráč na tahu
            // - má hod kostkou (už nemůže hodit znovu)
            // - figurka není finished
            // - je to hráčova figurka (nebo figurka aktuálního hráče v solo režimu)
            // - (figurka v HOME potřebuje 6ku, figurka na ploše jakýkoliv hod)
            const canMove = isMyTurn && hasDiceRoll && isMyPiece && isNotFinished && (canPlaceFromHome || canMoveOnBoard);
            
            if (canMove) {
                g.setAttribute("class", `piece-group piece-${colorName} clickable`);
                g.style.cursor = "pointer";
                
                // Animace pro kliknutelné figurky
                circle.setAttribute("stroke", "#ffc107");
                circle.setAttribute("stroke-width", "4");
            } else {
                g.style.cursor = "default";
                if (piece.status === "finished" || piece.status === "FINISHED") {
                    g.style.opacity = "0.8";
                }
            }
            
            pawnsLayer.appendChild(g);
        });
    });
}

// Handler pro kliknutí na figuru
function handlePawnClick(event) {
    // Najdi nejbližší element s data-pawn-id
    let target = event.target;
    while (target && target !== pawnsLayer) {
        if (target.hasAttribute && target.hasAttribute('data-pawn-id')) {
            const pawnId = target.getAttribute('data-pawn-id');
            const playerIdAttr = target.getAttribute('data-player-id');
            
            // Zkontroluj, zda je figurka kliknutelná
            if (target.classList && target.classList.contains('clickable')) {
                sendMessage({
                    type: "move_piece",
                    piece_id: pawnId
                });
            }
            return;
        }
        target = target.parentNode;
    }
}

// Staré funkce pro HTML grid byly odstraněny - nyní používáme SVG

// Funkce addMessage byla odstraněna - chat není zobrazován

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

