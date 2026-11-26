function updatePlayerCover(firstImg, mangaName, statusText) {
  markPlayerActive();
  if (firstImg) {
    const thumbUrl = `/api/thumb?path=${encodeURIComponent(firstImg)}`;
    const pImg = document.getElementById('player-img');
    if (pImg) {
      pImg.src = thumbUrl;
      pImg.style.display = 'block';
    }
    const pPh = document.getElementById('player-placeholder-icon');
    if (pPh) pPh.style.display = 'none';

    const lImg = document.getElementById('live-cover-img');
    if (lImg) {
      lImg.src = thumbUrl;
      lImg.style.display = 'block';
    }
    const lPh = document.getElementById('live-cover-placeholder');
    if (lPh) lPh.style.display = 'none';
  }
  if (mangaName) {
    const pTitle = document.getElementById('player-manga-title');
    if (pTitle) pTitle.innerText = mangaName;
    const lTitle = document.getElementById('live-manga-title');
    if (lTitle) lTitle.innerText = mangaName;
  }
  if (statusText) {
    const pStage = document.getElementById('player-manga-stage');
    if (pStage) pStage.innerText = statusText;
    const lDesc = document.getElementById('live-status-desc');
    if (lDesc) lDesc.innerText = statusText;
  }
}

let inspectRequestSeq = 0;

let isInspectingFolder = false;

async function inspectFolder(path) {
  const reqId = ++inspectRequestSeq;
  isInspectingFolder = true;
  currentSelectedManga = null;
  const startBtn = document.getElementById('btn-start');
  if (startBtn) {
    startBtn.disabled = true;
    startBtn.style.opacity = '0.5';
  }
  const selCard = document.getElementById('selection-card');
  const dz = document.getElementById('dropzone');
  if (selCard) selCard.style.display = 'none';
  if (dz) dz.style.display = 'block';
  const langBadge = document.getElementById('selected-lang-badge');
  if (langBadge) langBadge.innerText = 'Detectando idioma...';

  const isArchive = /\.(zip|cbz|pdf)$/i.test(path || '');
  const pBox = document.getElementById('upload-progress-box');
  const pText = document.getElementById('upload-status-text');
  const pFill = document.getElementById('upload-progress-fill');
  const pPct = document.getElementById('upload-pct-text');
  if (pBox) {
    pBox.style.display = 'block';
    if (pText) pText.innerText = isArchive ? 'Extraindo páginas do arquivo... Por favor, aguarde.' : 'Analisando obra e detectando idioma (OCR)...';
    if (pFill) pFill.style.width = '100%';
    if (pPct) pPct.innerText = '';
  }
  try {
    const res = await fetch('/api/inspect_folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path })
    });
    const data = await res.json();
    if (reqId !== inspectRequestSeq) return;
    isInspectingFolder = false;
    if (pBox) pBox.style.display = 'none';
    if (data.valid) {
      currentSelectedManga = data;
      if (dz) dz.style.display = 'none';
      if (selCard) selCard.style.display = 'flex';

      document.getElementById('selected-manga-title').innerText = data.name;
      document.getElementById('selected-pages-badge').innerText = `${data.pages} páginas`;
      if (langBadge) langBadge.innerText = `Leitura: ${data.detected_label}`;
      document.getElementById('selected-path-badge').innerText = data.path;
      document.getElementById('manga-preview-img').src = `/api/thumb?path=${encodeURIComponent(data.first_img)}`;

      // Atualiza capa no player e card ao vivo
      updatePlayerCover(data.first_img, data.name, `${data.pages} páginas, pronto para traduzir`);

      // Seta valor sugerido de OCR somente após inspeção validada
      setOption('ocr', data.detected_engine || 'auto');
      if (startBtn) {
        startBtn.disabled = false;
        startBtn.style.opacity = '1';
      }
    } else {
      if (startBtn) {
        startBtn.disabled = false;
        startBtn.style.opacity = '1';
      }
      alert(data.error || "Pasta inválida");
    }
  } catch (e) {
    if (reqId !== inspectRequestSeq) return;
    isInspectingFolder = false;
    if (pBox) pBox.style.display = 'none';
    if (startBtn) {
      startBtn.disabled = false;
      startBtn.style.opacity = '1';
    }
    console.error("Erro ao inspecionar pasta:", e);
  }
}

function resetSelection() {
  inspectRequestSeq++;
  isInspectingFolder = false;
  currentSelectedManga = null;
  const pBox = document.getElementById('upload-progress-box');
  if (pBox) pBox.style.display = 'none';
  const startBtn = document.getElementById('btn-start');
  if (startBtn) {
    startBtn.disabled = false;
    startBtn.style.opacity = '1';
  }
  document.getElementById('selection-card').style.display = 'none';
  document.getElementById('dropzone').style.display = 'block';
}

async function traverseFileTree(item, fileList) {
  if (item.isFile) {
    const file = await new Promise((res) => item.file(res));
    if (file && /\.(jpg|jpeg|png|webp|bmp)$/i.test(file.name)) {
      fileList.push(file);
    }
  } else if (item.isDirectory) {
    const dirReader = item.createReader();
    const entries = await new Promise((res) => dirReader.readEntries(res));
    for (const entry of entries) {
      await traverseFileTree(entry, fileList);
    }
  }
}

// DRAG AND DROP
const dropzone = document.getElementById('dropzone');

dropzone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropzone.classList.add('dragover');
});

dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

dropzone.addEventListener('drop', async (e) => {
  e.preventDefault();
  dropzone.classList.remove('dragover');

  const items = e.dataTransfer.items;
  if (items && items.length > 0) {
    const files = [];
    let zipFile = null;
    let detectedFolderName = 'Manga_Arrastado';

    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry ? items[i].webkitGetAsEntry() : null;
      if (entry) {
        if (entry.isDirectory) {
          detectedFolderName = entry.name;
          await traverseFileTree(entry, files);
        } else if (entry.isFile) {
          const f = items[i].getAsFile();
          if (f && /\.(zip|cbz|pdf)$/i.test(f.name)) {
            zipFile = f;
            break;
          } else if (f && /\.(jpg|jpeg|png|webp|bmp)$/i.test(f.name)) {
            files.push(f);
          }
        }
      } else {
        const f = items[i].getAsFile();
        if (f) {
          if (/\.(zip|cbz|pdf)$/i.test(f.name)) { zipFile = f; break; }
          else if (/\.(jpg|jpeg|png|webp|bmp)$/i.test(f.name)) files.push(f);
        }
      }
    }

    if (zipFile) {
      await uploadZipWithProgress(zipFile);
      return;
    }
    if (files.length > 0) {
      await uploadFilesWithProgress(files, detectedFolderName);
      return;
    }
  }

  triggerFolderSelect();
});

// OPTIONS TOGGLE
function setOption(type, value) {
  selectedOptions[type] = value;
  const selectorId = `${type}-selector`;
  const container = document.getElementById(selectorId);
  if (container) {
    container.querySelectorAll('.pill-btn').forEach(btn => btn.classList.remove('active'));
    const index = type === 'ocr' ? ['auto', 'rapidocr', 'mokuro', 'korean', 'ai_vision'].indexOf(value) :
                  type === 'adult' ? (value ? 0 : 1) :
                  type === 'colorize' ? (value ? 1 : 0) :
                  ['groq', 'ollama', 'openrouter'].indexOf(value);
    if (index >= 0 && container.children[index]) {
      container.children[index].classList.add('active');
    }
  }
  if (type === 'colorize') {
    const refBox = document.getElementById('color-reference-container');
    if (refBox) refBox.style.display = value ? 'block' : 'none';
  }
}
