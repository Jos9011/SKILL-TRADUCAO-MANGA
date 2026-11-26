// LIVE PROGRESS POLLER
let pollInterval = null;

function pollProgress() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/progress');
      const data = await res.json();

      // Atualiza capa e textos no Player e no Card Ativo
      const coverImg = data.first_img || (currentSelectedManga ? currentSelectedManga.first_img : '');
      if (coverImg) {
        updatePlayerCover(coverImg, data.manga_name, data.message);
      } else {
        if (data.manga_name) {
          document.getElementById('player-manga-title').innerText = data.manga_name;
          const lTitle = document.getElementById('live-manga-title');
          if (lTitle) lTitle.innerText = data.manga_name;
        }
        if (data.message) {
          document.getElementById('player-manga-stage').innerText = data.message;
          const lDesc = document.getElementById('live-status-desc');
          if (lDesc) lDesc.innerText = data.message;
        }
      }

      // Atualiza badge de etapa e provedor
      const liveStage = document.getElementById('live-stage-badge');
      if (liveStage && data.stage) {
        const stageNames = { ocr: 'Lendo o texto', translation: 'Traduzindo', translate: 'Traduzindo', diagram: 'Limpando e escrevendo', colorize: 'Colorindo', done: 'Pronto', cancelled: 'Parado' };
        liveStage.innerText = stageNames[data.stage] || data.stage;
      }
      const liveEngine = document.getElementById('live-engine-label');
      if (liveEngine) {
        if (data.stage === 'colorize') {
          liveEngine.innerText = 'Colorizador Neural IA (ONNX / GPU)';
        } else {
          liveEngine.innerText = selectedOptions.provider === 'groq' ? `Groq Cloud (${formatModelShortName(currentConfig.groq_model || 'qwen/qwen3.8-27b')})` :
                                 selectedOptions.provider === 'openrouter' ? 'OpenRouter Cloud' : 'IA Local GPU (Ollama)';
        }
      }

      // Atualiza barra principal
      document.getElementById('main-progress-bar').style.width = `${data.percentage}%`;
      document.getElementById('main-progress-pct').innerText = `${data.percentage}%`;
      document.getElementById('progress-status-badge').innerText = data.message;

      // Atualiza player bar
      document.getElementById('player-current-page').innerText = data.current_page;
      document.getElementById('player-total-pages').innerText = data.total_pages;
      document.getElementById('player-progress-fill').style.width = `${data.percentage}%`;

      // Atualiza logs
      const logBox = document.getElementById('terminal-logs');
      if (data.logs && data.logs.length) {
        logBox.innerHTML = data.logs.map(l => `<div>${escapeHtml(l)}</div>`).join('');
        logBox.scrollTop = logBox.scrollHeight;
      }

      const jobCtrlBox = document.getElementById('job-control-actions');
      const btnPause = document.getElementById('btn-pause-job');
      const btnStop = document.getElementById('btn-stop-job');
      const eqEl = document.getElementById('equalizer-anim');

      if (data.status === 'running' || data.status === 'paused') {
        if (jobCtrlBox) jobCtrlBox.style.display = 'flex';
        if (btnPause) {
          btnPause.dataset.state = data.status;
          btnPause.disabled = false;
          btnPause.innerText = data.status === 'paused' ? 'Continuar' : 'Pausar';
        }
        if (btnStop) btnStop.disabled = false;
        if (eqEl) eqEl.style.display = data.status === 'paused' ? 'none' : 'flex';
      }

      if (data.status === 'done') {
        clearInterval(pollInterval);
        if (jobCtrlBox) jobCtrlBox.style.display = 'none';
        document.getElementById('btn-start').disabled = false;
        document.getElementById('btn-start').style.opacity = '1';
        const btnCol = document.getElementById('btn-colorize-only');
        if (btnCol) { btnCol.disabled = false; btnCol.style.opacity = '1'; }
        activeResult = data.result;
        showActionButtons(data.result);
        loadLibrary();
        if (eqEl) eqEl.style.display = 'none';
      } else if (data.status === 'cancelled') {
        clearInterval(pollInterval);
        if (jobCtrlBox) jobCtrlBox.style.display = 'none';
        document.getElementById('btn-start').disabled = false;
        document.getElementById('btn-start').style.opacity = '1';
        const btnCol = document.getElementById('btn-colorize-only');
        if (btnCol) { btnCol.disabled = false; btnCol.style.opacity = '1'; }
        if (eqEl) eqEl.style.display = 'none';
        loadLibrary();
      } else if (data.status === 'error') {
        clearInterval(pollInterval);
        if (jobCtrlBox) jobCtrlBox.style.display = 'none';
        document.getElementById('btn-start').disabled = false;
        document.getElementById('btn-start').style.opacity = '1';
        const btnCol = document.getElementById('btn-colorize-only');
        if (btnCol) { btnCol.disabled = false; btnCol.style.opacity = '1'; }
        if (eqEl) eqEl.style.display = 'none';
        alert(`Erro no processamento: ${data.error}`);
      }
    } catch (e) {
      console.error("Poll error:", e);
    }
  }, 700);
}

