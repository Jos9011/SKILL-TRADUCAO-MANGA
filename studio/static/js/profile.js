// PROFILE & KEY PERSISTENCE (LOCALSTORAGE & DRIVE)
const PROFILE_STORAGE_KEY = 'manga_studio_profile_v1';

function saveBrowserProfile(cfg, showFeedback = true) {
  try {
    const payload = {
      groq_api_keys: cfg.groq_api_keys || [],
      openrouter_api_keys: cfg.openrouter_api_keys || [],
      gemini_api_keys: cfg.gemini_api_keys || [],
      groq_model: cfg.groq_model || 'qwen/qwen3.8-27b',
      openrouter_model: cfg.openrouter_model || 'nvidia/nemotron-3.5-lightning:free',
      openrouter_vision_model: cfg.openrouter_vision_model || 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free',
      gemini_model: cfg.gemini_model || 'gemini-2.5-flash',
      ollama_host: cfg.ollama_host || 'http://localhost:11434',
      ollama_vision_model: cfg.ollama_vision_model || '',
      vision_provider: cfg.vision_provider || 'auto',
      updated_at: new Date().toISOString()
    };
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(payload));
    if (showFeedback) {
      const badge = document.getElementById('profile-sync-msg');
      if (badge) {
        badge.innerText = 'Perfil salvo neste navegador e no Google Drive.';
        setTimeout(() => { badge.innerText = ''; }, 4000);
      } else {
        alert('Chaves salvas neste navegador e no Google Drive.');
      }
    }
  } catch (e) {
    console.error('Erro ao salvar no localStorage:', e);
  }
}

async function syncBrowserProfileToServer() {
  try {
    const raw = localStorage.getItem(PROFILE_STORAGE_KEY);
    if (!raw) {
      alert('Nenhum perfil salvo foi encontrado neste navegador ainda.\nInsira suas chaves e clique em "Salvar Chaves no Meu Perfil" primeiro!');
      return;
    }
    const profile = JSON.parse(raw);
    if (!currentConfig) currentConfig = {};
    if (Array.isArray(profile.groq_api_keys) && profile.groq_api_keys.length > 0) {
      currentConfig.groq_api_keys = profile.groq_api_keys;
      currentConfig.groq_api_key = profile.groq_api_keys[0];
    }
    if (Array.isArray(profile.openrouter_api_keys) && profile.openrouter_api_keys.length > 0) {
      currentConfig.openrouter_api_keys = profile.openrouter_api_keys;
      currentConfig.openrouter_api_key = profile.openrouter_api_keys[0];
    }
    if (Array.isArray(profile.gemini_api_keys) && profile.gemini_api_keys.length > 0) {
      currentConfig.gemini_api_keys = profile.gemini_api_keys;
      currentConfig.gemini_api_key = profile.gemini_api_keys[0];
    }
    if (profile.groq_model) currentConfig.groq_model = profile.groq_model;
    if (profile.openrouter_model) currentConfig.openrouter_model = profile.openrouter_model;
    if (profile.openrouter_vision_model) currentConfig.openrouter_vision_model = profile.openrouter_vision_model;
    if (profile.gemini_model) currentConfig.gemini_model = profile.gemini_model;
    if (profile.ollama_host) currentConfig.ollama_host = profile.ollama_host;
    if (typeof profile.ollama_vision_model === 'string') currentConfig.ollama_vision_model = profile.ollama_vision_model;
    if (profile.vision_provider) currentConfig.vision_provider = profile.vision_provider;

    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentConfig)
    });
    if (res.ok) {
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
      alert('Chaves recuperadas: o servidor já pode usá-las.');
      renderKeyLists();
      loadStatus();
    } else {
      alert('Erro ao enviar chaves para o servidor.');
    }
  } catch (e) {
    alert('Erro ao sincronizar perfil: ' + e);
  }
}

function exportProfileJson() {
  const raw = localStorage.getItem(PROFILE_STORAGE_KEY);
  const dataToExport = raw ? JSON.parse(raw) : currentConfig;
  const blob = new Blob([JSON.stringify(dataToExport, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'manga_studio_perfil.json';
  a.click();
  URL.revokeObjectURL(url);
}

function importProfileJson(evt) {
  const file = evt.target.files && evt.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async (e) => {
    try {
      const imported = JSON.parse(e.target.result);
      if (imported.groq_api_keys || imported.groq_api_key) {
        const keys = imported.groq_api_keys || [imported.groq_api_key];
        currentConfig.groq_api_keys = keys;
        currentConfig.groq_api_key = keys[0];
      }
      if (imported.openrouter_api_keys || imported.openrouter_api_key) {
        const orKeys = imported.openrouter_api_keys || [imported.openrouter_api_key];
        currentConfig.openrouter_api_keys = orKeys;
        currentConfig.openrouter_api_key = orKeys[0];
      }
      if (imported.gemini_api_keys || imported.gemini_api_key) {
        const gemKeys = imported.gemini_api_keys || [imported.gemini_api_key];
        currentConfig.gemini_api_keys = gemKeys;
        currentConfig.gemini_api_key = gemKeys[0];
      }
      if (imported.groq_model) currentConfig.groq_model = imported.groq_model;
      if (imported.openrouter_model) currentConfig.openrouter_model = imported.openrouter_model;
      if (imported.openrouter_vision_model) currentConfig.openrouter_vision_model = imported.openrouter_vision_model;
      if (imported.gemini_model) currentConfig.gemini_model = imported.gemini_model;
      if (imported.ollama_host) currentConfig.ollama_host = imported.ollama_host;
      if (typeof imported.ollama_vision_model === 'string') currentConfig.ollama_vision_model = imported.ollama_vision_model;
      if (imported.vision_provider) currentConfig.vision_provider = imported.vision_provider;

      saveBrowserProfile(currentConfig, false);
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentConfig)
      });
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
      alert('Backup importado: as chaves foram restauradas.');
      renderKeyLists();
      loadStatus();
    } catch (err) {
      alert('Erro ao importar arquivo de perfil: ' + err);
    }
  };
  reader.readAsText(file);
  evt.target.value = '';
}
