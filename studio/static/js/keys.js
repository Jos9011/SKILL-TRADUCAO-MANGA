// Lista de chaves de um provedor: número, chave mascarada, Testar e Remover
function renderKeyList(listId, keys, provider, removeFn, emptyText, prefixLen) {
  const box = document.getElementById(listId);
  if (!box) return;
  if (!keys || keys.length === 0) {
    box.innerHTML = `<div class="key-empty">${emptyText}</div>`;
    return;
  }
  box.innerHTML = keys.map((k, idx) => {
    const masked = k.length > 14 ? k.substring(0, prefixLen) + '...' + k.substring(k.length - 4) : k;
    return `
      <div class="key-item">
        <div class="key-meta">
          <span class="tag">Chave ${idx + 1}</span>
          <span class="key-code">${escapeHtml(masked)}</span>
        </div>
        <div class="key-actions">
          <button class="btn-small" onclick="testKey('${provider}', '${escapeQuotes(k)}', this)">Testar</button>
          <button class="btn-small danger" onclick="${removeFn}(${idx})">Remover</button>
        </div>
      </div>`;
  }).join('');
}

function renderKeyLists() {
  renderKeyList('groq-key-list', currentConfig.groq_api_keys, 'groq', 'removeGroqKey', 'Nenhuma chave Groq ainda.', 8);
  renderKeyList('openrouter-key-list', currentConfig.openrouter_api_keys, 'openrouter', 'removeOpenRouterKey', 'Nenhuma chave OpenRouter ainda.', 10);
  renderKeyList('gemini-key-list', currentConfig.gemini_api_keys, 'gemini', 'removeGeminiKey', 'Opcional. Sem chave Gemini, a leitura por imagem usa Groq, OpenRouter ou Ollama.', 8);
}

function addGroqKey() {
  const input = document.getElementById('new-groq-key');
  const val = input.value.trim();
  if (!val) return;
  if (!val.startsWith('gsk_')) {
    if (!confirm("Esta chave não começa com 'gsk_'. Deseja adicionar mesmo assim?")) return;
  }
  if (currentConfig.groq_api_keys.includes(val)) {
    alert("Esta chave já está cadastrada!");
    return;
  }
  currentConfig.groq_api_keys.push(val);
  currentConfig.groq_api_key = currentConfig.groq_api_keys[0];
  input.value = '';
  renderKeyLists();
}

function removeGroqKey(idx) {
  if (confirm("Deseja remover esta chave da Groq?")) {
    currentConfig.groq_api_keys.splice(idx, 1);
    currentConfig.groq_api_key = currentConfig.groq_api_keys[0] || '';
    renderKeyLists();
  }
}

function addOpenRouterKey() {
  const input = document.getElementById('new-openrouter-key');
  const val = input.value.trim();
  if (!val) return;
  if (!val.startsWith('sk-or-')) {
    if (!confirm("Esta chave não começa com 'sk-or-'. Deseja adicionar mesmo assim?")) return;
  }
  if (currentConfig.openrouter_api_keys.includes(val)) {
    alert("Esta chave já está cadastrada!");
    return;
  }
  currentConfig.openrouter_api_keys.push(val);
  currentConfig.openrouter_api_key = currentConfig.openrouter_api_keys[0];
  input.value = '';
  renderKeyLists();
}

function removeOpenRouterKey(idx) {
  if (confirm("Deseja remover esta chave do OpenRouter?")) {
    currentConfig.openrouter_api_keys.splice(idx, 1);
    currentConfig.openrouter_api_key = currentConfig.openrouter_api_keys[0] || '';
    renderKeyLists();
  }
}

