async function uploadFilesWithProgress(files, folderName) {
  const pBox = document.getElementById('upload-progress-box');
  const pFill = document.getElementById('upload-progress-fill');
  const pText = document.getElementById('upload-status-text');
  const pPct = document.getElementById('upload-pct-text');

  pBox.style.display = 'block';
  pFill.style.width = '0%';
  pPct.innerText = '0%';

  // Envia em lotes de 12 imagens para máxima estabilidade (evita timeout e limite de 100MB do Cloudflare)
  const BATCH_SIZE = 12;
  const totalBatches = Math.ceil(files.length / BATCH_SIZE);
  let lastResult = null;

  try {
    for (let b = 0; b < totalBatches; b++) {
      const start = b * BATCH_SIZE;
      const end = Math.min(files.length, start + BATCH_SIZE);
      const chunk = files.slice(start, end);
      const isLast = (b === totalBatches - 1);

      pText.innerText = `Enviando ${files.length} imagens (lote ${b + 1} de ${totalBatches})...`;
      const basePct = Math.round((start / files.length) * 100);
      pFill.style.width = basePct + '%';
      pPct.innerText = basePct + '%';

      const formData = new FormData();
      formData.append('folder_name', folderName);
      formData.append('is_last', isLast ? 'true' : 'false');
      chunk.forEach(f => formData.append('files[]', f, f.name));

      const res = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/upload', true);
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const chunkFraction = (e.loaded / e.total);
            const overallPct = Math.round(((start + (chunk.length * chunkFraction)) / files.length) * 100);
            pFill.style.width = Math.min(overallPct, 99) + '%';
            pPct.innerText = Math.min(overallPct, 99) + '%';
          }
        };
        xhr.onload = () => {
          if (xhr.status === 200) {
            try {
              resolve(JSON.parse(xhr.responseText));
            } catch (e) {
              reject(new Error("Resposta inválida do servidor"));
            }
          } else {
            let detail = "";
            try {
              const errJson = JSON.parse(xhr.responseText);
              detail = errJson.error || errJson.message || "";
            } catch (e) {}
            reject(new Error(`Erro no envio (HTTP ${xhr.status})${detail ? ': ' + detail : ''}`));
          }
        };
        xhr.onerror = () => reject(new Error("Falha na conexão ao enviar arquivos para o servidor."));
        xhr.send(formData);
      });

      lastResult = res;
    }

    pFill.style.width = '100%';
    pPct.innerText = '100%';
    pBox.style.display = 'none';

    if (lastResult && lastResult.path) {
      inspectFolder(lastResult.path);
    }
  } catch (err) {
    pBox.style.display = 'none';
    alert(err.message || "Erro durante o envio dos arquivos.");
  }
}

function uploadZipWithProgress(file) {
  return new Promise((resolve, reject) => {
    const pBox = document.getElementById('upload-progress-box');
    const pFill = document.getElementById('upload-progress-fill');
    const pText = document.getElementById('upload-status-text');
    const pPct = document.getElementById('upload-pct-text');

    pBox.style.display = 'block';
    pText.innerText = `Enviando arquivo ${file.name}...`;
    pFill.style.width = '0%';
    pPct.innerText = '0%';

    const formData = new FormData();
    formData.append('zip_file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload', true);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        pFill.style.width = pct + '%';
        pPct.innerText = pct + '%';
        if (pct >= 100) {
          pText.innerText = `Extraindo páginas de ${file.name} no servidor...`;
        }
      }
    };

    xhr.onload = () => {
      pBox.style.display = 'none';
      if (xhr.status === 200) {
        try {
          const res = JSON.parse(xhr.responseText);
          if (res.success && res.path) {
            inspectFolder(res.path);
            resolve(res);
          } else {
            alert("Erro ao descompactar mangá: " + (res.error || ""));
            reject(res);
          }
        } catch (err) {
          alert("Resposta inválida do servidor.");
          reject(err);
        }
      } else {
        let detail = "";
        try {
          const errJson = JSON.parse(xhr.responseText);
          detail = errJson.error || errJson.message || "";
        } catch (e) {}
        alert(`Erro no envio do ZIP (HTTP ${xhr.status})${detail ? ': ' + detail : ''}`);
        reject(xhr);
      }
    };

    xhr.onerror = () => {
      pBox.style.display = 'none';
      alert("Falha de conexão ao enviar ZIP.");
      reject();
    };

    xhr.send(formData);
  });
}
