// Globální proměnné
let ws = null;
let playerId = null;
let token = null;
let playerName = null;
let roomCode = null;
let currentGameState = null;
let pendingAction = null; // {type, name, solo_mode, room_code}
let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 30000;

const COLORS = {
    red: "#e74c3c",
    blue: "#3498db",
    green: "#2ecc71",
    yellow: "#f1c40f"
};

let boardAnchors = {};
let boardSvgElement = null;
let pawnsLayer = null;

const STACK_OFFSETS = [
    { dx: 0, dy: 0 },
    { dx: 10, dy: 0 },
    { dx: -10, dy: 0 },
    { dx: 0, dy: 10 },
    { dx: 0, dy: -10 }
];

// ── SVG board ────────────────────────────────────

async function loadBoardSvg() {
    const response = await fetch('/static/images/board_modern_52.svg');
    if (!response.ok) throw new Error(`Failed to load SVG: ${response.status}`);
    return await response.text();
}

function readAnchors(svgEl) {
    const anchors = {};
    svgEl.querySelectorAll('[id^="track-"], [id^="home-"], [id^="lane-"]').forEach(el => {
        anchors[el.id] = { x: Number(el.getAttribute("cx")), y: Number(el.getAttribute("cy")) };
    });
    return anchors;
}

function validateAnchors(anchors) {
    const errors = [];
    for (let i = 0; i < 52; i++) {
        if (!anchors[`track-${i}`]) errors.push(`track-${i}`);
    }
    ['red', 'blue', 'yellow', 'green'].forEach(color => {
        for (let i = 0; i < 4; i++) {
            if (!anchors[`home-${color}-${i}`]) errors.push(`home-${color}-${i}`);
            if (!anchors[`lane-${color}-${i}`]) errors.push(`lane-${color}-${i}`);
        }
    });
    if (errors.length > 0) {
        console.error('Missing anchors:', errors);
        throw new Error(`SVG validation failed: ${errors.length} missing anchors`);
    }
}

function pawnToAnchorId(pawn) {
    const color = pawn.color || 'red';
    const status = (pawn.status || '').toLowerCase();

    if (status === "track") return `track-${pawn.position % 52}`;
    if (status === "home") return `home-${color}-${pawn.home_position !== undefined ? pawn.home_position : 0}`;
    if (status === "home_lane") {
        let pos = 0;
        if (pawn.position !== undefined && pawn.position !== null) pos = Math.min(Math.max(pawn.position, 0), 3);
        return `lane-${color}-${pos}`;
    }
    if (status === "finished") return `lane-${color}-3`;

    return `home-${color}-0`;
}

// ── DOMContentLoaded ─────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    const mainTitle = document.getElementById('main-title');
    if (mainTitle) mainTitle.addEventListener('click', () => window.location.reload());

    token = sessionStorage.getItem("token");
    playerId = sessionStorage.getItem("player_id");
    playerName = sessionStorage.getItem("player_name");
    roomCode = sessionStorage.getItem("room_code");

    const savedName = sessionStorage.getItem("player_name");
    const nameInput = document.getElementById("player-name");
    if (savedName && nameInput) nameInput.value = savedName;

    // Vytvořit hru
    document.getElementById("create-room-btn")?.addEventListener("click", () => {
        const name = getNameFromInput();
        if (!name) return;
        pendingAction = { type: "create_room", name, solo_mode: false };
        openWebSocket();
    });

    // Připojit se do místnosti
    document.getElementById("join-room-btn")?.addEventListener("click", () => {
        const name = getNameFromInput();
        if (!name) return;
        const code = document.getElementById("room-code-input")?.value.trim().toUpperCase();
        if (!code || code.length !== 4) {
            showError("Zadejte 4-písmenný kód místnosti");
            return;
        }
        pendingAction = { type: "join_room", name, room_code: code };
        openWebSocket();
    });

    // Solo režim
    document.getElementById("solo-mode-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        const name = getNameFromInput() || "Solo Hráč";
        pendingAction = { type: "create_room", name, solo_mode: true };
        sessionStorage.setItem("player_name", name);
        openWebSocket();
    });

    // Enter v jméně → vytvořit hru
    nameInput?.addEventListener("keypress", (e) => {
        if (e.key === "Enter") document.getElementById("create-room-btn")?.click();
    });

    // Enter v kódu místnosti → připojit
    document.getElementById("room-code-input")?.addEventListener("keypress", (e) => {
        if (e.key === "Enter") document.getElementById("join-room-btn")?.click();
    });

    // Lobby buttons
    document.getElementById("ready-btn")?.addEventListener("click", handleSetReady);
    document.getElementById("start-game-btn")?.addEventListener("click", () => sendMessage({ type: "start_game" }));
    document.getElementById("leave-btn")?.addEventListener("click", handleLeaveLobby);
    document.getElementById("roll-dice-btn")?.addEventListener("click", () => sendMessage({ type: "roll_dice" }));
    document.getElementById("end-game-btn")?.addEventListener("click", handleEndGame);

    // Reconnect pokud máme token
    if (token && playerId) {
        pendingAction = null;
        openWebSocket();
    }

    // Verze
    fetch('/static/version.json')
        .then(r => r.json())
        .then(data => {
            const el = document.getElementById('app-version');
            if (el && data.version) el.textContent = data.version;
        })
        .catch(() => {});
});

