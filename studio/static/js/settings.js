// CONFIG & API KEYS MANAGEMENT
let currentConfig = {
  groq_api_keys: [],
  groq_api_key: '',
  groq_model: 'qwen/qwen3.8-27b',
  openrouter_api_keys: [],
  openrouter_api_key: '',
  openrouter_model: 'nvidia/nemotron-3.5-lightning:free',
  openrouter_vision_model: 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free',
  gemini_api_keys: [],
  gemini_api_key: '',
  gemini_model: 'gemini-2.5-flash',
  ollama_host: 'http://localhost:11434',
  ollama_vision_model: '',
  vision_provider: 'auto'
};

function setSelectValueSafe(elId, val, fallbackVal) {
  const el = document.getElementById(elId);
  if (!el) return;
  const v = val || fallbackVal;
  if (v && !Array.from(el.options).some(o => o.value === v)) {
    const opt = document.createElement('option');
    opt.value = v;
    opt.text = v + ' (Personalizado)';
    el.appendChild(opt);
  }
  el.value = v;
}

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    const cfg = await res.json();
    currentConfig = cfg;

    // Normaliza chaves da Groq
    if (!Array.isArray(currentConfig.groq_api_keys)) {
      currentConfig.groq_api_keys = currentConfig.groq_api_key ? [currentConfig.groq_api_key] : [];
    } else if (currentConfig.groq_api_key && !currentConfig.groq_api_keys.includes(currentConfig.groq_api_key)) {
      currentConfig.groq_api_keys.unshift(currentConfig.groq_api_key);
    }

    // Normaliza chaves do OpenRouter
    if (!Array.isArray(currentConfig.openrouter_api_keys)) {
      currentConfig.openrouter_api_keys = currentConfig.openrouter_api_key ? [currentConfig.openrouter_api_key] : [];
    } else if (currentConfig.openrouter_api_key && !currentConfig.openrouter_api_keys.includes(currentConfig.openrouter_api_key)) {
      currentConfig.openrouter_api_keys.unshift(currentConfig.openrouter_api_key);
    }

    // Normaliza chaves Google Gemini
    if (!Array.isArray(currentConfig.gemini_api_keys)) {
      currentConfig.gemini_api_keys = currentConfig.gemini_api_key ? [currentConfig.gemini_api_key] : [];
    } else if (currentConfig.gemini_api_key && !currentConfig.gemini_api_keys.includes(currentConfig.gemini_api_key)) {
      currentConfig.gemini_api_keys.unshift(currentConfig.gemini_api_key);
    }

    renderKeyLists();
    updateHeaderAiPill(`Groq Cloud, ${formatModelShortName(currentConfig.groq_model || 'qwen/qwen3.8-27b')}`, 'ok');
    setSelectValueSafe('cfg-groq-model', currentConfig.groq_model, 'qwen/qwen3.8-27b');
    setSelectValueSafe('cfg-openrouter-model', currentConfig.openrouter_model, 'nvidia/nemotron-3.5-lightning:free');
    setSelectValueSafe('cfg-vision-provider', currentConfig.vision_provider, 'auto');
    setSelectValueSafe('cfg-gemini-model', currentConfig.gemini_model, 'gemini-2.5-flash');
    setSelectValueSafe('cfg-openrouter-vision-model', currentConfig.openrouter_vision_model, 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free');
    document.getElementById('cfg-ollama-host').value = currentConfig.ollama_host || 'http://localhost:11434';
    if (document.getElementById('cfg-ollama-vision-model')) {
      document.getElementById('cfg-ollama-vision-model').value = currentConfig.ollama_vision_model || '';
    }
    if (document.getElementById('cfg-raw-mangas-dir')) {
      document.getElementById('cfg-raw-mangas-dir').value = currentConfig.raw_mangas_dir || 'C:\\Users\\ja329\\OneDrive\\Documentos\\MANGAS';
    }
    if (document.getElementById('cfg-translated-mangas-dir')) {
      document.getElementById('cfg-translated-mangas-dir').value = currentConfig.translated_mangas_dir || 'C:\\Users\\ja329\\OneDrive\\Documentos\\MANGAS';
    }

    // Auto-sincronização com o perfil permanente salvo no navegador (localStorage)
    const hasServerKeys = (currentConfig.groq_api_keys && currentConfig.groq_api_keys.length > 0) ||
                          (currentConfig.openrouter_api_keys && currentConfig.openrouter_api_keys.length > 0) ||
                          (currentConfig.gemini_api_keys && currentConfig.gemini_api_keys.length > 0);
    if (!hasServerKeys) {
      const savedProfileRaw = localStorage.getItem(PROFILE_STORAGE_KEY);
      if (savedProfileRaw) {
        try {
          const p = JSON.parse(savedProfileRaw);
          const hasLocalProfileKeys = (p.groq_api_keys && p.groq_api_keys.length > 0) ||
                                      (p.openrouter_api_keys && p.openrouter_api_keys.length > 0) ||
                                      (p.gemini_api_keys && p.gemini_api_keys.length > 0);
          if (hasLocalProfileKeys) {
            if (p.groq_api_keys && p.groq_api_keys.length > 0) {
              currentConfig.groq_api_keys = p.groq_api_keys;
              currentConfig.groq_api_key = p.groq_api_keys[0];
            }
            if (p.openrouter_api_keys && p.openrouter_api_keys.length > 0) {
              currentConfig.openrouter_api_keys = p.openrouter_api_keys;
              currentConfig.openrouter_api_key = p.openrouter_api_keys[0];
            }
            if (p.gemini_api_keys && p.gemini_api_keys.length > 0) {
              currentConfig.gemini_api_keys = p.gemini_api_keys;
              currentConfig.gemini_api_key = p.gemini_api_keys[0];
            }
            if (p.groq_model) currentConfig.groq_model = p.groq_model;
            if (p.openrouter_model) currentConfig.openrouter_model = p.openrouter_model;
            if (p.openrouter_vision_model) currentConfig.openrouter_vision_model = p.openrouter_vision_model;
            if (p.gemini_model) currentConfig.gemini_model = p.gemini_model;
            if (p.ollama_host) currentConfig.ollama_host = p.ollama_host;
            if (typeof p.ollama_vision_model === 'string') currentConfig.ollama_vision_model = p.ollama_vision_model;
            if (p.vision_provider) currentConfig.vision_provider = p.vision_provider;

            setSelectValueSafe('cfg-groq-model', currentConfig.groq_model, 'qwen/qwen3.8-27b');
            setSelectValueSafe('cfg-openrouter-model', currentConfig.openrouter_model, 'nvidia/nemotron-3.5-lightning:free');
            setSelectValueSafe('cfg-vision-provider', currentConfig.vision_provider, 'auto');
            setSelectValueSafe('cfg-gemini-model', currentConfig.gemini_model, 'gemini-2.5-flash');
            setSelectValueSafe('cfg-openrouter-vision-model', currentConfig.openrouter_vision_model, 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free');
            if (document.getElementById('cfg-ollama-host')) {
              document.getElementById('cfg-ollama-host').value = currentConfig.ollama_host || 'http://localhost:11434';
            }
            if (document.getElementById('cfg-ollama-vision-model')) {
              document.getElementById('cfg-ollama-vision-model').value = currentConfig.ollama_vision_model || '';
            }
            fetch('/api/config', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(currentConfig)
            }).then(() => {
              renderKeyLists();
              loadStatus();
              console.log("⚡ Chaves restauradas automaticamente do perfil salvo no navegador!");
            }).catch(() => {});
          }
        } catch (e) {}
      }
    } else {
      // Servidor possui chaves válidas; atualiza o backup deste navegador
      saveBrowserProfile(currentConfig, false);
    }

    // Atualiza status do badge de Google Drive
    const driveBadge = document.getElementById('profile-drive-badge');
    if (driveBadge) {
      if (currentConfig.drive_connected) {
        driveBadge.innerText = 'Google Drive ligado';
        driveBadge.className = 'meta-badge highlight';
      } else {
        driveBadge.innerText = 'Perfil local';
        driveBadge.className = 'meta-badge';
      }
    }
  } catch (e) {
    console.error("Erro ao carregar configurações:", e);
  }
}

