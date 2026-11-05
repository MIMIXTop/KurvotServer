// --- Переключение табов ---
function switchTab(tabId, btnElement) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

  const targetTab = document.getElementById(`tab-${tabId}`);
  if (targetTab) targetTab.classList.add('active');
  if (btnElement) btnElement.classList.add('active');
  if (tabId === 'users') loadUsers();
}

// --- Буфер логов ---
let logBuffer = [];
let liveTailActive = true;
let currentContainer = null;
let socket = null;
let reconnectTimer = null;

function parseLogEntry(entry) {
  const rawMessage = String(entry.msg ?? '');
  const match = rawMessage.match(
    /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\|\s*([A-Z]+)\s+\|\s*([^|]+?)\s+\|\s?(.*)$/s
  );

  if (!match) return entry;

  return {
    ...entry,
    time: match[1],
    level: match[2],
    name: match[3].trim(),
    msg: match[4]
  };
}

function renderLogs() {
  const sFilter = document.getElementById('serviceFilter').value;
  const lFilter = document.getElementById('levelFilter').value;
  const search = document.getElementById('searchLog').value.toLowerCase();
  const container = document.getElementById('logTerminal');

  if (!container) return;

  const filtered = logBuffer.filter(l => {
    const matchService = sFilter === 'ALL' || l.name === sFilter;
    const matchLevel = lFilter === 'ALL' || l.level === lFilter;
    const matchSearch = [l.time, l.level, l.name, l.msg]
      .some(value => String(value ?? '').toLowerCase().includes(search));
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

function usersPath() {
  return (window.APP_CONFIG && window.APP_CONFIG.usersPath) || '/dashboard/api/users';
}

function formatUserDate(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

function setUsersError(message) {
  const error = document.getElementById('usersError');
  if (!error) return;
  error.textContent = message;
  error.hidden = !message;
}

function roleOptions(selected) {
  return ['teacher', 'admin']
    .map(role => `<option value="${role}" ${role === selected ? 'selected' : ''}>${role.toUpperCase()}</option>`)
    .join('');
}

async function changeUserRole(email, role) {
  try {
    const response = await fetch(`${usersPath()}/${encodeURIComponent(email)}/role`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    await loadUsers();
  } catch (error) {
    setUsersError(`Не удалось изменить роль: ${error.message}`);
  }
}

async function loadUsers() {
  const body = document.getElementById('usersTableBody');
  if (!body) return;
  setUsersError('');
  try {
    const response = await fetch(usersPath());
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    body.innerHTML = data.length ? data.map(user => `
      <tr>
        <td>${escapeHtml(user.name || 'Без имени')}</td>
        <td>${escapeHtml(user.email)}</td>
        <td>
          <select data-email="${escapeHtml(user.email)}" onchange="changeUserRole(this.dataset.email, this.value)">
            ${roleOptions(user.role)}
          </select>
        </td>
        <td><span class="user-status user-status-${escapeHtml(user.status)}">${escapeHtml(user.status)}</span></td>
        <td>${user.telegram_linked ? 'Привязан' : 'Не привязан'}</td>
        <td>${escapeHtml(formatUserDate(user.last_login_at))}</td>
      </tr>
    `).join('') : '<tr><td colspan="6">Пользователей пока нет</td></tr>';
  } catch (error) {
    body.innerHTML = '<tr><td colspan="6">Не удалось загрузить пользователей</td></tr>';
    setUsersError(`Ошибка загрузки пользователей: ${error.message}`);
  }
}

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

  logBuffer.push(parseLogEntry({ time: nowTime(), level: level, name: 'docker', msg: msg }));
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
      // Формат: { "time": "...", "level": "INFO", "name": "container", "msg": "..." }
      const logEntry = parseLogEntry(JSON.parse(event.data));
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

document.addEventListener("DOMContentLoaded", () => {
  renderLogs();
  loadContainers();
  loadUsers();
});