function getNameFromInput() {
    const input = document.getElementById("player-name");
    const name = input?.value.trim();
    if (!name) {
        showError("Zadejte jméno");
        return null;
    }
    return name;
}

// ── WebSocket ────────────────────────────────────

function openWebSocket() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        sendPendingAction();
        return;
    }
    if (ws) { ws.onclose = null; ws.close(); ws = null; }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        reconnectAttempts = 0;
        sendPendingAction();
    };

    ws.onmessage = (event) => {
        try {
            handleMessage(JSON.parse(event.data));
        } catch (e) {
            console.error("WS parse error:", e);
        }
    };

    ws.onerror = () => {};

    ws.onclose = () => {
        if (token) {
            reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), MAX_RECONNECT_DELAY);
            setTimeout(() => openWebSocket(), delay);
        }
    };
}

function sendPendingAction() {
    if (pendingAction) {
        sendMessage(pendingAction);
        pendingAction = null;
    } else if (token) {
        sendMessage({ type: "reconnect", token });
    }
}

function sendMessage(message) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(message));
    }
}

// ── Message handler ──────────────────────────────

let isReady = false;

function handleMessage(message) {
    switch (message.type) {
        case "ping":
            sendMessage({ type: "pong" });
            return;

        case "player_connection_lost":
        case "player_disconnected":
        case "player_reconnected":
            if (message.message) showToast(message.message);
            break;

        case "game_reset":
            if (message.message) showToast(message.message);
            showScreen("login-screen");
            clearSession();
            break;

        case "joined":
            playerId = message.player_id;
            token = message.token;
            roomCode = message.room_code;
            playerName = document.getElementById("player-name")?.value.trim() || "Hráč";

            sessionStorage.setItem("token", token);
            sessionStorage.setItem("player_id", playerId);
            sessionStorage.setItem("player_name", playerName);
            sessionStorage.setItem("room_code", roomCode);

            if (message.solo_mode) {
                setTimeout(() => {
                    sendMessage({ type: "set_ready", ready: true });
                    setTimeout(() => sendMessage({ type: "start_game" }), 500);
                }, 500);
            }

            showScreen("lobby-screen");
            break;

        case "reconnected":
            playerId = message.player_id;
            roomCode = message.room_code;
            break;

        case "lobby_state":
            updateLobby(message);
            const isGameActive = message.status === "playing" || message.status === "finished";
            const currentScreen = document.querySelector(".screen:not(.hidden)");
            if (isGameActive && currentScreen?.id === "game-screen") break;
            showScreen("lobby-screen");
            break;

        case "game_started":
            showScreen("game-screen");
            break;

        case "game_state":
            currentGameState = message;
            if (message.status === "playing" || message.status === "finished") showScreen("game-screen");
            updateGame(message);
            break;

        case "dice_rolled": {
            const cp = currentGameState?.players?.find(p => p.player_id === currentGameState?.current_player_id);
            updateDice(message.dice_roll, cp?.color || null);
            break;
        }

        case "piece_moved":
            break;

        case "game_end":
            showGameEndOverlay(message.winner_name);
            break;

        case "return_to_lobby":
            hideGameEndOverlay();
            showScreen("lobby-screen");
            break;

        case "solo_game_ended":
            showScreen("login-screen");
            clearSession();
            break;

        case "error":
            if (message.message === "Neplatný token" || message.message === "Místnost již neexistuje") {
                clearSession();
            }
            showError(message.message);
            break;
    }
}

// ── Screen & session ─────────────────────────────

function showScreen(screenId) {
    document.querySelectorAll(".screen").forEach(s => s.classList.add("hidden"));
    document.getElementById(screenId)?.classList.remove("hidden");
    if (screenId === "game-screen" && !boardSvgElement) initializeBoard();
}

