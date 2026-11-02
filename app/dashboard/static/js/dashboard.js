// --- Переключение табов ---
function switchTab(tabId, btnElement) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

  const targetTab = document.getElementById(`tab-${tabId}`);
  if (targetTab) targetTab.classList.add('active');
  if (btnElement) btnElement.classList.add('active');
}

// --- Буфер логов ---
let logBuffer = [];
let liveTailActive = true;
let currentContainer = null;
let socket = null;
let reconnectTimer = null;

function renderLogs() {
  const sFilter = document.getElementById('serviceFilter').value;
  const lFilter = document.getElementById('levelFilter').value;
  const search = document.getElementById('searchLog').value.toLowerCase();
  const container = document.getElementById('logTerminal');

  if (!container) return;

  const filtered = logBuffer.filter(l => {
    const matchService = sFilter === 'ALL' || l.name === sFilter;
    const matchLevel = lFilter === 'ALL' || l.level === lFilter;
    const matchSearch = l.msg.toLowerCase().includes(search) || l.name.toLowerCase().includes(search);
    return matchService && matchLevel && matchSearch;
  });

  container.innerHTML = filtered.map(l => `
    <div class="log-row">
      <span class="log-time">${escapeHtml(l.time)}</span>
      <span class="log-level lvl-${escapeHtml(l.level)}">${escapeHtml(l.level)}</span>
      <span class="log-service">${escapeHtml(l.name)}</span>
      <span class="log-msg">${escapeHtml(l.msg)}</span>
    </div>
  `).join('');

  if (liveTailActive) {
    container.scrollTop = container.scrollHeight;
  }
}

function applyFilters() { renderLogs(); }
function clearLogs() { logBuffer = []; renderLogs(); }

function toggleLiveTail() {
  liveTailActive = !liveTailActive;
  const btn = document.getElementById('liveTailBtn');
  if (liveTailActive) {
    btn.classList.add('active');
    btn.innerText = "🟢 Live Stream";
  } else {
    btn.classList.remove('active');
    btn.innerText = "⏸️ Paused";
  }
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function nowTime() {
  return new Date().toTimeString().slice(0, 8);
}

// Сообщение самого дашборда (ошибки docker, статус подключения) —
// дубликаты подряд не дублируем, чтобы не заливать терминал
function pushSystem(level, msg) {
  const last = logBuffer[logBuffer.length - 1];
  if (last && last.name === 'docker' && last.msg === msg) return;

  logBuffer.push({ time: nowTime(), level: level, name: 'docker', msg: msg });
  if (logBuffer.length > 1000) logBuffer.shift();
  ensureServiceOption('docker');
  renderLogs();
}

// Логи контейнера могут приходить с именем, которого нет в фильтре сервисов
function ensureServiceOption(name) {
  const select = document.getElementById('serviceFilter');
  if (!select || !name) return;
  for (const option of select.options) {
    if (option.value === name) return;
  }
  const opt = document.createElement('option');
  opt.value = name;
  opt.textContent = name;
  select.appendChild(opt);
}

// --- Список контейнеров ---
async function loadContainers() {
  const select = document.getElementById('containerFilter');
  if (!select) return;

  const path = (window.APP_CONFIG && window.APP_CONFIG.containersPath) || '/dashboard/api/containers';
  try {
    const resp = await fetch(path);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);

    const items = data.containers || [];
    select.innerHTML = '';
    if (!items.length) {
      select.innerHTML = '<option value="">нет контейнеров</option>';
      pushSystem('WARNING', 'Нет запущенных контейнеров — логи не приходят');
      return;
    }

    for (const c of items) {
      const opt = document.createElement('option');
      opt.value = c.name;
      opt.textContent = `${c.name} · ${c.state}`;
      opt.title = `${c.image} — ${c.status}`;
      select.appendChild(opt);
    }
    currentContainer = items[0].name;
    select.value = currentContainer;
    connectLogs();
  } catch (e) {
    pushSystem('ERROR', `Не удалось получить список контейнеров: ${e.message}`);
  }
}

function onContainerChange() {
  const select = document.getElementById('containerFilter');
  currentContainer = select ? select.value : '';
  logBuffer = [];
  renderLogs();

  if (currentContainer) connectLogs();
  else disconnectLogs();
}

// --- WebSocket с логами контейнера ---
function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const path = (window.APP_CONFIG && window.APP_CONFIG.wsPath) || '/dashboard/ws/logs';
  const params = new URLSearchParams();
  if (currentContainer) params.set('container', currentContainer);
  return `${proto}//${location.host}${path}?${params.toString()}`;
}

function disconnectLogs() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (socket) {
    socket.onclose = null;
    try { socket.close(); } catch (e) { /* уже закрыт */ }
    socket = null;
  }
}

function connectLogs() {
  disconnectLogs();
  if (!currentContainer || typeof WebSocket === 'undefined') return;

  try {
    socket = new WebSocket(wsUrl());
  } catch (e) {
    pushSystem('ERROR', `Не удалось открыть WebSocket: ${e.message}`);
    return;
  }

  socket.onopen = () => pushSystem('INFO', `Логи подключены: ${currentContainer}`);

  socket.onmessage = (event) => {
    try {
      // Формат: { "time": "19:12:03", "level": "INFO", "name": "api.gateway", "msg": "..." }
      const logEntry = JSON.parse(event.data);
      if (!logEntry || typeof logEntry.msg !== 'string') return;

      ensureServiceOption(logEntry.name);
      logBuffer.push(logEntry);
      if (logBuffer.length > 1000) logBuffer.shift(); // не перегружаем память браузера
      renderLogs();
    } catch (e) {
      console.error("Log parse error", e);
    }
  };

  // ошибки соединения обрабатывает onclose — там же переподключение
  socket.onerror = () => {};

  socket.onclose = () => {
    socket = null;
    if (!currentContainer) return;
    pushSystem('WARNING', `Соединение с логами потеряно, повтор через 3с (${currentContainer})`);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectLogs();
    }, 3000);
  };
}

// Заглушка: правка пользователя ещё не реализована
function editUser(id) {
  pushSystem('INFO', `Редактирование пользователя #${id} — пока не реализовано`);
}

document.addEventListener("DOMContentLoaded", () => {
  renderLogs();
  loadContainers();
});
