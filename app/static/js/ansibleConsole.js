let socket = null;
let processRunning = false;

// -----------------------------------------------------
// Action functions
// -----------------------------------------------------

function startDelete(event, configId) {
    if (event) event.preventDefault();

    startWebSocketProcess(`/ws/delete/${configId}`);
}

function startEdit(event, configId) {
    if (event) event.preventDefault();
    
    const editForm = document.getElementById("editForm");
    const formData = new FormData(editForm);
    
    const payload = {
        team_name: formData.get("name"),
        vm_id: parseInt(formData.get("vm_id")),
        vm_ip: formData.get("vm_ip"),
        student_emails: getCombinedEmails()
    };
    
    startWebSocketProcess(`/ws/edit/${configId}`, payload);
}

function startProvide(event) {
    if (event) event.preventDefault();
    const editForm = document.getElementById("addForm");
    const formData = new FormData(editForm);
    
    const payload = {
        team_name: formData.get("team_name"),
        vm_id: parseInt(formData.get("vm_id")),
        vm_ip: formData.get("vm_ip"),
        student_emails: formData.get("student_emails"),
        has_shared_user: formData.has("shared_user"),
        is_container: formData.has("is_container")
    };
    
    startWebSocketProcess("/ws/add", payload);
}

// -----------------------------------------------------
// Utilities
// -----------------------------------------------------

function startWebSocketProcess(url, params = {}) {
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

    statusBadge.textContent = "Running...";
    statusBadge.className = "px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 font-medium";

    // Establish WebSocket Connection
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}${url}`;
    console.log(wsUrl);

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        appendLogLine("[System] Connection established.", "text-indigo-400");

        if (url.includes("/ws/edit")) {
            socket.send(JSON.stringify(params));
        }
        else if (url.includes("/ws/add")) {
            socket.send(JSON.stringify(params));
        }
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
        statusBadge.textContent = "Finished";
        statusBadge.className = "px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium";
        appendLogLine("[System] Connection closed.", "text-slate-500");

        // Reload configurations
        const response = fetch(window.location.href);
        const html = response.text();
        
        // Parse the HTML and extract the updated table body
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const newTableBody = doc.getElementById('config-table-body').innerHTML;
        
        // Swap out the old rows instantly without breaking the WS connection
        document.getElementById('config-table-body').innerHTML = newTableBody;
        
        processRunning = false;
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
