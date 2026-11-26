// START TRANSLATION
async function startTranslation() {
  if (isInspectingFolder || !currentSelectedManga) return;
  const btn = document.getElementById('btn-start');
  const btnCol = document.getElementById('btn-colorize-only');
  btn.disabled = true;
  btn.style.opacity = '0.6';
  if (btnCol) { btnCol.disabled = true; btnCol.style.opacity = '0.6'; }

  document.getElementById('live-progress-section').style.display = 'block';
  document.getElementById('terminal-logs').innerHTML = '<div>[+] Iniciando pipeline profissional de tradução...</div>';
  const eq = document.getElementById('equalizer-anim');
  if (eq) eq.style.display = 'flex';

  updatePlayerCover(currentSelectedManga.first_img, currentSelectedManga.name, "Iniciando motor de OCR e análise...");

  const refInput = document.getElementById('color-reference-path');
  const refVal = refInput ? refInput.value.trim() : '';

  try {
    const payload = {
      path: currentSelectedManga.path,
      first_img: currentSelectedManga.first_img || '',
      ocr_mode: selectedOptions.ocr,
      is_adult: selectedOptions.adult,
      provider: selectedOptions.provider,
      colorize: Boolean(selectedOptions.colorize),
      reference: refVal || null
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
      alert(data.error || "Erro ao iniciar");
      btn.disabled = false;
      btn.style.opacity = '1';
      if (btnCol) { btnCol.disabled = false; btnCol.style.opacity = '1'; }
    }
  } catch (e) {
    alert("Erro de conexão ao iniciar tradução.");
    btn.disabled = false;
    btn.style.opacity = '1';
    if (btnCol) { btnCol.disabled = false; btnCol.style.opacity = '1'; }
  }
}

// START COLORIZE ONLY
async function startColorizeOnly() {
  if (isInspectingFolder || !currentSelectedManga) return;
  const btn = document.getElementById('btn-colorize-only');
  const btnStart = document.getElementById('btn-start');
  if (btn) { btn.disabled = true; btn.style.opacity = '0.6'; }
  if (btnStart) { btnStart.disabled = true; btnStart.style.opacity = '0.6'; }

  document.getElementById('live-progress-section').style.display = 'block';
  document.getElementById('terminal-logs').innerHTML = '<div>[+] Iniciando colorização neural com IA...</div>';
  const eq = document.getElementById('equalizer-anim');
  if (eq) eq.style.display = 'flex';

  updatePlayerCover(currentSelectedManga.first_img, currentSelectedManga.name, "Colorindo páginas com IA...");

  const refInput = document.getElementById('color-reference-path');
  const refVal = refInput ? refInput.value.trim() : '';

  try {
    const payload = {
      path: currentSelectedManga.path,
      first_img: currentSelectedManga.first_img || '',
      colorize: true,
      colorize_only: true,
      reference: refVal || null
    };
    const res = await fetch('/api/colorize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      pollProgress();
    } else {
      alert(data.error || "Erro ao iniciar colorização");
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
      if (btnStart) { btnStart.disabled = false; btnStart.style.opacity = '1'; }
    }
  } catch (e) {
    alert("Erro de conexão ao iniciar colorização.");
    if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    if (btnStart) { btnStart.disabled = false; btnStart.style.opacity = '1'; }
  }
}

// COLORIZE ALREADY TRANSLATED MANGA DIRECTLY FROM LIBRARY
async function colorizeExistingManga(path, cleanName, firstImg) {
  const askRef = prompt(
    `Colorizar mangá já traduzido:\n"${cleanName}"\n\nDeseja indicar o caminho de uma pasta ou imagem COLORIDA como referência de cores?\n(Ex: outro capítulo colorido ou capa. Deixe em branco para colorização automática normal):`,
    ""
  );
  if (askRef === null) return; // cancelado

  currentSelectedManga = {
    path: path,
    name: cleanName,
    clean_name: cleanName,
    first_img: firstImg
  };

  switchTab('translate');

  const refInput = document.getElementById('color-reference-path');
  if (refInput) {
    refInput.value = askRef.trim();
  }
  setOption('colorize', true);

  const selName = document.getElementById('selected-manga-name');
  if (selName) selName.innerText = cleanName;
  const selCover = document.getElementById('selected-cover-img');
  if (selCover && firstImg) {
    selCover.src = `/api/thumb?path=${encodeURIComponent(firstImg)}`;
    selCover.style.display = 'block';
    const pl = document.getElementById('selected-cover-placeholder');
    if (pl) pl.style.display = 'none';
  }
  const selCard = document.getElementById('selection-card');
  if (selCard) selCard.style.display = 'flex';
  const dz = document.getElementById('dropzone');
  if (dz) dz.style.display = 'none';

  await startColorizeOnly();
}

async function togglePauseJob() {
  const btnPause = document.getElementById('btn-pause-job');
  const isPaused = btnPause && btnPause.dataset.state === 'paused';
  const endpoint = isPaused ? '/api/job/resume' : '/api/job/pause';
  if (btnPause) btnPause.disabled = true;
  try {
    const res = await fetch(endpoint, { method: 'POST' });
    const data = await res.json();
    if (!data.success && data.error) {
      alert(data.error);
    }
  } catch (e) {
    alert('Erro ao alterar pausa: ' + e);
  } finally {
    if (btnPause) btnPause.disabled = false;
  }
}

async function stopActiveJob() {
  if (!confirm('Deseja parar a tradução agora?\nO progresso já traduzido será salvo no cache para você continuar depois sem perder cotas.')) {
    return;
  }
  const btnStop = document.getElementById('btn-stop-job');
  if (btnStop) btnStop.disabled = true;
  try {
    const res = await fetch('/api/job/stop', { method: 'POST' });
    const data = await res.json();
    if (!data.success && data.error) {
      alert(data.error);
      if (btnStop) btnStop.disabled = false;
    }
  } catch (e) {
    alert('Erro ao parar tradução: ' + e);
    if (btnStop) btnStop.disabled = false;
  }
}

async function checkActiveJob() {
  try {
    const res = await fetch('/api/progress');
    const data = await res.json();
    if (data && (data.status === 'running' || data.status === 'paused')) {
      document.getElementById('live-progress-section').style.display = 'block';
      const eq = document.getElementById('equalizer-anim');
      if (eq) eq.style.display = data.status === 'paused' ? 'none' : 'flex';
      updatePlayerCover(data.first_img, data.manga_name, data.message);
      pollProgress();
    }
  } catch (e) {
    console.error("Erro ao verificar job ativo:", e);
  }
}
