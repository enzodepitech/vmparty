let socket = null;
let processRunning = false;

// -----------------------------------------------------
// Action functions
// -----------------------------------------------------

// Disable when a process is running (optional)
let actionButtons = ["submitBtn", "deploy-btn"];

function startEdit() => startWebSocketProcess("/ws/edit");
function startDeployment() => startWebSocketProcess("/ws/deploy");

// -----------------------------------------------------
// Utilities
// -----------------------------------------------------

function startWebSocketProcess(url) {
    // url: format /...
    // button_id: html button id string
    if (processRunning) {
        console.log("A Web Socket Process is already running...");
        alert("A Web Socket Process is already running. Wait until finish.")
        return;
    }
    processRunning = true;
    
    const terminal = document.getElementById("terminal-logs");
    const statusBadge = document.getElementById("status-badge");

    // Clear previous logs
    terminal.innerHTML = "";

    // Update UI state
    for (actionButton in actionButtons) {
        document.getElementById(actionButton).disabled = true;
    }
    statusBadge.textContent = "Running...";
    statusBadge.className = "px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 font-medium";

    // Establish WebSocket Connection
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}${url}`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        appendLogLine("[System] Connection established.", "text-indigo-400");
    };

    socket.onmessage = (event) => {
        const line = event.data;
        let colorClass = "text-slate-300";

        // Ansible color
        if (line.includes("ok:")) colorClass = "text-emerald-400";
        else if (line.includes("changed:")) colorClass = "text-amber-300";

        appendLogLine(line, colorClass);
    };

    socket.onerror = (error) => {
        appendLogLine("[Error] WebSocket error occurred.", "text-rose-400 font-semibold");
    };

    socket.onclose = () => {
        for (actionButton in actionButtons) {
            document.getElementById(actionButton).disabled = false;
        }
        statusBadge.textContent = "Finished";
        statusBadge.className = "px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium";
        appendLogLine("[System] Connection closed.", "text-slate-500");
    };

    processRunning = false;
}

function appendLogLine(text, colorClass = "text-slate-300") {
    const terminal = document.getElementById("terminal-logs");
    const lineElement = document.createElement("div");
    lineElement.className = colorClass;
    lineElement.textContent = text;
    terminal.appendChild(lineElement);

    // Auto-scroll to bottom
    terminal.scrollTop = terminal.scrollHeight;
}

function clearLogs() {
    const terminal = document.getElementById("terminal-logs");
    terminal.innerHTML = '<span class="text-slate-500">// Logs cleared. Ready to deploy...</span>';
}
