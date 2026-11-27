// Cotas de IA: quanto ainda dá para traduzir hoje em cada conta (Groq, OpenRouter, Gemini, Ollama).

function quotaTag(text, kind) {
  return `<span class="tag ${kind || ''}">${escapeHtml(text)}</span>`;
}

function quotaMeter(label, valueText, pct, kind) {
  return `
    <div class="q-row"><span>${label}</span><b class="${kind}">${valueText}</b></div>
    <div class="meter-bar"><div class="meter-fill" style="width: ${Math.max(0, Math.min(100, pct))}%; background: var(--${kind === 'err' ? 'redpen' : kind === 'warn' ? 'warn' : 'ok'});"></div></div>`;
}

function renderQuotaWarnings(d) {
  const warnings = Array.isArray(d.runtime_warnings) ? d.runtime_warnings : [];
  if (!warnings.length) return '';
  return `
    <div class="q-alert">
      <h3>Limites atingidos durante a última tradução</h3>
      <ul style="margin: 0; padding-left: 18px;">
        ${warnings.slice(0, 3).map(w => `<li><b>${escapeHtml(w.provider || 'IA')}</b>${w.key ? ` (${escapeHtml(w.key)})` : ''}: ${escapeHtml(w.msg || '')}</li>`).join('')}
      </ul>
    </div>`;
}

function renderGroqModel(mName, mi, isPrimary, deepChecked) {
  const hasReq = mi.rem_req != null && mi.lim_req != null;
  const hasTpd = mi.tpd_limit != null && mi.tpd_remaining != null;
  const ready = !!mi.ok && mi.page_ready !== false;
  const kind = ready ? 'ok' : (mi.is_daily_limit ? 'err' : 'warn');
  let html = `<div class="q-model"><div class="q-row"><span><b>${escapeHtml(formatModelShortName(mName))}</b>${isPrimary ? ' (em uso)' : ''}</span></div>`;
  if (hasReq) html += quotaMeter('Pedidos hoje', `${mi.rem_req} de ${mi.lim_req}`, mi.lim_req > 0 ? (mi.rem_req / mi.lim_req) * 100 : 0, kind);
  else html += `<div class="q-note ${ready ? '' : kind}">${ready ? 'Disponível' : escapeHtml(mi.limit_type || 'Bloqueado')}</div>`;
  if (!hasTpd && ready) {
    html += `<div class="q-note">Tokens por dia: o Groq só informa quando o limite é atingido. "Pedidos hoje" e "Por minuto" cheios não garantem que ainda há tokens no dia.</div>`;
  }
  if (hasTpd) {
    const tk = mi.tpd_exhausted ? 'err' : 'ok';
    html += `<div style="margin-top: 8px;">${quotaMeter(`Tokens hoje ${deepChecked ? '(conferido)' : '(estimado)'}`,
      `${mi.tpd_remaining.toLocaleString('pt-BR')} de ${mi.tpd_limit.toLocaleString('pt-BR')}`,
      mi.tpd_limit > 0 ? (mi.tpd_remaining / mi.tpd_limit) * 100 : 0, tk)}</div>`;
  }
  const notes = [];
  if (mi.rem_tok != null && mi.lim_tok != null) notes.push(`Por minuto: ${mi.rem_tok} de ${mi.lim_tok} tokens${mi.rst_tok ? ` (renova em ${escapeHtml(mi.rst_tok)})` : ''}`);
  if (mi.tpd_exhausted && mi.tpd_reset_sec) notes.push(`Libera em cerca de ${formatDurationPt(mi.tpd_reset_sec)}`);
  if (!ready && mi.msg) notes.push(escapeHtml(mi.msg));
  if (notes.length) html += `<div class="q-note ${ready ? '' : kind}">${notes.join('. ')}</div>`;
  return html + '</div>';
}