function clearSession() {
    sessionStorage.removeItem("token");
    sessionStorage.removeItem("player_id");
    sessionStorage.removeItem("room_code");
    token = null;
    playerId = null;
    roomCode = null;
    isReady = false;
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
}

function showError(message) {
    const el = document.getElementById("login-error");
    if (el) {
        el.textContent = message;
        el.classList.add("show");
        setTimeout(() => el.classList.remove("show"), 5000);
    } else {
        alert(message);
    }
}

function showToast(text) {
    const toast = document.createElement("div");
    toast.className = "game-toast";
    toast.textContent = text;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("show"));
    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => toast.remove(), 400);
    }, 4000);
}

// ── Lobby handlers ───────────────────────────────

function handleSetReady() {
    isReady = !isReady;
    sendMessage({ type: "set_ready", ready: isReady });
    const btn = document.getElementById("ready-btn");
    if (btn) btn.textContent = isReady ? "Zrušit" : "Připraven";
}

function handleLeaveLobby() {
    if (ws && ws.readyState === WebSocket.OPEN) sendMessage({ type: "leave_lobby" });
    clearSession();
    showScreen("login-screen");
}

function handleEndGame() {
    if (ws && ws.readyState === WebSocket.OPEN) sendMessage({ type: "end_solo_game" });
    clearSession();
    showScreen("login-screen");
}

// ── Lobby UI ─────────────────────────────────────

function updateLobby(state) {
    // Room code
    const rcDisplay = document.getElementById("room-code-display");
    if (rcDisplay && state.room_code) {
        rcDisplay.innerHTML = `Kód místnosti: <span class="code">${escapeHtml(state.room_code)}</span>`;
    }

    const playersList = document.getElementById("players-list");
    if (!playersList) return;

    const isGameActive = state.status === "playing" || state.status === "finished";
    playersList.innerHTML = "";

    state.players.forEach(player => {
        const div = document.createElement("div");
        div.className = `player-item ${player.ready ? "ready" : ""}`;
        let statusText = isGameActive
            ? (player.pieces_count === 4 ? "Vyhrál!" : "Ve hře")
            : (player.ready ? "✓ Připraven" : "Čeká...");

        const colorName = player.color || '';
        const colorHex = colorName ? COLORS[colorName] : '';
        const colorDot = colorName
            ? `<span style="display:inline-block;width:20px;height:20px;background:${colorHex};border-radius:50%;margin-right:8px;border:2px solid #333;"></span>`
            : '';

        div.innerHTML = `<div class="player-item-left">${colorDot}<span class="player-name">${escapeHtml(player.name)}</span></div><span class="ready-status">${statusText}</span>`;
        playersList.appendChild(div);
    });

    updateColorSelection(state);

    const myPlayer = state.players.find(p => p.player_id === playerId);
    const readyBtn = document.getElementById("ready-btn");
    const startBtn = document.getElementById("start-game-btn");

    if (isGameActive) {
        if (readyBtn) readyBtn.style.display = "none";
        if (startBtn) startBtn.style.display = "none";
    } else {
        if (readyBtn) {
            readyBtn.style.display = "";
            if (myPlayer) {
                isReady = myPlayer.ready || false;
                readyBtn.textContent = isReady ? "Zrušit" : "Připraven";
            }
        }
        if (startBtn) startBtn.style.display = state.can_start ? "" : "none";
    }

    updateLobbyStatus(state, isGameActive);
}

function updateColorSelection(state) {
    const sel = document.getElementById("color-selection");
    const btns = document.getElementById("color-buttons");
    if (!sel || !btns) return;

    const myPlayer = state.players.find(p => p.player_id === playerId);
    if (!myPlayer || state.status !== "waiting") { sel.style.display = "none"; return; }

    sel.style.display = "block";
    btns.innerHTML = "";

    const allColors = state.all_colors || ["red", "blue", "green", "yellow"];
    const usedColors = new Set(state.players.filter(p => p.player_id !== playerId).map(p => p.color).filter(Boolean));

    allColors.forEach(color => {
        const button = document.createElement("button");
        button.className = "color-btn";
        button.style.backgroundColor = COLORS[color];
        button.style.border = myPlayer.color === color ? "3px solid #333" : "1px solid #ccc";
        button.title = usedColors.has(color) ? "Obsazeno" : color;
        button.disabled = usedColors.has(color) && myPlayer.color !== color;
        if (myPlayer.color === color) button.innerHTML = "✓";
        button.onclick = () => {
            if (!usedColors.has(color) || myPlayer.color === color) {
                sendMessage({ type: "select_color", color });
            }
        };
        btns.appendChild(button);
    });
}