function addGeminiKey() {
  const input = document.getElementById('new-gemini-key');
  if (!input) return;
  const val = input.value.trim();
  if (!val) return;
  if (val.startsWith('gsk_') || val.startsWith('sk-or-')) {
    alert("Esta chave pertence à Groq/OpenRouter, não ao Google Gemini (começa com 'AIza...' ou 'AQ...').");
    return;
  }
  if (!val.startsWith('AIza') && !val.startsWith('AQ.')) {
    if (!confirm("Esta chave não começa com 'AIza' ou 'AQ.'. Deseja adicionar mesmo assim?")) return;
  }
  if (!Array.isArray(currentConfig.gemini_api_keys)) currentConfig.gemini_api_keys = [];
  if (currentConfig.gemini_api_keys.includes(val)) {
    alert("Esta chave Gemini já está cadastrada!");
    return;
  }
  currentConfig.gemini_api_keys.push(val);
  currentConfig.gemini_api_key = currentConfig.gemini_api_keys[0];
  input.value = '';
  renderKeyLists();
}

function removeGeminiKey(idx) {
  if (confirm("Deseja remover esta chave Google Gemini?")) {
    currentConfig.gemini_api_keys.splice(idx, 1);
    currentConfig.gemini_api_key = currentConfig.gemini_api_keys[0] || '';
    renderKeyLists();
  }
}

async function testKey(provider, key, btnEl) {
  const origText = btnEl.innerText;
  btnEl.innerText = "Testando...";
  btnEl.disabled = true;
  try {
    let targetModel = '';
    if (provider === 'groq') {
      targetModel = document.getElementById('cfg-groq-model')?.value || currentConfig.groq_model || 'qwen/qwen3.8-27b';
    } else if (provider === 'gemini') {
      targetModel = document.getElementById('cfg-gemini-model')?.value || currentConfig.gemini_model || 'gemini-2.5-flash';
    }
    const res = await fetch('/api/test_key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: provider, key: key, model: targetModel, deep: true })
    });
    const data = await res.json();
    const icon = data.valid ? (data.rate_limited ? "Limite atingido: " : "Funcionando: ") : "Não funcionou: ";
    alert(icon + data.msg);
    if (document.getElementById('tab-quotas')?.classList.contains('active')) {
      loadStatus(false);
    }
  } catch (e) {
    alert("Erro ao testar chave.");
  } finally {
    btnEl.innerText = origText;
    btnEl.disabled = false;
  }
}

async function testOllamaHost() {
  const resSpan = document.getElementById('ollama-test-result');
  const body = {
    host: document.getElementById('cfg-ollama-host').value.trim(),
    model: (document.getElementById('cfg-ollama-model') || {}).value || '',
    num_ctx: parseInt((document.getElementById('cfg-ollama-num-ctx') || {}).value || '16384', 10)
  };
  resSpan.innerText = 'Conectando e medindo a velocidade (pode levar até 1 minuto na primeira vez)...';
  try {
    const res = await fetch('/api/test_ollama', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await res.json();
    if (d.ok) {
      resSpan.innerHTML = `<span class="tag ok">Ligado</span> ${escapeHtml(d.model)}: ${d.tok_s} tokens/s, ${escapeHtml(d.speed_label)}. Exemplo: "${escapeHtml(d.sample)}"`;
    } else {
      resSpan.innerHTML = `<span class="tag warn">Não funcionou</span> ${escapeHtml(d.error || 'Sem resposta.')}`;
    }
  } catch (e) {
    resSpan.innerHTML = '<span class="tag err">Erro</span> Não foi possível testar agora.';
  }
}

async function exportTrainingDataset() {
  const st = document.getElementById('dataset-export-status');
  if (st) st.innerHTML = 'Exportando o histórico de traduções...';
  try {
    const r = await fetch('/api/dataset/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format: 'sharegpt' })
    });
    const d = await r.json();
    if (d.ok) {
      if (st) st.innerHTML = `<span class="tag ok">Pronto</span> ${d.total_pairs} pares exportados (${d.size_kb} KB) para o Drive.`;
    } else {
      if (st) st.innerHTML = `<span class="tag err">Erro</span> ${escapeHtml(d.error || 'Falha ao exportar')}`;
    }
  } catch (err) {
    if (st) st.innerHTML = `<span class="tag err">Erro de conexão</span> ${escapeHtml(String(err))}`;
  }
}