function renderGroq(d) {
  const g = d.groq || {};
  const activeM = g.active_model || 'qwen/qwen3.8-27b';
  const fbM = g.fallback_model || 'openai/gpt-oss-120b';
  const keys = g.keys || (g.configured ? [{ index: 1, masked_key: g.masked_key, models: g.models, ok: true }] : []);
  if (!keys.length) {
    return `<section class="q-provider"><h2>Groq ${quotaTag('Sem chave')}</h2><p class="q-empty">Adicione uma chave Groq em Configurações.</p></section>`;
  }
  const ready = g.ready_keys_count != null ? g.ready_keys_count : keys.filter(k => k.ok).length;
  const anyReady = g.any_model_ready_keys != null ? g.any_model_ready_keys : ready;
  const rem = g.total_active_remaining != null ? g.total_active_remaining : (g.total_qwen_remaining || 0);
  const lim = g.total_active_limit != null ? g.total_active_limit : (g.total_qwen_limit || 0);
  const kind = ready > 0 ? 'ok' : (anyReady > 0 ? 'warn' : 'err');
  const sub = ready > 0
    ? `pedidos livres hoje em ${formatModelShortName(activeM)}, somando ${ready} de ${keys.length} chave(s)`
    : (anyReady > 0 ? `${formatModelShortName(activeM)} sem cota; o modelo reserva (GPT-OSS) ainda funciona` : 'todas as chaves sem cota no momento');

  if (ready > 0) updateHeaderAiPill(`Groq Cloud, ${formatModelShortName(activeM)}`, 'ok');
  else if (anyReady > 0) updateHeaderAiPill('Groq Cloud, modelo reserva', 'warn');
  else updateHeaderAiPill('Groq Cloud, sem cota', 'err');

  const cards = keys.map(k => {
    const models = k.models || {};
    const order = [];
    [activeM, fbM, 'qwen/qwen3.8-27b', 'openai/gpt-oss-120b', 'openai/gpt-oss-20b', ...Object.keys(models)].forEach(mn => {
      if (mn && models[mn] && !order.includes(mn)) order.push(mn);
    });
    const prim = models[activeM] || {};
    const allOk = !!prim.ok && prim.page_ready !== false;
    const tag = allOk ? quotaTag('Pronta', 'ok') : (k.ok ? quotaTag('Só o modelo reserva', 'warn') : quotaTag('Sem cota', 'err'));
    return `
      <div class="q-key">
        <div class="q-key-head"><strong>Chave ${k.index || 1}</strong>${tag}</div>
        <div class="mono">${escapeHtml(k.masked_key || 'configurada')}</div>
        ${order.map(mn => renderGroqModel(mn, models[mn] || {}, mn === activeM, g.deep_checked)).join('')}
      </div>`;
  }).join('');

  return `
    <section class="q-provider">
      <h2>Groq</h2>
      <div class="q-pool"><span class="big ${kind}">${ready > 0 ? `${rem} de ${lim || '?'}` : `0 de ${lim || keys.length * 1000}`}</span><span>${escapeHtml(sub)}</span></div>
      <div class="q-keys">${cards}</div>
    </section>`;
}

function renderOpenRouter(d) {
  const keys = (d.openrouter && d.openrouter.keys) || [];
  if (!keys.length) {
    return `<section class="q-provider"><h2>OpenRouter ${quotaTag('Sem chave')}</h2><p class="q-empty">Nenhuma chave OpenRouter cadastrada.</p></section>`;
  }
  const cards = keys.map((k, idx) => {
    const credits = Number(k.credits || 0);
    const paid = credits > 0.01;
    let tag = quotaTag('Gratuita', 'info');
    if (k.err && !k.ok) tag = quotaTag('Chave com erro', 'err');
    else if (k.daily_exhausted) tag = quotaTag('Cota do dia esgotada', 'err');
    else if (paid) tag = quotaTag('Com créditos', 'ok');
    else if (k.upstream_limited_model) tag = quotaTag('Fila cheia', 'warn');

    let body;
    if (k.has_free_quota_details) {
      const fLim = k.free_limit || 50, fUsed = k.free_used || 0;
      const fRem = k.free_rem != null ? k.free_rem : Math.max(0, fLim - fUsed);
      body = quotaMeter('Pedidos grátis hoje', `${fRem} de ${fLim}`, (fRem / fLim) * 100, fRem > 0 ? 'ok' : 'err') +
        `<div class="q-note">${fRem === 0 ? 'Acabou por hoje. Renova às 21h (horário de Brasília).' : `${fRem} pedidos grátis restantes hoje`}</div>`;
    } else {
      body = `<div class="q-note">${paid ? 'Conta com créditos: modelos pagos sem fila.' : 'Conta gratuita: cerca de 50 pedidos por dia nos modelos :free.'}</div>`;
    }
    return `
      <div class="q-key">
        <div class="q-key-head"><strong>Chave ${k.index || (idx + 1)}</strong>${tag}</div>
        <div class="mono">${escapeHtml(k.key || 'sk-or-v1...')}</div>
        <div class="q-model">${body}</div>
        ${k.runtime_warning ? `<div class="q-note warn">${escapeHtml(k.runtime_warning)}</div>` : ''}
        ${k.err && !k.ok ? `<div class="q-note err">${escapeHtml(k.err)}</div>` : ''}
        <div class="q-note">Saldo: <b>US$ ${credits.toFixed(2)}</b> (cerca de R$ ${(credits * 5.8).toFixed(2)})</div>
      </div>`;
  }).join('');
  return `<section class="q-provider"><h2>OpenRouter</h2><div class="q-keys">${cards}</div></section>`;
}