function updateLobbyStatus(state, isGameActive) {
    const div = document.getElementById("lobby-status");
    if (!div) return;
    div.className = "status-message";

    if (isGameActive) {
        div.textContent = state.status === "playing" ? "Probíhá hra" : "Hra skončila";
    } else if (state.can_start) {
        if (state.solo_mode) {
            div.textContent = "Klikněte na 'Spustit hru' pro solo režim.";
            div.classList.add("ready");
        } else {
            div.textContent = "Všichni jsou připraveni! Hra začne automaticky...";
            div.classList.add("ready");
            setTimeout(() => {
                if (state.can_start && state.status === "waiting") sendMessage({ type: "start_game" });
            }, 1000);
        }
    } else {
        div.textContent = `Čekáme na hráče... (${state.players.length}/4)`;
        div.classList.add("waiting");
    }
}

// ── Game UI ──────────────────────────────────────

function updateGame(state) {
    if (state.players) {
        const sid = state.solo_mode && state.solo_player_id ? state.solo_player_id : playerId;
        updateStatistics(state.players, sid);
    }

    const soloBox = document.getElementById("solo-end-game-box");
    if (soloBox) soloBox.style.display = (state.solo_mode && state.solo_player_id === playerId) ? "block" : "none";

    const diceBtn = document.getElementById("roll-dice-btn");
    const isMyTurn = state.solo_mode ? (state.solo_player_id === playerId) : (state.current_player_id === playerId);
    if (diceBtn) diceBtn.disabled = !(isMyTurn && state.can_roll_dice);

    const cp = state.players?.find(p => p.player_id === state.current_player_id);
    updateDice(state.last_dice_roll > 0 ? state.last_dice_roll : null, cp?.color || null);
    updatePlayers(state.players, state.current_player_id);
    updateGameBoard(state);
}

function updateDice(value, color) {
    const el = document.getElementById("dice");
    if (!el) return;
    el.textContent = value || "?";
    el.className = `dice dice-${value || "unknown"}`;
    if (color && COLORS[color]) {
        el.style.backgroundColor = COLORS[color];
        el.style.color = "#fff";
        el.style.borderColor = COLORS[color];
    } else {
        el.style.backgroundColor = "#667eea";
        el.style.color = "#fff";
        el.style.borderColor = "#667eea";
    }
}

function updatePlayers(players, currentPlayerId) {
    const container = document.getElementById("players-container");
    if (!container) return;
    container.innerHTML = "";
    players.forEach(p => {
        const div = document.createElement("div");
        div.className = `player-card ${p.player_id === currentPlayerId ? "current" : ""}`;
        const hex = COLORS[p.color || 'red'] || COLORS.red;
        div.innerHTML = `<div class="player-name" style="color:${hex};font-weight:bold;">${escapeHtml(p.name)}</div>`;
        container.appendChild(div);
    });
}

function updateStatistics(players, currentPlayerId) {
    const container = document.getElementById("statistics-container");
    if (!container) return;
    const p = players.find(x => x.player_id === currentPlayerId);
    if (!p?.stats) { container.innerHTML = "<div class='stat-item'>Žádné statistiky</div>"; return; }
    const s = p.stats;
    container.innerHTML = `
        <div class="stat-item"><span class="stat-label">Tahy:</span><span class="stat-value">${s.turns||0}</span></div>
        <div class="stat-item"><span class="stat-label">Nasazení:</span><span class="stat-value">${s.deployments||0}</span></div>
        <div class="stat-item"><span class="stat-label">Pohyby:</span><span class="stat-value">${s.moves||0}</span></div>
        <div class="stat-item"><span class="stat-label">Vyhození:</span><span class="stat-value">${s.captures||0}</span></div>
        <div class="stat-item"><span class="stat-label">Šestky:</span><span class="stat-value">${s.sixes||0}</span></div>
    `;
}

// ── Board ────────────────────────────────────────

async function initializeBoard() {
    if (boardSvgElement) return;
    try {
        const svgText = await loadBoardSvg();
        const boardEl = document.getElementById("game-board");
        if (!boardEl) return;
        boardEl.innerHTML = svgText;
        boardSvgElement = boardEl.querySelector('svg');
        if (!boardSvgElement) throw new Error('SVG element not found');
        boardSvgElement.setAttribute("class", "ludo-board-svg");
        boardAnchors = readAnchors(boardSvgElement);
        validateAnchors(boardAnchors);
        pawnsLayer = boardSvgElement.querySelector('#pawns-layer');
        if (!pawnsLayer) {
            pawnsLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
            pawnsLayer.setAttribute("id", "pawns-layer");
            boardSvgElement.appendChild(pawnsLayer);
        }
        pawnsLayer.addEventListener('click', handlePawnClick);
    } catch (error) {
        console.error('Board init error:', error);
        alert('Chyba při načítání hrací plochy. Obnovte stránku.');
    }
}

