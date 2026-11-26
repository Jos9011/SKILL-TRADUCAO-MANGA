// LIBRARY
async function loadLibrary() {
  try {
    const res = await fetch('/api/library');
    libraryData = await res.json();
    renderLibraryGrid();
    renderSidebarRecents();
    renderQuickPicks();
  } catch (e) {
    console.error("Erro ao carregar biblioteca:", e);
  }
}

// Capa + título + "Ler"; as outras ações ficam no menu "Mais" (details nativo)
function libraryCardTags(m) {
  const tags = [];
  if (m.is_drive) tags.push('<span class="tag">Drive</span>');
  if (m.is_archive) tags.push(`<span class="tag">${escapeHtml(m.archive_type || 'ZIP')}</span>`);
  return tags.length ? `<div class="card-tags">${tags.join('')}</div>` : '';
}

function translatedCard(m) {
  const p = escapeQuotes(m.path), name = escapeQuotes(m.clean_name), img = escapeQuotes(m.first_img);
  const read = `openReader('${p}', '${escapeQuotes(m.reader_url)}'); updatePlayerCover('${img}', '${name}', '${m.pages} páginas, traduzido');`;
  return `
    <div class="manga-card" onclick="${read}">
      <div class="card-thumb"><img src="/api/thumb?path=${encodeURIComponent(m.first_img)}" loading="lazy" alt="">${libraryCardTags(m)}</div>
      <div class="card-title" title="${escapeHtml(m.clean_name)}">${escapeHtml(m.clean_name)}</div>
      <div class="card-subtitle">${m.pages} páginas</div>
      <div class="card-actions-row" onclick="event.stopPropagation()">
        <button class="card-action-btn primary" onclick="${read}">Ler</button>
        <details class="card-more">
          <summary class="card-action-btn" title="Mais ações">Mais</summary>
          <div class="card-more-menu">
            <button onclick="downloadCbz('${escapeQuotes(m.cbz_path || m.path)}')">Baixar CBZ</button>
            <button onclick="downloadFolderZip('${p}')">Baixar ZIP</button>
            <button onclick="colorizeExistingManga('${p}', '${name}', '${img}')">Colorir páginas</button>
            <button onclick="openAuditModal('${p}', '${name}')">Avaliar tradução</button>
            <hr>
            <button class="danger" onclick="confirmDeleteManga('${p}', '${name}')">Excluir</button>
          </div>
        </details>
      </div>
    </div>`;
}

function rawCard(m) {
  const p = escapeQuotes(m.path);
  const go = `inspectFolder('${p}'); switchTab('translate');`;
  return `
    <div class="manga-card" onclick="${go}">
      <div class="card-thumb"><img src="/api/thumb?path=${encodeURIComponent(m.first_img)}" loading="lazy" alt="">${libraryCardTags(m)}</div>
      <div class="card-title" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</div>
      <div class="card-subtitle">${m.pages} páginas${m.is_archive ? ', compactado' : ''}</div>
      <div class="card-actions-row" onclick="event.stopPropagation()">
        <button class="card-action-btn primary" onclick="${go}">Traduzir</button>
        <details class="card-more">
          <summary class="card-action-btn" title="Mais ações">Mais</summary>
          <div class="card-more-menu">
            <button class="danger" onclick="confirmDeleteManga('${p}', '${escapeQuotes(m.name)}')">Excluir</button>
          </div>
        </details>
      </div>
    </div>`;
}

function renderLibraryGrid() {
  const q = (document.getElementById('library-search')?.value || '').trim();
  const grid = document.getElementById('library-grid');
  const rawGrid = document.getElementById('raw-library-grid');

  const filteredTrans = libraryData.translated.filter(m => mangaMatchesSearch(m.name, q) || mangaMatchesSearch(m.clean_name, q));
  grid.innerHTML = filteredTrans.map(translatedCard).join('') ||
    `<div class="library-empty">${q ? `Nenhuma obra traduzida encontrada para "${escapeHtml(q)}".` : 'Nenhuma obra traduzida ainda. Traduza um capítulo e ele aparece aqui.'}</div>`;

  const filteredRaw = libraryData.raw.filter(m => mangaMatchesSearch(m.name, q));
  rawGrid.innerHTML = filteredRaw.map(rawCard).join('') ||
    `<div class="library-empty">${q ? `Nenhuma obra original encontrada para "${escapeHtml(q)}".` : 'Nenhum capítulo na pasta de originais. Escolha a pasta em Configurações ou envie um capítulo na aba Traduzir.'}</div>`;

  const info = document.getElementById('library-search-info');
  if (info) {
    info.textContent = q
      ? `${filteredTrans.length} de ${libraryData.translated.length} traduzidos e ${filteredRaw.length} de ${libraryData.raw.length} originais`
      : '';
  }
  const clearBtn = document.getElementById('library-search-clear');
  if (clearBtn) clearBtn.classList.toggle('visible', !!q);
}

