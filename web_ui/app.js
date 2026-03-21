/* Godot Studio Agent — Web UI 交互逻辑 */

const API = '';  // 同域，无需前缀

// ─── 状态 ─────────────────────────────────────────────────────────────────────
let totalCmds = 0, successCmds = 0;
let currentCode = { content: '', filename: 'new_script.gd' };
let pipelineMode = false;

// ─── DOM 引用 ─────────────────────────────────────────────────────────────────
const messages = document.getElementById('messages');
const cmdInput = document.getElementById('cmdInput');
const btnSend = document.getElementById('btnSend');
const sendLabel = document.getElementById('sendLabel');
const sendSpinner = document.getElementById('sendSpinner');
const codeContent = document.getElementById('codeContent');
const codeFilename = document.getElementById('codeFilename');
const rolesContainer = document.getElementById('rolesContainer');
const historyList = document.getElementById('historyList');
const healthDot = document.getElementById('healthDot');
const btnPipeline = document.getElementById('btnPipeline');

// 调试面板
const dbgTotal = document.getElementById('dbgTotal');
const dbgSuccess = document.getElementById('dbgSuccess');
const dbgRole = document.getElementById('dbgRole');
const dbgConf = document.getElementById('dbgConf');

// 角色图标映射
const ROLE_ICONS = {
    developer: '🏗️',
    code_generator: '💻',
    tester: '🧪',
    ai_controller: '🤖',
    resource_manager: '🎨',
    simulation: '⚙️',
    narrative: '📖',
    ui_designer: '🖼️',
    audio_manager: '🎵',
    level_designer: '🗺️',
    optimizer: '⚡',
};

// ─── 初始化 ───────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
    await checkHealth();
    await loadRoles();
    loadHistory();
    bindEvents();
});

// ─── 绑定事件 ─────────────────────────────────────────────────────────────────
function bindEvents() {
    btnSend.addEventListener('click', onSend);
    cmdInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(); }
    });

    // 快捷命令
    document.querySelectorAll('.qcmd').forEach(btn => {
        btn.addEventListener('click', () => {
            cmdInput.value = btn.dataset.cmd;
            onSend();
        });
    });

    // 流水线切换
    btnPipeline.addEventListener('click', () => {
        pipelineMode = !pipelineMode;
        btnPipeline.style.borderColor = pipelineMode ? 'var(--accent)' : '';
        btnPipeline.style.color = pipelineMode ? 'var(--accent)' : '';
        cmdInput.placeholder = pipelineMode
            ? '流水线模式：每行一条命令，顺序执行\n例：\n生成玩家移动脚本\n生成血量系统\n创建玩家 HUD'
            : '用自然语言描述你需要什么… 例如：为 Boss 创建多阶段 AI';
        showToast(pipelineMode ? '🔀 流水线模式已开启（换行分隔命令）' : '💬 单命令模式');
    });

    // 复制代码
    document.getElementById('btnCopy').addEventListener('click', () => {
        navigator.clipboard.writeText(currentCode.content).then(() => showToast('📋 代码已复制到剪贴板'));
    });

    // 下载代码
    document.getElementById('btnSaveFile').addEventListener('click', () => {
        const blob = new Blob([currentCode.content], { type: 'text/plain' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = currentCode.filename;
        a.click();
        showToast('💾 已下载 ' + currentCode.filename);
    });

    // 清空会话
    document.getElementById('btnNewSession').addEventListener('click', async () => {
        await fetch(API + '/session/clear', { method: 'POST' });
        messages.innerHTML = '';
        historyList.innerHTML = '';
        totalCmds = successCmds = 0;
        updateDebug(null);
        appendSystemMsg('🔄 会话已清空，开始新项目！');
        showToast('✅ 新会话已开始');
    });
}

// ─── 发送命令 ─────────────────────────────────────────────────────────────────
async function onSend() {
    const input = cmdInput.value.trim();
    if (!input) return;
    cmdInput.value = '';
    setLoading(true);

    if (pipelineMode) {
        const cmds = input.split('\n').map(s => s.trim()).filter(Boolean);
        appendUserMsg('🔀 流水线 (' + cmds.length + ' 步):\n' + cmds.join('\n'));
        await executePipeline(cmds);
    } else {
        appendUserMsg(input);
        await executeCommand(input);
    }

    setLoading(false);
    loadHistory();
}

async function executeCommand(command) {
    totalCmds++;
    try {
        const res = await fetch(API + '/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command })
        });
        const data = await res.json();
        if (data.success) successCmds++;
        renderAgentResult(data);
        updateDebug(data);
    } catch (e) {
        appendErrorMsg('请求失败：' + e.message);
    }
}

async function executePipeline(commands) {
    try {
        const res = await fetch(API + '/pipeline', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ commands })
        });
        const data = await res.json();
        appendSystemMsg(`流水线完成：${data.steps} 步，成功 ${data.results.filter(r => r.success).length} 步`);
        data.results.forEach(r => {
            totalCmds++;
            if (r.success) successCmds++;
            renderAgentResult(r);
        });
        updateDebug(data.results[data.results.length - 1]);
    } catch (e) {
        appendErrorMsg('流水线失败：' + e.message);
    }
}