function renderGemini(d) {
  const gem = d.gemini || {};
  const keys = gem.keys || [];
  if (!keys.length) {
    return `<section class="q-provider"><h2>Google Gemini ${quotaTag('Opcional')}</h2><p class="q-empty">Sem chave Gemini: a leitura por imagem usa Groq, OpenRouter ou Ollama.</p></section>`;
  }
  const cards = keys.map((k, idx) => {
    const exh = !!k.quota_exhausted;
    const tag = exh ? quotaTag('Limite atingido', 'warn') : (k.ok ? quotaTag('Pronta', 'ok') : quotaTag('Erro', 'err'));
    const reset = (exh && k.quota_reset_sec > 0) ? `. Libera em cerca de ${formatDurationPt(k.quota_reset_sec)}` : '';
    return `
      <div class="q-key">
        <div class="q-key-head"><strong>Chave ${k.index || (idx + 1)}</strong>${tag}</div>
        <div class="mono">${escapeHtml(k.key || 'AIza...')}</div>
        <div class="q-note ${exh ? 'warn' : ''}">Modelo ${escapeHtml(gem.active_model || 'gemini-2.5-flash')}: ${escapeHtml((k.msg || (k.ok ? 'funcionando' : 'verifique a chave')) + reset)}</div>
      </div>`;
  }).join('');
  return `<section class="q-provider"><h2>Google Gemini</h2><div class="q-keys">${cards}</div></section>`;
}

function renderOllama(d) {
  const ol = d.ollama || { models: [] };
  const online = ol.status === 'online';
  const vis = Array.isArray(ol.vision_models) ? ol.vision_models : [];
  return `
    <section class="q-provider">
      <h2>Ollama (IA local) ${online ? quotaTag('Ligado', 'ok') : quotaTag('Desligado')}</h2>
      <p>${(ol.models || []).length ? `Modelos instalados: ${escapeHtml(ol.models.join(', '))}` : 'Nenhum servidor Ollama respondendo neste computador.'}</p>
      <p>Leitura por imagem: ${vis.length ? escapeHtml(vis.join(', ')) : 'nenhum modelo de visão (ex.: qwen2.5vl:7b, gemma3:12b)'}</p>
    </section>`;
}

async function loadStatus(deep = false) {
  const container = document.getElementById('quota-cards-container');
  container.innerHTML = `<p class="q-empty">${deep ? 'Testando a cota real em cada conta...' : 'Consultando as contas...'}</p>`;
  try {
    const res = await fetch(deep ? '/api/status?deep=1' : '/api/status');
    const d = await res.json();
    container.innerHTML = renderQuotaWarnings(d) + renderGroq(d) + renderOpenRouter(d) + renderGemini(d) + renderOllama(d);
  } catch (e) {
    container.innerHTML = '<p class="q-note err">Não foi possível consultar as cotas. Verifique a conexão e tente Atualizar.</p>';
  }
}