async function browseFolder(type) {
  try {
    const title = type === 'raw' ? "Selecione a Pasta dos Mangás Originais (Raws)" : "Selecione a Pasta dos Mangás Traduzidos [PT-BR]";
    const res = await fetch('/api/pick_path', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title })
    });
    const data = await res.json();
    if (data.success && data.path) {
      if (type === 'raw') {
        document.getElementById('cfg-raw-mangas-dir').value = data.path;
      } else if (type === 'translated') {
        document.getElementById('cfg-translated-mangas-dir').value = data.path;
      }
    } else if (data.is_headless) {
      alert(data.error || "Seleção visual de pasta disponível apenas no PC local. Digite ou cole o caminho manualmente no campo ao lado.");
      const targetInp = document.getElementById(type === 'raw' ? 'cfg-raw-mangas-dir' : 'cfg-translated-mangas-dir');
      if (targetInp) targetInp.focus();
    }
  } catch (e) {
    console.error("Erro ao selecionar pasta:", e);
  }
}

async function saveConfig(showProfileMsg = false) {
  try {
    currentConfig.groq_model = document.getElementById('cfg-groq-model').value;
    currentConfig.openrouter_model = document.getElementById('cfg-openrouter-model').value;
    currentConfig.ollama_host = document.getElementById('cfg-ollama-host').value.trim();

    const visionProvEl = document.getElementById('cfg-vision-provider');
    if (visionProvEl) currentConfig.vision_provider = visionProvEl.value || 'auto';
    const gemModelEl = document.getElementById('cfg-gemini-model');
    if (gemModelEl) currentConfig.gemini_model = gemModelEl.value || 'gemini-2.5-flash';
    const orVisionEl = document.getElementById('cfg-openrouter-vision-model');
    if (orVisionEl) currentConfig.openrouter_vision_model = orVisionEl.value || 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free';
    const olVisionEl = document.getElementById('cfg-ollama-vision-model');
    if (olVisionEl) currentConfig.ollama_vision_model = olVisionEl.value.trim();
    
    const rawEl = document.getElementById('cfg-raw-mangas-dir');
    if (rawEl && rawEl.value.trim()) {
      currentConfig.raw_mangas_dir = rawEl.value.trim();
    }
    const transEl = document.getElementById('cfg-translated-mangas-dir');
    if (transEl && transEl.value.trim()) {
      currentConfig.translated_mangas_dir = transEl.value.trim();
    }

    if (!Array.isArray(currentConfig.groq_api_keys)) currentConfig.groq_api_keys = [];
    if (!Array.isArray(currentConfig.openrouter_api_keys)) currentConfig.openrouter_api_keys = [];
    if (!Array.isArray(currentConfig.gemini_api_keys)) currentConfig.gemini_api_keys = [];

    currentConfig.groq_api_key = currentConfig.groq_api_keys[0] || '';
    currentConfig.openrouter_api_key = currentConfig.openrouter_api_keys[0] || '';
    currentConfig.gemini_api_key = currentConfig.gemini_api_keys[0] || '';

    const saveRes = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentConfig)
    });
    if (saveRes.ok) {
      saveBrowserProfile(currentConfig, showProfileMsg);
      if (!showProfileMsg) {
        alert("Configurações salvas.");
      }
      loadStatus();
      loadLibrary();
    } else {
      alert("Erro ao salvar configurações.");
    }
  } catch (e) {
    alert("Erro de conexão ao salvar configurações.");
  }
}