function showActionButtons(result) {
  if (!result) return;
  markPlayerActive();
  const btnReader = document.getElementById('player-btn-reader');
  const btnZip = document.getElementById('player-btn-zip');
  const btnCbz = document.getElementById('player-btn-cbz');
  const btnFolder = document.getElementById('player-btn-folder');
  if (btnReader) btnReader.style.display = 'inline-flex';
  if (btnZip) btnZip.style.display = 'inline-flex';
  if (btnCbz) btnCbz.style.display = 'inline-flex';
  if (btnFolder) btnFolder.style.display = 'inline-flex';
}

function openActiveReader() {
  if (activeResult) {
    if (activeResult.reader_url) {
      window.open(activeResult.reader_url, '_blank');
    } else if (activeResult.id) {
      window.open('/read/' + activeResult.id + '/', '_blank');
    } else if (activeResult.output_dir || activeResult.reader_path) {
      const p = activeResult.output_dir || activeResult.reader_path;
      window.open('/api/reader?path=' + encodeURIComponent(p), '_blank');
    }
    if (activeResult.reader_path) {
      fetch('/api/open_reader', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: activeResult.reader_path })
      }).catch(() => {});
    }
  }
}

function downloadActiveZip() {
  if (activeResult && (activeResult.output_dir || activeResult.reader_path)) {
    downloadFolderZip(activeResult.output_dir || activeResult.reader_path);
  }
}

function downloadActiveCbz() {
  if (activeResult) {
    const p = activeResult.cbz_path || activeResult.output_dir;
    downloadCbz(p);
  }
}

function openActiveCbz() {
  downloadActiveCbz();
}

function openActiveFolder() {
  if (activeResult && activeResult.output_dir) {
    fetch('/api/open_folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: activeResult.output_dir })
    });
  }
}

function downloadFolderZip(folderPath) {
  if (!folderPath) return;
  const link = document.createElement('a');
  link.href = '/api/download_folder?path=' + encodeURIComponent(folderPath);
  link.setAttribute('download', '');
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function downloadCbz(cbzPath) {
  if (!cbzPath) return;
  const link = document.createElement('a');
  link.href = '/api/download_cbz?path=' + encodeURIComponent(cbzPath);
  link.setAttribute('download', '');
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

// EXTRACT ALL ARCHIVES
async function extractAllArchives() {
  const btn = document.getElementById('btn-extract-all-archives');
  const originalText = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = 'Descompactando...';
  }
  try {
    const res = await fetch('/api/drive/extract_all', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    const data = await res.json();
    if (data.success) {
      alert(data.message || `${data.count} obra(s) descompactada(s) com sucesso!`);
      await loadLibrary();
    } else {
      alert('Erro ao descompactar: ' + (data.error || 'Erro desconhecido'));
    }
  } catch (e) {
    alert('Erro de conexão ao descompactar: ' + e);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }
}