// ─── 渲染结果 ─────────────────────────────────────────────────────────────────
function renderAgentResult(data) {
    const meta = data._meta || {};
    const role = meta.role || data.role || '—';
    const conf = meta.confidence ? (meta.confidence * 100).toFixed(0) + '%' : '';
    const icon = ROLE_ICONS[role] || '🤖';

    let html = `
    <div class="msg-agent-meta">
      <span class="role-tag">${icon} ${role}</span>
      ${conf ? `<span class="conf-tag">置信度 ${conf}</span>` : ''}
    </div>
    <div>${escapeHtml(data.message || '')}</div>
  `;

    const d = data.data || {};

    // 代码预览
    if (d.code) {
        currentCode = { content: d.code, filename: d.script_name || 'script.gd' };
        updateCodePanel(d.code, d.script_name);
        html += `
      <div class="msg-code-preview" onclick="scrollToCode()" title="点击查看完整代码">
${escapeHtml(d.code.substring(0, 200))}${d.code.length > 200 ? '\n...' : ''}
      </div>
    `;
    }

    // 提示信息
    if (d.tips) html += `<div class="msg-tips">💡 ${escapeHtml(d.tips)}</div>`;

    // 优化建议列表
    if (d.tips && Array.isArray(d.tips)) {
        html += '<ul style="margin:6px 0 0 16px;font-size:12.5px;color:var(--text-sub)">';
        d.tips.forEach(t => { html += `<li>${escapeHtml(t)}</li>`; });
        html += '</ul>';
    }

    appendMsg('msg-agent', '🎮', html);
}

function updateCodePanel(code, filename) {
    codeFilename.textContent = filename || 'script.gd';
    codeContent.textContent = code;
    hljs.highlightElement(codeContent);
}

function scrollToCode() {
    document.querySelector('.panel-code').scrollTo({ top: 0, behavior: 'smooth' });
}

// ─── 调试面板 ─────────────────────────────────────────────────────────────────
function updateDebug(data) {
    dbgTotal.textContent = totalCmds;
    dbgSuccess.textContent = totalCmds > 0 ? Math.round(successCmds / totalCmds * 100) + '%' : '—';
    if (data && data._meta) {
        dbgRole.textContent = data._meta.role || '—';
        dbgConf.textContent = data._meta.confidence ? (data._meta.confidence * 100).toFixed(0) + '%' : '—';
    }
}

// ─── 角色面板 ─────────────────────────────────────────────────────────────────
async function loadRoles() {
    try {
        const res = await fetch(API + '/roles');
        const data = await res.json();
        rolesContainer.innerHTML = '';
        data.roles.forEach(role => {
            const icon = ROLE_ICONS[role.name] || '🔧';
            const card = document.createElement('div');
            card.className = 'role-card';
            card.innerHTML = `
        <span class="role-icon">${icon}</span>
        <div class="role-info">
          <div class="role-name">${role.name}</div>
          <div class="role-desc" title="${escapeHtml(role.description)}">${escapeHtml(role.description)}</div>
        </div>
      `;
            card.addEventListener('click', () => {
                document.querySelectorAll('.role-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                const caps = role.capabilities.join('、');
                appendSystemMsg(`📋 ${icon} <strong>${role.name}</strong>：${role.description}<br>能力：${escapeHtml(caps)}`);
            });
            rolesContainer.appendChild(card);
        });
    } catch (e) {
        rolesContainer.innerHTML = '<div style="color:var(--text-sub);font-size:12px;padding:8px">加载角色失败</div>';
    }
}

// ─── 历史记录 ─────────────────────────────────────────────────────────────────
async function loadHistory() {
    try {
        const res = await fetch(API + '/history?limit=15');
        const data = await res.json();
        historyList.innerHTML = '';
        [...data.history].reverse().forEach(item => {
            const icon = item.success ? '✅' : '❌';
            const div = document.createElement('div');
            div.className = 'history-item';
            div.innerHTML = `
        <span class="hi-icon">${icon}</span>
        <span class="hi-text" title="${escapeHtml(item.prompt)}">${escapeHtml(item.prompt)}</span>
        <span class="hi-role">${item.role}</span>
      `;
            div.addEventListener('click', () => {
                cmdInput.value = item.prompt;
                cmdInput.focus();
            });
            historyList.appendChild(div);
        });
    } catch (e) { }
}

// ─── 健康检查 ─────────────────────────────────────────────────────────────────
async function checkHealth() {
    try {
        const res = await fetch(API + '/health');
        const data = await res.json();
        healthDot.classList.add(data.status === 'healthy' ? 'ok' : 'err');
        healthDot.title = `状态: ${data.status}，角色数: ${data.roles}`;
    } catch (e) {
        healthDot.classList.add('err');
    }
}

// ─── 消息辅助 ─────────────────────────────────────────────────────────────────
function appendMsg(cls, icon, html) {
    const div = document.createElement('div');
    div.className = cls;
    div.innerHTML = `
    <span class="msg-icon">${icon}</span>
    <div class="msg-bubble">${html}</div>
  `;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

function appendUserMsg(text) {
    appendMsg('msg-user', '👤', escapeHtml(text).replace(/\n/g, '<br>'));
}
function appendSystemMsg(html) {
    appendMsg('msg-system', '🎮', html);
}
function appendErrorMsg(text) {
    appendMsg('msg-agent', '❌', `<span style="color:var(--danger)">${escapeHtml(text)}</span>`);
}

function setLoading(loading) {
    btnSend.disabled = loading;
    sendLabel.classList.toggle('hidden', loading);
    sendSpinner.classList.toggle('hidden', !loading);
}

function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showToast(msg, duration = 2500) {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.classList.remove('hidden');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.add('hidden'), duration);
}
