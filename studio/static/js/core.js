let currentSelectedManga = null;

let selectedOptions = {
  ocr: 'auto',
  adult: true,
  provider: 'auto',
  colorize: false
};

let activeResult = null;

let libraryData = { translated: [], raw: [] };

let currentRuleTab = 'aprendizado';

// TAB SWITCHING & MOBILE NAVIGATION
function toggleMobileDrawer(forceOpen) {
  const sb = document.getElementById('mobile-sidebar');
  const bd = document.getElementById('mobile-drawer-backdrop');
  if (!sb || !bd) return;
  const shouldOpen = typeof forceOpen === 'boolean' ? forceOpen : !sb.classList.contains('mobile-open');
  sb.classList.toggle('mobile-open', shouldOpen);
  bd.classList.toggle('open', shouldOpen);
}

function markPlayerActive() {
  const bar = document.getElementById('player-bar');
  if (bar) bar.classList.add('has-activity');
  document.body.classList.add('has-player-activity');
}

function dismissMobilePlayer() {
  const bar = document.getElementById('player-bar');
  if (bar) bar.classList.remove('has-activity');
  document.body.classList.remove('has-player-activity');
}

function focusLiveProgress() {
  const liveSec = document.getElementById('live-progress-section');
  if (liveSec && liveSec.style.display !== 'none') {
    switchTab('translate');
    setTimeout(() => {
      liveSec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 60);
  }
}

function switchTab(tabId) {
  document.querySelectorAll('.tab-view').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('.mobile-nav-item').forEach(n => n.classList.remove('active'));

  const targetTab = document.getElementById(`tab-${tabId}`);
  const targetNav = document.getElementById(`nav-${tabId}`);
  const targetMobileNav = document.getElementById(`mnav-${tabId}`);
  if (targetTab) targetTab.classList.add('active');
  if (targetNav) targetNav.classList.add('active');
  if (targetMobileNav) targetMobileNav.classList.add('active');

  const titles = {
    translate: 'Traduzir',
    library: 'Biblioteca',
    quotas: 'Cotas de IA',
    rules: 'Regras e glossário',
    settings: 'Configurações'
  };
  document.getElementById('view-title').innerText = titles[tabId] || 'Manga Studio';

  toggleMobileDrawer(false);
  const mainEl = document.querySelector('.main-content');
  if (mainEl) mainEl.scrollTop = 0;

  if (tabId === 'library') loadLibrary();
  if (tabId === 'quotas') loadStatus();
  if (tabId === 'rules') loadRules();
  if (tabId === 'settings') loadConfig();
}

function formatModelShortName(modelName) {
  const m = String(modelName || '').trim();
  const ml = m.toLowerCase();
  if (!m) return 'Qwen 3.8 27B';
  if (ml.includes('qwen3.8-27b')) return 'Qwen 3.8 (27B)';
  if (ml.includes('gpt-oss-120b')) return 'GPT-OSS 120B';
  if (ml.includes('gpt-oss-20b')) return 'GPT-OSS 20B';
  if (ml.includes('maverick')) return 'Llama 4 Maverick';
  if (ml.includes('scout')) return 'Llama 4 Scout';
  return m.split('/').pop();
}

function formatDurationPt(sec) {
  const s = Math.max(0, Math.round(Number(sec || 0)));
  if (!s) return '0s';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${r}s`;
  return `${r}s`;
}

// Tema claro/escuro: sem escolha salva, segue o sistema; a escolha fica só neste navegador
function toggleTheme() {
  const root = document.documentElement;
  const current = root.dataset.theme || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = current === 'dark' ? 'light' : 'dark';
  root.dataset.theme = next;
  try { localStorage.setItem('ms-theme', next); } catch (e) {}
}

function updateHeaderAiPill(labelText, state = 'ok') {
  const lbl = document.getElementById('header-ai-label');
  const dot = document.getElementById('header-ai-dot');
  if (lbl && labelText) lbl.innerText = labelText;
  if (dot) {
    dot.style.backgroundColor = state === 'err' ? 'var(--redpen)' : state === 'warn' ? 'var(--warn)' : 'var(--ok)';
  }
}

// UTILS
function escapeHtml(text) {
  if (!text) return '';
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeQuotes(text) {
  if (!text) return '';
  return text.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

// PWA & APP WINDOW
let deferredPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  const btn = document.getElementById('btn-install-pwa');
  if (btn) btn.style.display = 'inline-flex';
});

async function installPWA() {
  if (deferredPrompt) {
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      const btn = document.getElementById('btn-install-pwa');
      if (btn) btn.style.display = 'none';
    }
    deferredPrompt = null;
  } else {
    alert("Para fixar o Manga Studio como aplicativo nativo:\n\n1. Use o atalho oficial 'Manga Studio' que criamos na sua Área de Trabalho!\n2. Ou no menu do navegador (⋮), clique em 'Instalar Manga Studio' ou 'Criar Atalho'.");
  }
}

async function openAsDesktopWindow() {
  try {
    const btn = document.getElementById('btn-open-app-window');
    if (btn) btn.innerText = "Abrindo Janela...";
    await fetch('/api/launch_app_window', { method: 'POST' });
    setTimeout(() => {
      if (btn) {
        btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 14H5V8h14v10z"/></svg> Modo App Desktop`;
      }
    }, 2000);
  } catch (e) {
    console.error("Erro ao abrir janela de app:", e);
  }
}

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(err => console.log('SW reg error:', err));
  });
}

// Encerrar o servidor local (no .exe e no .bat ele fica rodando escondido depois de fechar a janela)
async function shutdownApp() {
  if (!confirm('Encerrar o Manga Studio neste computador?')) return;
  try {
    let res = await fetch('/api/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (res.status === 409) {
      if (!confirm('Há uma tradução em andamento. O que já foi traduzido fica salvo. Encerrar mesmo assim?')) return;
      res = await fetch('/api/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"force": true}' });
    }
    const data = await res.json();
    if (!data.success) { alert(data.error || 'Não foi possível encerrar.'); return; }
    document.body.innerHTML = '<div style="display:grid;place-items:center;height:100dvh;font:16px var(--font-ui);color:var(--tone);text-align:center;padding:24px">Manga Studio encerrado. Pode fechar esta janela.</div>';
  } catch (e) {
    alert('Não foi possível encerrar: ' + e);
  }
}
