// Registra inputs assim que a página carregar
document.addEventListener('DOMContentLoaded', () => {
  checkDriveAvailability();

  const isLocal = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
  const foot = document.getElementById('sidebar-foot');
  if (foot) foot.hidden = !isLocal;
  if (!isLocal) {
    const desktopBtn = document.getElementById('btn-open-app-window');
    if (desktopBtn) desktopBtn.style.display = 'none';
  }

  const folderInput = document.getElementById('browser-folder-input');
  if (folderInput) {
    folderInput.addEventListener('change', async (e) => {
      const allFiles = Array.from(e.target.files);
      const imgFiles = allFiles.filter(f => /\.(jpg|jpeg|png|webp|bmp)$/i.test(f.name));
      if (imgFiles.length === 0) {
        alert("Nenhuma imagem válida (JPG, PNG, WEBP) encontrada na pasta selecionada.");
        e.target.value = '';
        return;
      }
      const relPath = imgFiles[0].webkitRelativePath || '';
      const folderName = relPath.split('/')[0] || 'Manga_Upload';
      e.target.value = '';
      await uploadFilesWithProgress(imgFiles, folderName);
    });
  }

  const imagesInput = document.getElementById('browser-images-input');
  if (imagesInput) {
    imagesInput.addEventListener('change', (e) => {
      const allFiles = Array.from(e.target.files);
      const imgFiles = allFiles.filter(f => /\.(jpg|jpeg|png|webp|bmp)$/i.test(f.name));
      e.target.value = '';
      if (imgFiles.length === 0) {
        alert("Nenhuma imagem válida (JPG, PNG, WEBP) selecionada.");
        return;
      }
      imgFiles.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));
      openImagesNameModal(imgFiles);
    });
  }

  const zipInput = document.getElementById('browser-zip-input');
  if (zipInput) {
    zipInput.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      e.target.value = '';
      if (!file) return;
      await uploadZipWithProgress(file);
    });
  }
});

// INIT
window.addEventListener('DOMContentLoaded', () => {
  loadConfig();
  loadLibrary();
  checkActiveJob();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    toggleMobileDrawer(false);
    closeDriveModal();
    closeImagesNameModal();
    closeAuditModal();
  }
});

// Fecha o menu "Mais" dos cartões ao clicar fora dele ou ao escolher uma ação
document.addEventListener('click', (e) => {
  document.querySelectorAll('details.card-more[open]').forEach(d => {
    if (!d.contains(e.target) || e.target.closest('.card-more-menu button')) d.removeAttribute('open');
  });
});
