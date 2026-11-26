// RULES & GLOSSARY
async function loadRules() {
  const endpoint = currentRuleTab === 'aprendizado' ? '/api/aprendizado' : '/api/glossary';
  try {
    const res = await fetch(endpoint);
    const data = await res.json();
    const editor = document.getElementById('rules-editor');
    if (currentRuleTab === 'aprendizado') {
      editor.value = data.content || '';
    } else {
      editor.value = JSON.stringify(data.data || {}, null, 2);
    }
  } catch (e) {
    console.error("Erro ao carregar regras:", e);
  }
}

function switchRulesEditor(tab) {
  currentRuleTab = tab;
  document.getElementById('tab-rule-aprendizado').classList.toggle('active', tab === 'aprendizado');
  document.getElementById('tab-rule-glossary').classList.toggle('active', tab === 'glossary');
  loadRules();
}

async function saveRules() {
  const editor = document.getElementById('rules-editor');
  const endpoint = currentRuleTab === 'aprendizado' ? '/api/aprendizado' : '/api/glossary';
  try {
    let body = {};
    if (currentRuleTab === 'aprendizado') {
      body = { content: editor.value };
    } else {
      body = { data: JSON.parse(editor.value) };
    }
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (data.success) {
      alert("Salvo com sucesso!");
    } else {
      alert("Erro ao salvar: " + (data.error || ""));
    }
  } catch (e) {
    alert("Erro de formato ou conexão ao salvar.");
  }
}

// SISTEMA DE AVALIAÇÃO & AUTO-AUDITORIA DA IA
let currentAuditPath = '';

let currentAuditRating = 3;

function openAuditModal(path, cleanName) {
  currentAuditPath = path;
  document.getElementById('audit-manga-title').innerText = 'Avaliar: ' + cleanName;
  document.getElementById('audit-feedback-input').value = '';
  document.getElementById('audit-results-box').style.display = 'none';
  setAuditRating(3);
  const modal = document.getElementById('audit-modal-overlay');
  modal.style.display = 'flex';
}

function closeAuditModal() {
  document.getElementById('audit-modal-overlay').style.display = 'none';
}

function setAuditRating(val) {
  currentAuditRating = val;
  const stars = document.querySelectorAll('#audit-stars-row .star-btn');
  stars.forEach((s, idx) => {
    s.classList.toggle('on', idx < val);
  });
  const desc = document.getElementById('audit-rating-desc');
  const labels = ['', '1 estrela: muito ruim (a IA vai revisar a fundo)', '2 estrelas: ruim (a IA vai revisar a fundo)',
    '3 estrelas: razoável (a IA vai revisar)', '4 estrelas: boa (revisão opcional)', '5 estrelas: ótima'];
  desc.innerText = labels[val] || labels[5];
}

async function submitAuditRating() {
  if (!currentAuditPath) return;
  const btn = document.getElementById('btn-run-audit');
  btn.disabled = true;
  btn.innerHTML = 'Revisando a tradução...';
  const comment = document.getElementById('audit-feedback-input').value.trim();

  try {
    const res = await fetch('/api/rate_manga', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: currentAuditPath,
        rating: currentAuditRating,
        comment: comment,
        force_audit: true
      })
    });
    const data = await res.json();
    btn.disabled = false;
    btn.innerHTML = 'Enviar nota e revisar';

    if (data.success && data.audit_report && data.audit_report.success) {
      displayAuditResults(data.audit_report);
    } else {
      alert('Avaliação registrada! ' + (data.audit_report?.error || 'Nenhum erro crítico detectado no cache.'));
    }
  } catch (e) {
    btn.disabled = false;
    btn.innerHTML = 'Enviar nota e revisar';
    alert('Erro ao enviar avaliação: ' + e);
  }
}

function displayAuditResults(rep) {
  const box = document.getElementById('audit-results-box');
  box.style.display = 'block';

  const badge = document.getElementById('audit-health-badge');
  badge.innerText = `Saúde: ${rep.health_score}%`;
  badge.className = 'tag ' + (rep.health_score >= 80 ? 'ok' : rep.health_score >= 60 ? 'warn' : 'err');

  document.getElementById('audit-categories-row').innerHTML = Object.entries(rep.categories || {})
    .map(([k, count]) => `<span class="tag">${escapeHtml(k)}: <b>${count}</b></span>`).join('');

  const issuesList = document.getElementById('audit-issues-list');
  if (rep.issues_detail && rep.issues_detail.length > 0) {
    issuesList.innerHTML = rep.issues_detail.map(iss => `
      <div class="audit-issue">
        <div class="why">${escapeHtml(iss.category)}: ${escapeHtml(iss.reason)}</div>
        <div><del>${escapeHtml(iss.current_translation)}</del></div>
        <div><ins>${escapeHtml(iss.suggested_correction)}</ins></div>
      </div>
    `).join('');
  } else {
    issuesList.innerHTML = '<div class="q-note">Nenhum problema de tradução ou de OCR encontrado.</div>';
  }
}

async function retranslateAfterAudit() {
  if (!currentAuditPath) return;
  if (!confirm('Deseja retraduzir este mangá agora com as correções aplicadas pela IA?\\nO processo levará apenas alguns segundos pois reutilizará os balões do OCR!')) {
    return;
  }
  closeAuditModal();
  switchTab('translate');

  // Dispara job de retradução usando o cache corrigido
  const btn = document.getElementById('btn-start');
  if (btn) {
    btn.disabled = true;
    btn.style.opacity = '0.6';
  }
  document.getElementById('live-progress-section').style.display = 'block';
  document.getElementById('terminal-logs').innerHTML = '<div>[+] Retraduzindo mangá com correções da auto-auditoria da IA...</div>';
  const eq = document.getElementById('equalizer-anim');
  if (eq) eq.style.display = 'flex';

  try {
    const payload = {
      path: currentAuditPath,
      ocr_mode: 'auto',
      is_adult: true,
      force_ocr: false,
      retranslate: false,
      provider: 'auto'
    };
    const res = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      pollProgress();
    } else {
      alert(data.error || 'Erro ao iniciar retradução');
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    }
  } catch (e) {
    alert('Erro ao iniciar retradução: ' + e);
    if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
  }
}
