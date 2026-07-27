let socket = null;

function startDeployment() {
    const terminal = document.getElementById("terminal-logs");
    const deployBtn = document.getElementById("deploy-btn");
    const statusBadge = document.getElementById("status-badge");

    // Clear previous logs
    terminal.innerHTML = "";

    // Update UI state
    deployBtn.disabled = true;
    statusBadge.textContent = "Deploying...";
    statusBadge.className = "px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 font-medium";

    // Establish WebSocket Connection
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/deploy`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        appendLogLine("[System] Connection established to deployment engine...", "text-indigo-400");
    };

    socket.onmessage = (event) => {
        const line = event.data;

        // Basic ANSI/Ansible text color highlight parsing
        let colorClass = "text-slate-300";
        if (line.includes("PLAY [") || line.includes("TASK [")) colorClass = "text-cyan-400 font-bold";
        else if (line.includes("ok:")) colorClass = "text-emerald-400";
        else if (line.includes("changed:")) colorClass = "text-amber-300";
        else if (line.includes("FAILED!") || line.includes("fatal:")) colorClass = "text-rose-400 font-semibold";
        else if (line.includes("--- Starting") || line.includes("--- Deployment")) colorClass = "text-indigo-400 font-semibold";

        appendLogLine(line, colorClass);
    };

    socket.onerror = (error) => {
        appendLogLine("[Error] WebSocket error occurred.", "text-rose-400 font-semibold");
    };

    socket.onclose = () => {
        deployBtn.disabled = false;
        statusBadge.textContent = "Finished";
        statusBadge.className = "px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium";
        appendLogLine("[System] Connection closed.", "text-slate-500");
    };
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