function updateGameBoard(state) {
    if (!boardSvgElement || !pawnsLayer) {
        initializeBoard().then(() => { if (boardSvgElement && pawnsLayer) renderPiecesSVG(state); });
        return;
    }
    renderPiecesSVG(state);
}

function renderPiecesSVG(state) {
    if (!pawnsLayer || !boardAnchors) return;
    pawnsLayer.innerHTML = "";

    const groups = {};
    state.players.forEach((player, pi) => {
        const colorName = player.color || ['red','blue','green','yellow'][pi] || 'red';
        player.pieces.forEach((piece, idx) => {
            const anchorId = pawnToAnchorId({ ...piece, color: colorName, home_position: piece.home_position !== undefined ? piece.home_position : idx });
            const anchor = boardAnchors[anchorId];
            if (!anchor) return;
            if (!groups[anchorId]) groups[anchorId] = [];
            groups[anchorId].push({ piece, player, colorName, pieceIndex: idx, anchor });
        });
    });

    Object.entries(groups).forEach(([, group]) => {
        group.forEach((item, index) => {
            const { piece, player, colorName, pieceIndex, anchor } = item;
            const offset = STACK_OFFSETS[index] || { dx: 0, dy: 0 };

            const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
            g.setAttribute("data-pawn-id", piece.piece_id);
            g.setAttribute("data-player-id", player.player_id);
            g.setAttribute("class", `piece-group piece-${colorName}`);

            const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            circle.setAttribute("cx", anchor.x + offset.dx);
            circle.setAttribute("cy", anchor.y + offset.dy);
            circle.setAttribute("r", 18);
            circle.setAttribute("fill", COLORS[colorName] || "#ccc");
            circle.setAttribute("stroke", "#333");
            circle.setAttribute("stroke-width", "3");

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

            const isMyTurn = state.solo_mode ? (state.solo_player_id === playerId) : (state.current_player_id === playerId);
            const hasDice = !state.can_roll_dice && state.last_dice_roll > 0;
            const isMyPiece = state.solo_mode ? player.player_id === state.current_player_id : player.player_id === playerId;
            const notFinished = piece.status !== "finished";
            const inHome = piece.status === "home";
            const canPlace = inHome && state.last_dice_roll === 6;
            const onBoard = piece.status === "track" || piece.status === "home_lane";
            const canMoveBoard = onBoard && state.last_dice_roll > 0;
            const canMove = isMyTurn && hasDice && isMyPiece && notFinished && (canPlace || canMoveBoard);

            if (canMove) {
                g.setAttribute("class", `piece-group piece-${colorName} clickable`);
                g.style.cursor = "pointer";
                circle.setAttribute("stroke", "#ffc107");
                circle.setAttribute("stroke-width", "4");
            } else {
                g.style.cursor = "default";
                if (piece.status === "finished") g.style.opacity = "0.8";
            }

            pawnsLayer.appendChild(g);
        });
    });
}

function handlePawnClick(event) {
    let target = event.target;
    while (target && target !== pawnsLayer) {
        if (target.hasAttribute?.('data-pawn-id')) {
            if (target.classList?.contains('clickable')) {
                sendMessage({ type: "move_piece", piece_id: target.getAttribute('data-pawn-id') });
            }
            return;
        }
        target = target.parentNode;
    }
}

// ── Game end overlay ─────────────────────────────

function showGameEndOverlay(winnerName) {
    let overlay = document.getElementById("game-end-overlay");
    if (!overlay) {
        overlay = document.createElement("div");
        overlay.id = "game-end-overlay";
        overlay.className = "game-end-overlay";
        document.body.appendChild(overlay);
    }
    overlay.innerHTML = `
        <div class="game-end-box">
            <h2>Hra skončila!</h2>
            <p>Vyhrál: <strong>${escapeHtml(winnerName)}</strong></p>
            <button class="btn-primary" onclick="sendMessage({type:'new_game'}); hideGameEndOverlay();">Nová hra</button>
            <button class="btn-secondary" onclick="hideGameEndOverlay(); handleLeaveLobby();">Odejít</button>
        </div>
    `;
    overlay.style.display = "flex";
}

function hideGameEndOverlay() {
    const o = document.getElementById("game-end-overlay");
    if (o) o.style.display = "none";
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}
