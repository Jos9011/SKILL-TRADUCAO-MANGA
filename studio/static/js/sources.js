// FOLDER PICKER & UPLOAD MANAGEMENT
function triggerFolderSelect() {
  const isLocalhost = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
  if (isLocalhost) {
    fetch('/api/pick_folder', { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.success && data.path) {
          inspectFolder(data.path);
        } else if (data.is_headless || !data.success) {
          document.getElementById('browser-folder-input').click();
        }
      })
      .catch(() => {
        document.getElementById('browser-folder-input').click();
      });
  } else {
    document.getElementById('browser-folder-input').click();
  }
}

function triggerImagesSelect() {
  document.getElementById('browser-images-input').click();
}

function triggerZipSelect() {
  document.getElementById('browser-zip-input').click();
}

async function checkDriveAvailability() {
  try {
    const res = await fetch('/api/drive_folders');
    const data = await res.json();
    const driveBtn = document.getElementById('btn-drive-pick');
    if (driveBtn && data.available) {
      driveBtn.style.display = 'inline-flex';
    }
  } catch (e) {}
}

let cachedDriveFolders = [];

async function openDrivePicker() {
  const overlay = document.getElementById('drive-picker-modal');
  const listBox = document.getElementById('drive-modal-list');
  const searchInp = document.getElementById('drive-modal-search');
  if (overlay && listBox) {
    if (searchInp) searchInp.value = '';
    listBox.innerHTML = '<div class="drive-empty">Carregando obras do Google Drive...</div>';
    overlay.style.display = 'flex';
    try {
      const res = await fetch('/api/drive_folders');
      const data = await res.json();
      cachedDriveFolders = data.folders || [];
      renderDriveModalList();
    } catch (e) {
      listBox.innerHTML = `<div style="color: var(--red-accent); padding: 14px;">Erro ao consultar Google Drive: ${escapeHtml(String(e))}</div>`;
    }
  }
}

function renderDriveModalList() {
  const listBox = document.getElementById('drive-modal-list');
  const searchInp = document.getElementById('drive-modal-search');
  if (!listBox) return;
  const q = (searchInp ? searchInp.value : '').trim().toLowerCase();
  const filtered = cachedDriveFolders.filter(f => mangaMatchesSearch(f.name, q));
  if (filtered.length === 0) {
    listBox.innerHTML = '<div class="drive-empty">Nenhuma obra com esse nome na pasta MANGAS do Drive. Você pode digitar o caminho abaixo.</div>';
    return;
  }
  listBox.innerHTML = filtered.map(f => `
    <div class="drive-list-item" onclick="selectDriveItem('${escapeQuotes(f.path)}')">
      <div style="min-width: 0; flex: 1;">
        <div class="drive-item-title">${escapeHtml(f.name)}</div>
        <div class="drive-item-path">${escapeHtml(f.path)}</div>
      </div>
      <span class="tag info">${f.pages} págs</span>
    </div>
  `).join('');
}

function selectDriveItem(path) {
  closeDriveModal();
  if (path) inspectFolder(path);
}

function confirmDriveManualPath() {
  const inp = document.getElementById('drive-manual-path-input');
  const val = inp ? inp.value.trim() : '';
  if (!val) return;
  closeDriveModal();
  inspectFolder(val);
}

function closeDriveModal() {
  const overlay = document.getElementById('drive-picker-modal');
  if (overlay) overlay.style.display = 'none';
}

function pickFolder() {
  triggerFolderSelect();
}

let pendingImageUploadFiles = null;

function openImagesNameModal(imgFiles) {
  pendingImageUploadFiles = imgFiles;
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
  const modal = document.getElementById('images-name-modal');
  const inp = document.getElementById('images-folder-name-input');
  const countBadge = document.getElementById('images-modal-count');
  if (!modal || !inp) {
    uploadFilesWithProgress(imgFiles, `Manga_${stamp}`);
    return;
  }
  if (countBadge) countBadge.innerText = `${imgFiles.length} página${imgFiles.length > 1 ? 's' : ''}`;
  inp.value = `Manga_${stamp}`;
  modal.style.display = 'flex';
  setTimeout(() => { inp.focus(); inp.select(); }, 50);
}

function closeImagesNameModal() {
  const modal = document.getElementById('images-name-modal');
  if (modal) modal.style.display = 'none';
  pendingImageUploadFiles = null;
}

async function confirmImagesNameModal() {
  const files = pendingImageUploadFiles;
  const inp = document.getElementById('images-folder-name-input');
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
  const folderName = (inp ? inp.value.trim() : '') || `Manga_${stamp}`;
  closeImagesNameModal();
  if (files && files.length > 0) {
    await uploadFilesWithProgress(files, folderName);
  }
}