// Busca de mangás: ignora maiúsculas, acentos e pontuação; aceita palavras em qualquer ordem
// ("gal kuro" e "toshiue ch1" encontram "Toshiue no Kuro Gal ... Ch.1").
function normalizeMangaSearch(text) {
  return String(text || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+/g, ' ')
    .trim();
}

function mangaMatchesSearch(name, query) {
  const q = normalizeMangaSearch(query);
  if (!q) return true;
  const n = normalizeMangaSearch(name);
  const compact = n.replace(/ /g, '');
  return q.split(' ').every(t => n.includes(t) || compact.includes(t));
}

function clearLibrarySearch() {
  const inp = document.getElementById('library-search');
  if (!inp) return;
  inp.value = '';
  renderLibraryGrid();
  inp.focus();
}

function renderSidebarRecents() {
  const rec = document.getElementById('sidebar-recents');
  rec.innerHTML = libraryData.translated.slice(0, 10).map(m => `
    <div class="recent-item" onclick="toggleMobileDrawer(false); openReader('${escapeQuotes(m.path)}', '${escapeQuotes(m.reader_url)}'); updatePlayerCover('${escapeQuotes(m.first_img)}', '${escapeQuotes(m.clean_name)}', '${m.pages} páginas, traduzido');" title="${escapeHtml(m.clean_name)}">${escapeHtml(m.clean_name)}</div>
  `).join('') || '<div class="recent-item" style="cursor: default;">Nada traduzido ainda</div>';
}

// Tela Traduzir: até 6 capítulos da pasta de originais para começar com um clique
function renderQuickPicks() {
  const box = document.getElementById('quick-picks');
  const sec = document.getElementById('quick-picks-section');
  if (!box || !sec) return;
  const items = (libraryData.raw || []).slice(0, 6);
  sec.hidden = items.length === 0;
  box.innerHTML = items.map(m => `
    <div class="manga-card" onclick="inspectFolder('${escapeQuotes(m.path)}')" title="${escapeHtml(m.name)}">
      <div class="card-thumb"><img src="/api/thumb?path=${encodeURIComponent(m.first_img)}" loading="lazy" alt="">${libraryCardTags(m)}</div>
      <div class="card-title">${escapeHtml(m.name)}</div>
      <div class="card-subtitle">${m.pages} páginas</div>
    </div>`).join('');
}

function filterLibrary() {
  renderLibraryGrid();
}

function openReader(path, readerUrl) {
  if (readerUrl) {
    window.open(readerUrl, '_blank');
    return;
  }
  if (!path) return;
  window.open('/api/reader?path=' + encodeURIComponent(path), '_blank');
  fetch('/api/open_reader', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: path })
  }).catch(() => {});
}

// CONFIRM AND DELETE MANGA
function confirmDeleteManga(path, name) {
  if (!path) return;
  if (!confirm(`Deseja realmente excluir permanentemente o mangá "${name}"?\nEsta ação apagará todos os arquivos desta obra.`)) {
    return;
  }
  fetch('/api/delete_manga', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: path })
  })
  .then(r => r.json())
  .then(data => {
    if (data.success) {
      alert(`"${name}" foi excluído.`);
      loadLibrary();
      if (currentSelectedManga && currentSelectedManga.path === path) {
        resetSelection();
      }
    } else {
      alert('Erro ao excluir mangá: ' + (data.error || 'Erro desconhecido.'));
    }
  })
  .catch(err => alert('Erro de conexão ao excluir: ' + err));
}

function deleteSelectedManga() {
  if (!currentSelectedManga || !currentSelectedManga.path) return;
  confirmDeleteManga(currentSelectedManga.path, currentSelectedManga.name || 'Obra Selecionada');
}
