# -*- coding: utf-8 -*-
r"""
Auto Manga Translator & Typesetter (PT-BR)
Salva automaticamente em: C:\Users\ja329\OneDrive\Documentos\MANGAS

Suporta:
- Arrastar e soltar pastas no .bat
- OCR automático com RapidOCR
- Detecção automática de idioma (Japonês ou Inglês -> PT-BR)
- Limpeza inteligente de balões (fill branco + OpenCV inpainting)
- Diagramação com Comic Sans MS Bold e outline de contraste
- Geração de leitor web interativo (leitor.html)
"""

import os
import sys
import re
import time
import json
import cv2
import shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import textwrap
from rapidocr_onnxruntime import RapidOCR
from deep_translator import MyMemoryTranslator, GoogleTranslator
from tqdm import tqdm

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Diretório padrão fixo de saída solicitado pelo usuário
BASE_OUTPUT_DIR = r"C:\Users\ja329\OneDrive\Documentos\MANGAS"
temp_render_dir = os.path.join(os.environ.get("TEMP", "C:\\temp"), "manga_render_tmp")

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\comicbd.ttf",   # Comic Sans MS Bold
    r"C:\Windows\Fonts\segoeuib.ttf",  # Segoe UI Bold
    r"C:\Windows\Fonts\arialbd.ttf"    # Arial Bold
]

def get_best_font():
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return "arial.ttf"

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def detect_language_from_samples(texts):
    """Detecta automaticamente o idioma predominante (Japonês, Coreano, Chinês, Inglês, etc.)."""
    full_str = " ".join(texts)
    if not full_str.strip():
        return "en-US"
        
    # Contagem de caracteres por categoria
    ko_chars = len(re.findall(r'[\uac00-\ud7af\u1100-\u11ff]', full_str))
    jp_kana = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', full_str))
    cjk_ideographs = len(re.findall(r'[\u4e00-\u9fff]', full_str))
    latin_chars = len(re.findall(r'[a-zA-Z]', full_str))
    
    total_asian = ko_chars + jp_kana + cjk_ideographs
    
    # 1. Se os caracteres latinos forem predominantemente maiores (evita que ruído OCR ou um SFX japonês assuma o controle)
    if latin_chars > 20 and latin_chars > (total_asian * 2):
        lower = full_str.lower()
        spanish_markers = [" el ", " la ", " de ", " que ", " y ", " en ", " un ", " por ", " con ", " para "]
        # Exige pelo menos alguns marcadores para garantir que é espanhol, senão assume inglês
        if sum(1 for m in spanish_markers if m in lower) >= 3:
            return "es-ES"
        return "en-US"
        
    # 2. Avalia qual idioma asiático é o principal
    if ko_chars > 10 and ko_chars > jp_kana:
        return "ko-KR"
    if jp_kana > 10 or (cjk_ideographs > 20 and jp_kana > 0):
        return "ja-JP"
    if cjk_ideographs > 20 and jp_kana <= 5:
        return "zh-CN"
        
    # 3. Fallbacks finais
    if latin_chars > total_asian:
        return "en-US"
        
    return "ja-JP"

def should_merge_lines(b1, b2):
    x1_min, y1_min, x1_max, y1_max = b1["box"]
    x2_min, y2_min, x2_max, y2_max = b2["box"]
    
    h1 = y1_max - y1_min
    h2 = y2_max - y2_min
    w1 = x1_max - x1_min
    w2 = x2_max - x2_min
    
    overlap_x = max(0, min(x1_max, x2_max) - max(x1_min, x2_min))
    overlap_y = max(0, min(y1_max, y2_max) - max(y1_min, y2_min))
    
    gap_x = max(0, max(x1_min, x2_min) - min(x1_max, x2_max))
    gap_y = max(0, max(y1_min, y2_min) - min(y1_max, y2_max))
    
    # 1. Logica para texto predominantemente HORIZONTAL
    if w1 >= h1 or w2 >= h2:
        if gap_y < max(max(h1, h2) * 1.5, 35):
            cx1 = (x1_min + x1_max) / 2
            cx2 = (x2_min + x2_max) / 2
            if overlap_x > 0 or abs(cx1 - cx2) < max(w1, w2) * 0.8:
                if gap_x < 40:
                    return True

    # 2. Logica para texto predominantemente VERTICAL (Mangas Japoneses)
    if h1 > w1 and h2 > w2:
        if gap_x < max(max(w1, w2) * 2.5, 50): # Linhas verticais podem ter espacamento lateral
            cy1 = (y1_min + y1_max) / 2
            cy2 = (y2_min + y2_max) / 2
            if overlap_y > 0 or abs(cy1 - cy2) < max(h1, h2) * 0.8:
                if gap_y < 50:
                    return True
                    
    # Fallback de proximidade extrema
    if gap_x < 25 and gap_y < 25:
        return True
        
    return False

def smart_group_bubbles(blocks):
    """Agrupa linhas de texto próximas usando conectividade de grafos, suportando leitura oriental."""
    n = len(blocks)
    if n == 0:
        return []
    adj = {i: [] for i in range(n)}
    
    for i in range(n):
        for j in range(i + 1, n):
            if should_merge_lines(blocks[i], blocks[j]):
                adj[i].append(j)
                adj[j].append(i)
                
    visited = set()
    clusters = []
    
    for i in range(n):
        if i not in visited:
            comp = []
            queue = [i]
            visited.add(i)
            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            clusters.append(comp)
            
    bubbles = []
    for comp in clusters:
        comp_blocks = [blocks[idx] for idx in comp]
        
        avg_w = np.mean([b["box"][2] - b["box"][0] for b in comp_blocks])
        avg_h = np.mean([b["box"][3] - b["box"][1] for b in comp_blocks])
        is_vertical = avg_h > avg_w * 1.2
        
        if is_vertical:
            # Leitura oriental: Direita para Esquerda (X descrescente), Topo para Baixo
            comp_blocks.sort(key=lambda b: (-b["box"][2], b["box"][1]))
        else:
            # Leitura ocidental: Topo para Baixo (Y crescente), Esquerda para Direita
            comp_blocks.sort(key=lambda b: (b["box"][1], b["box"][0]))
        
        xmin = min(b["box"][0] for b in comp_blocks)
        ymin = min(b["box"][1] for b in comp_blocks)
        xmax = max(b["box"][2] for b in comp_blocks)
        ymax = max(b["box"][3] for b in comp_blocks)
        
        lines_text = [b["text"].strip() for b in comp_blocks]
        full_text = " ".join(lines_text)
        
        raw_boxes = [b["box"] for b in comp_blocks]
        
        bubbles.append({
            "box": [xmin, ymin, xmax, ymax],
            "raw_boxes": raw_boxes,
            "lines": lines_text,
            "combined_text": full_text,
            "is_vertical": is_vertical
        })
        
    bubbles.sort(key=lambda b: (b["box"][1], b["box"][0]))
    return bubbles

def fit_text_to_box(draw, text, max_w, max_h, font_path):
    """Ajusta proporcionalmente o tamanho da fonte e quebras de linha com precisão cirúrgica."""
    paragraphs = text.split('\n')
    
    for font_size in range(24, 10, -1):
        font = ImageFont.truetype(font_path, font_size)
        all_lines = []
        fits_all = True
        
        for para in paragraphs:
            words = para.split()
            if not words:
                continue
            
            best_para_lines = None
            for num_lines in range(1, 10):
                words_per_line = int(np.ceil(len(words) / num_lines))
                candidate_lines = []
                for i in range(0, len(words), words_per_line):
                    candidate_lines.append(' '.join(words[i:i+words_per_line]))
                    
                fits = True
                for l in candidate_lines:
                    bbox = draw.textbbox((0, 0), l, font=font)
                    w_line = bbox[2] - bbox[0]
                    if w_line > max_w:
                        fits = False
                        break
                if fits:
                    best_para_lines = candidate_lines
                    break
                    
            if best_para_lines is not None:
                all_lines.extend(best_para_lines)
            else:
                fits_all = False
                break
                
        if fits_all and all_lines:
            line_h = (draw.textbbox((0, 0), "Ag", font=font)[3] - draw.textbbox((0, 0), "Ag", font=font)[1]) * 1.22
            if len(all_lines) * line_h <= max_h:
                return font, all_lines
                
    font = ImageFont.truetype(font_path, 10)
    fallback_lines = []
    for p in paragraphs:
        fallback_lines.extend(textwrap.wrap(p, width=14))
    return font, fallback_lines

import urllib.request

def check_ollama_available():
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as response:
            if response.status == 200:
                # Retorna o primeiro modelo disponível como padrão
                data = json.loads(response.read().decode('utf-8'))
                models = data.get("models", [])
                if models:
                    return True, models[0]["name"]
        return True, "llama3" # fallback de nome se falhar o parse
    except Exception:
        return False, None

def translate_with_ollama(text, model_name):
    url = "http://localhost:11434/api/generate"
    prompt = f"""Atue como um tradutor e diagramador profissional de mangás adultos.
O texto a seguir pode conter múltiplos idiomas no mesmo mangá (ex: Inglês e Japonês misturados).
Identifique o idioma deste trecho e traduza-o para o Português do Brasil (PT-BR) com extrema naturalidade.

REGRAS DE FORMATAÇÃO E TRADUÇÃO:
1. Adapte gírias, expressões e linguagem explícita para o português coloquial e fluído. Não censure.
2. Adapte gemidos e onomatopeias para o formato BR (ex: "Ah...", "Ugh!", "Nhn~").
3. Use pontuação dramática de mangá (exclamações, interrogações e reticências).
4. Responda APENAS com a tradução, sem aspas, sem notas e sem o texto original.

Texto original: {text}
Tradução:"""
    
    data = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3
        }
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get("response", "").strip()
    except Exception:
        return None

def translate_batch_texts(text_list, src_lang="auto"):
    """Traduz lista de textos para Português usando Ollama (se disponível) com fallback para MyMemory/Google."""
    if not text_list:
        return []
        
    if src_lang == "auto":
        src_lang = detect_language_from_samples(text_list)
    elif src_lang == "ja":
        src_lang = "ja-JP"
    elif src_lang == "en":
        src_lang = "en-US"
    elif src_lang == "ko":
        src_lang = "ko-KR"
    elif src_lang == "zh":
        src_lang = "zh-CN"
    elif src_lang == "es":
        src_lang = "es-ES"
        
    print(f"[*] Idioma de origem detectado/configurado: {src_lang} -> pt-BR")
    
    ollama_active, ollama_model = check_ollama_available()
    if ollama_active:
        print(f"[+] OLLAMA DETECTADO! Ativando Modo Inteligência Artificial Local (Modelo: {ollama_model})...")
    else:
        print(f"[*] Ollama não detectado. Usando modo de tradução em nuvem (MyMemory/Google).")
    
    # Forçamos o fallback para 'auto', permitindo que o Google Translator avalie balão por balão
    # caso o mangá tenha idiomas misturados (ex: balão em inglês e balão em japonês no mesmo capítulo)
    fallback_code = 'auto'
    translator = MyMemoryTranslator(source=src_lang, target='pt-BR')
    results = []
    
    for i, t in enumerate(tqdm(text_list, desc="Traduzindo", unit="balão")):
        clean_t = t.strip()
        if not clean_t or clean_t in ("...", "…", "!!", "!?"):
            results.append(clean_t)
            continue
            
        res = None
        
        # 1. Tenta IA Local (Ollama)
        if ollama_active:
            res = translate_with_ollama(clean_t, ollama_model)
            
        # 2. Fallback Nuvem
        if not res:
            try:
                res = translator.translate(clean_t)
                if "MYMEMORY WARNING" in res:
                    res = GoogleTranslator(source=fallback_code, target='pt').translate(clean_t)
                time.sleep(0.1) # Cooldown da API grátis
            except Exception:
                try:
                    time.sleep(1) # Backoff
                    res = GoogleTranslator(source=fallback_code, target='pt').translate(clean_t)
                except Exception:
                    res = clean_t
                    
        # Validação extra de segurança: a IA pode às vezes colocar aspas em volta da resposta
        if res and res.startswith('"') and res.endswith('"'):
            res = res[1:-1].strip()
            
        results.append(res)
                
    return results

def create_html_reader(images_dir, title):
    """Gera leitor web moderno e responsivo."""
    images = [f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f != "leitor.html"]
    images.sort(key=natural_sort_key)
    
    if not images:
        return
        
    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} [PT-BR]</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background-color: #121212; color: #f1f1f1; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; flex-direction: column; align-items: center; min-height: 100vh; }}
  header {{ position: fixed; top: 0; left: 0; right: 0; background: rgba(18, 18, 18, 0.95); backdrop-filter: blur(8px); border-bottom: 1px solid #2a2a2a; padding: 10px 20px; display: flex; justify-content: space-between; align-items: center; z-index: 100; }}
  h1 {{ font-size: 15px; font-weight: 600; color: #fff; max-width: 50%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .controls {{ display: flex; align-items: center; gap: 12px; }}
  button, select {{ background: #252525; color: #fff; border: 1px solid #3d3d3d; padding: 6px 14px; border-radius: 6px; font-size: 14px; cursor: pointer; }}
  button:hover, select:hover {{ background: #333; }}
  .reader-container {{ margin-top: 60px; margin-bottom: 40px; display: flex; flex-direction: column; align-items: center; max-width: 1000px; width: 100%; padding: 0 10px; }}
  .page-view {{ display: flex; flex-direction: column; align-items: center; width: 100%; }}
  .page-view img {{ max-width: 100%; max-height: 90vh; object-fit: contain; border-radius: 4px; box-shadow: 0 4px 20px rgba(0,0,0,0.6); cursor: pointer; }}
  .scroll-view {{ display: none; flex-direction: column; align-items: center; gap: 15px; width: 100%; }}
  .scroll-view img {{ max-width: 100%; border-radius: 4px; box-shadow: 0 4px 16px rgba(0,0,0,0.5); }}
  .nav-footer {{ margin-top: 15px; display: flex; gap: 15px; align-items: center; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="controls">
    <select id="modeSelect" onchange="toggleMode()">
      <option value="single">Página por Página</option>
      <option value="scroll">Rolar Tudo (Webtoon)</option>
    </select>
    <button onclick="prevPage()">◀ Anterior</button>
    <span id="pageIndicator">1 / {len(images)}</span>
    <button onclick="nextPage()">Próxima ▶</button>
  </div>
</header>
<div class="reader-container">
  <div id="pageView" class="page-view">
    <img id="currentImg" src="{images[0]}" alt="Página 1" onclick="nextPage()">
    <div class="nav-footer">
      <button onclick="prevPage()">◀ Anterior</button>
      <button onclick="nextPage()">Próxima ▶</button>
    </div>
  </div>
  <div id="scrollView" class="scroll-view">
    {"".join(f'<img src="{img}" loading="lazy" alt="Página {i+1}">' for i, img in enumerate(images))}
  </div>
</div>
<script>
  const images = {images};
  let currentIndex = 0;
  const currentImg = document.getElementById('currentImg');
  const pageIndicator = document.getElementById('pageIndicator');
  const pageView = document.getElementById('pageView');
  const scrollView = document.getElementById('scrollView');
  const modeSelect = document.getElementById('modeSelect');

  function updatePage() {{
    currentImg.src = images[currentIndex];
    pageIndicator.textContent = (currentIndex + 1) + " / " + images.length;
    window.scrollTo(0, 0);
  }}
  function prevPage() {{ if (currentIndex > 0) {{ currentIndex--; updatePage(); }} }}
  function nextPage() {{ if (currentIndex < images.length - 1) {{ currentIndex++; updatePage(); }} }}
  function toggleMode() {{
    if (modeSelect.value === 'scroll') {{
      pageView.style.display = 'none'; scrollView.style.display = 'flex';
    }} else {{
      scrollView.style.display = 'none'; pageView.style.display = 'flex'; updatePage();
    }}
  }}
  document.addEventListener('keydown', (e) => {{
    if (modeSelect.value === 'single') {{
      if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') nextPage();
      else if (e.key === 'ArrowLeft' || e.key === 'PageUp') prevPage();
    }}
  }});
</script>
</body>
</html>
"""
    leitor_file = os.path.join(images_dir, "leitor.html")
    with open(leitor_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[+] Leitor interativo criado: {leitor_file}")

def check_needs_rapidocr(manga_dir):
    """Analisa uma página no meio do mangá usando RapidOCR para ver se é inglês/latino"""
    try:
        from rapidocr_onnxruntime import RapidOCR
        import glob
        img_files = glob.glob(os.path.join(manga_dir, "*.*"))
        img_files = [f for f in img_files if f.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.bmp'))]
        if not img_files: return False
        
        sample_idx = min(len(img_files)//2, len(img_files)-1)
        src_path = img_files[sample_idx]
        
        engine = RapidOCR()
        try:
            with open(src_path, "rb") as f:
                img_array = np.asarray(bytearray(f.read()), dtype=np.uint8)
                img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            res, _ = engine(img_cv)
        except Exception:
            return False
            
        if not res: return False
        
        latin_count = 0
        asian_count = 0
        for box in res:
            text = box[1]
            latin_count += len(re.findall(r'[a-zA-Z]', text))
            asian_count += len(re.findall(r'[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]', text))
            
        return latin_count > 10 and latin_count > (asian_count * 2)
    except Exception:
        return False

def generate_rapidocr_json(manga_dir, output_json_path):
    """Gera o arquivo json de caixas usando RapidOCR (ideal para Inglês/Latino)"""
    from rapidocr_onnxruntime import RapidOCR
    import glob
    
    img_files = glob.glob(os.path.join(manga_dir, "*.*"))
    img_files = [f for f in img_files if f.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.bmp'))]
    img_files.sort(key=natural_sort_key)
    
    engine = RapidOCR()
    pages = []
    
    print("[*] Extraindo textos usando RapidOCR (Motor otimizado para Inglês/Latino)...")
    for img_path in tqdm(img_files, desc="OCR Pages"):
        img_name = os.path.basename(img_path)
        try:
            with open(img_path, "rb") as f:
                img_array = np.asarray(bytearray(f.read()), dtype=np.uint8)
                img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        except Exception:
            img_cv = None
            
        if img_cv is None:
            continue
            
        res, _ = engine(img_cv)
        blocks_for_grouping = []
        if res:
            for box_data in res:
                coords = box_data[0]
                text = box_data[1]
                xs = [p[0] for p in coords]
                ys = [p[1] for p in coords]
                
                blocks_for_grouping.append({
                    "box": [min(xs), min(ys), max(xs), max(ys)],
                    "text": text
                })
                
        # Usa a função smart_group_bubbles nativa para agrupar as falas do RapidOCR
        grouped = smart_group_bubbles(blocks_for_grouping)
        final_blocks = []
        for b in grouped:
            final_blocks.append({
                "box": [int(round(float(v))) for v in b["box"]],
                "vertical": bool(b["is_vertical"]),
                "lines": b["lines"]
            })
            
        pages.append({
            "img_path": img_name,
            "blocks": final_blocks
        })
        
    mokuro_data = {"version": "rapidocr", "pages": pages}
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(mokuro_data, f, ensure_ascii=False)

def process_manga(manga_dir, target_lang="pt-BR", ocr_mode="auto", force_ocr=False):
    manga_dir = os.path.abspath(manga_dir.strip('\"\''))
    if not os.path.exists(manga_dir) or not os.path.isdir(manga_dir):
        print(f"[!] Erro: Caminho inválido ({manga_dir})")
        return False
        
    manga_name = os.path.basename(manga_dir)
    clean_name = manga_name.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip()
    
    # 0. Define o diretório de destino diretamente como especificado
    base_drive_dir = BASE_OUTPUT_DIR
    try:
        os.makedirs(base_drive_dir, exist_ok=True)
    except Exception as e:
        print(f"[!] Aviso: Não foi possível criar/acessar a pasta raiz do destino: {e}")
        # Fallback de segurança
        base_drive_dir = os.path.dirname(manga_dir)
        
    output_dir = os.path.join(base_drive_dir, f"{clean_name} [PT-BR]")
    os.makedirs(output_dir, exist_ok=True)
    
    # Pasta dedicada para todos os arquivos de cache (OCR, .mokuro, traducoes)
    cache_dir = os.path.join(output_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    
    # Criar pasta temp segura e ÚNICA para evitar conflitos se rodar 2 mangás ao mesmo tempo
    import uuid
    temp_render_dir = os.path.join(os.environ.get("TEMP", "C:\\temp"), f"manga_render_tmp_{uuid.uuid4().hex[:8]}")
    os.makedirs(temp_render_dir, exist_ok=True)
    
    print("=" * 60)
    print(f"[*] INICIANDO TRADUCAO DO MANGA")
    print(f"[*] Pasta de Entrada: {manga_dir}")
    print(f"[*] Pasta de Destino: {output_dir}")
    print("=" * 60)
    
    # 1. Carregar arquivos de imagem
    img_files = [f for f in os.listdir(manga_dir) if f.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.bmp'))]
    img_files.sort(key=natural_sort_key)
    
    if not img_files:
        print("[!] Nenhuma imagem encontrada na pasta especificada.")
        return False
        
    print(f"[+] {len(img_files)} imagens encontradas.")
    
    # 2. Executar OCR usando Mokuro ou RapidOCR (Armazenado na pasta cache)
    parent_dir = os.path.dirname(manga_dir)
    mokuro_path = os.path.join(cache_dir, manga_name + ".mokuro")
    cache_file = os.path.join(cache_dir, "translation_cache.json")
    html_dest = os.path.join(cache_dir, manga_name + "_mokuro.html")
    
    # Migra caches legados soltos fora da pasta cache (se existirem)
    legacy_mokuro = os.path.join(parent_dir, manga_name + ".mokuro")
    legacy_dest_mokuro = os.path.join(output_dir, manga_name + ".mokuro")
    legacy_cache_file = os.path.join(output_dir, "translation_cache.json")
    
    if not os.path.exists(mokuro_path):
        if os.path.exists(legacy_dest_mokuro):
            try: shutil.move(legacy_dest_mokuro, mokuro_path)
            except Exception: pass
        elif os.path.exists(legacy_mokuro):
            try: shutil.move(legacy_mokuro, mokuro_path)
            except Exception: pass
            
    if not os.path.exists(cache_file) and os.path.exists(legacy_cache_file):
        try: shutil.move(legacy_cache_file, cache_file)
        except Exception: pass

    # Se limpeza forcada foi solicitada
    if force_ocr:
        print("[!] LIMPEZA DE CACHE ATIVADA: Removendo pasta cache deste manga...")
        if os.path.exists(cache_dir):
            try:
                shutil.rmtree(cache_dir)
                print(f"    [x] Pasta cache removida: {cache_dir}")
            except Exception as ce:
                print(f"    [!] Aviso ao remover cache: {ce}")
        os.makedirs(cache_dir, exist_ok=True)
        # Limpa eventuais arquivos soltos na pasta de origem
        for p in [legacy_mokuro, os.path.join(parent_dir, manga_name + ".html")]:
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass

    # Decidir qual motor deve ser usado
    print(f"[*] Modo OCR selecionado: {ocr_mode.upper()}")
    
    use_rapidocr = False
    if ocr_mode == "rapidocr":
        use_rapidocr = True
    elif ocr_mode == "mokuro":
        use_rapidocr = False
    elif ocr_mode == "auto":
        print("[*] Analisando imagens para escolher o motor OCR ideal...")
        use_rapidocr = check_needs_rapidocr(manga_dir)
        
    expected_engine = "rapidocr" if use_rapidocr else "mokuro"

    # Verificar se ja existe um arquivo .mokuro na pasta cache e se e compativel
    needs_new_ocr = True
    if not force_ocr and os.path.exists(mokuro_path):
        try:
            with open(mokuro_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            file_version = str(existing_data.get("version", ""))
            is_file_rapidocr = (file_version == "rapidocr")
            
            pages = existing_data.get("pages", [])
            total_blocks = sum(len(p.get("blocks", [])) for p in pages)
            
            if total_blocks == 0:
                print("[!] Cache OCR na pasta cache estava VAZIO. Regerando...")
                os.remove(mokuro_path)
                needs_new_ocr = True
            elif (use_rapidocr and is_file_rapidocr) or (not use_rapidocr and not is_file_rapidocr):
                print(f"[+] Cache OCR compativel ({expected_engine.upper()}) encontrado na pasta cache ({total_blocks} baloes). Reutilizando...")
                needs_new_ocr = False
            else:
                print(f"[*] Cache OCR existente pertence a outro motor ({'RAPIDOCR' if is_file_rapidocr else 'MOKURO'}). Regerando na pasta cache com {expected_engine.upper()}...")
                os.remove(mokuro_path)
                needs_new_ocr = True
        except Exception as e:
            print(f"[!] Erro ao ler cache existente ({e}). Regerando...")
            try: os.remove(mokuro_path)
            except Exception: pass
            needs_new_ocr = True

    if needs_new_ocr:
        if use_rapidocr:
            print("[+] Executando motor Universal/Ocidental (RapidOCR) -> Salvando em cache...")
            generate_rapidocr_json(manga_dir, mokuro_path)
        else:
            print("[*] Executando motor Asiatico especializado (Mokuro)...")
            import subprocess
            try:
                subprocess.run([sys.executable, "-m", "mokuro", manga_dir, "--disable_confirmation"], check=True)
                # Mover saidas geradas pelo Mokuro para dentro da pasta cache para nao poluir a origem
                temp_mokuro = os.path.join(parent_dir, manga_name + ".mokuro")
                if os.path.exists(temp_mokuro):
                    shutil.move(temp_mokuro, mokuro_path)
                temp_html = os.path.join(parent_dir, manga_name + ".html")
                if os.path.exists(temp_html):
                    shutil.move(temp_html, html_dest)
            except subprocess.CalledProcessError as e:
                print(f"[!] Erro ao executar o Mokuro. Detalhes: {e}")
                return False

    if not os.path.exists(mokuro_path):
        print("[!] Arquivo de texto OCR nao foi gerado na pasta cache. Falha na leitura.")
        return False

    print("[*] Lendo dados estruturados do Mokuro (pasta cache)...")
    with open(mokuro_path, "r", encoding="utf-8") as f:
        mokuro_data = json.load(f)
        
    pages_data = []
    all_raw_texts = []
    font_path = get_best_font()
    
    # Extrair os balões do formato Mokuro
    for idx, page_info in enumerate(mokuro_data.get("pages", [])):
        fname = os.path.basename(page_info.get("img_path", ""))
        bubbles = []
        for blk in page_info.get("blocks", []):
            xmin, ymin, xmax, ymax = [int(round(float(v))) for v in blk.get("box", [0, 0, 0, 0])]
            is_vertical = blk.get("vertical", True)
            lines = blk.get("lines", [])
            text = " ".join(lines)
            
            if not text.strip():
                continue
                
            all_raw_texts.append(text)
            bubbles.append({
                "box": [xmin, ymin, xmax, ymax],
                "raw_boxes": [[xmin, ymin, xmax, ymax]], # Mokuro dá apenas o bloco inteiro, sem bounding box por linha, então usamos o bloco como raw_box
                "lines": lines,
                "combined_text": text,
                "is_vertical": is_vertical
            })
            
        pages_data.append({
            "page": idx + 1,
            "img": fname,
            "bubbles": bubbles
        })
            
    # 3. Detectar idioma e traduzir
    src_lang = detect_language_from_samples(all_raw_texts)
    print(f"[+] Amostragem analisada: idioma detectado é '{src_lang.upper()}'")
    
    # Montar lista linear de textos para tradução com cache
    cache_file = os.path.join(cache_dir, "translation_cache.json")
    cache = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as cf:
                cache = json.load(cf)
        except Exception:
            pass
            
    texts_to_translate = []
    text_mapping = [] # (page_idx, bubble_idx)
    
    for p_idx, p in enumerate(pages_data):
        for b_idx, b in enumerate(p["bubbles"]):
            orig_text = b["combined_text"].strip()
            if orig_text not in cache:
                texts_to_translate.append(orig_text)
            text_mapping.append((p_idx, b_idx, orig_text))
            
    if texts_to_translate:
        print(f"[*] Traduzindo {len(texts_to_translate)} balões de fala...")
        translated_results = translate_batch_texts(texts_to_translate, src_lang=src_lang)
        for orig, trans in zip(texts_to_translate, translated_results):
            cache[orig] = trans
            
        try:
            # Tenta remover o atributo de oculto/sistema antes se existir (OneDrive quirk)
            if os.path.exists(cache_file):
                os.system(f'attrib -h -r -s "{cache_file}" >nul 2>&1')
            with open(cache_file, "w", encoding="utf-8") as cf:
                json.dump(cache, cf, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[!] Aviso: Nao foi possivel salvar o cache de tradução: {e}")
            
    # Atribuir traduções aos balões
    for p_idx, b_idx, orig_text in text_mapping:
        pages_data[p_idx]["bubbles"][b_idx]["translated_text"] = cache.get(orig_text, orig_text)
        
    # 4. Diagramação e Inpainting
    print(f"[*] Iniciando limpeza de balões e diagramação profissional...")
    for idx, p in enumerate(tqdm(pages_data, desc="Diagramação", unit="pág")):
        img_name = p["img"]
        src_path = os.path.join(manga_dir, img_name)
        
        # Correção para o Windows: cv2.imread falha silenciosamente se o caminho tiver acentos (ex: "Por trás")
        # Usamos numpy imdecode que suporta perfeitamente Unicode no Windows
        try:
            with open(src_path, "rb") as f:
                img_array = np.asarray(bytearray(f.read()), dtype=np.uint8)
                img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        except Exception:
            img_cv = None
            
        if img_cv is None:
            print(f"[!] Aviso: Falha ao ler a imagem {src_path}. Pulando...")
            continue
            
        h_img, w_img = img_cv.shape[:2]
        cleaned = img_cv.copy()
        bubbles = p.get("bubbles", [])
        
        # Limpar balões com a técnica segura (não arrancar arte)
        for b in bubbles:
            boxes_to_clean = b.get("raw_boxes", [b["box"]])
            is_vertical = b.get("is_vertical", False)
            for box in boxes_to_clean:
                xmin, ymin, xmax, ymax = box
                # Para texto vertical japonês (com furigana) a margem lateral deve ser maior
                if is_vertical or (ymax - ymin) > (xmax - xmin) * 1.2:
                    pad_x = 12
                    pad_y = 6
                else:
                    pad_x = 8
                    pad_y = 8
                    
                x0 = int(max(0, xmin - pad_x))
                y0 = int(max(0, ymin - pad_y))
                x1 = int(min(w_img, xmax + pad_x))
                y1 = int(min(h_img, ymax + pad_y))
                
                roi = cleaned[y0:y1, x0:x1]
                if roi.size == 0:
                    continue
                gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                
                # Mascara para inpaint/fill baseada nos pixels de texto escuros
                mask = (gray_roi < 160).astype(np.uint8) * 255
                k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
                mask = cv2.dilate(mask, k, iterations=2)
                
                if np.mean(gray_roi > 210) > 0.20:
                    # Fundo majoritariamente branco: limpa a máscara pintando de branco (evita cortar a borda preta do balao)
                    roi_clean = roi.copy()
                    roi_clean[mask > 0] = (255, 255, 255)
                    cleaned[y0:y1, x0:x1] = roi_clean
                else:
                    # Fundo com textura ou tom de cinza: Inpainting
                    cleaned[y0:y1, x0:x1] = cv2.inpaint(roi, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
                
        # Desenhar texto com Pillow usando fit_text_to_box
        img_pil = Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img_pil)
        
        for b in bubbles:
            text = b.get("translated_text", "").strip().upper()
            if not text or text in ("...", "…"):
                continue
                
            xmin, ymin, xmax, ymax = b["box"]
            bw = xmax - xmin
            bh = ymax - ymin
            cx = (xmin + xmax) / 2
            cy = (ymin + ymax) / 2
            
            target_w = max(bw * 1.15, 80)
            target_h = max(bh * 1.10, 40)
            
            font, lines = fit_text_to_box(draw, text, target_w, target_h, font_path)
            if not lines:
                continue
                
            line_h = (draw.textbbox((0, 0), "Ag", font=font)[3] - draw.textbbox((0, 0), "Ag", font=font)[1]) * 1.22
            total_h = len(lines) * line_h
            start_y = cy - (total_h / 2) + (line_h / 2)
            
            for line_idx, line in enumerate(lines):
                ly = start_y + (line_idx * line_h)
                draw.text((cx, ly), line, font=font, fill=(0, 0, 0), stroke_width=3, stroke_fill=(255, 255, 255), anchor="mm")
                
        out_file = os.path.join(temp_render_dir, os.path.splitext(img_name)[0] + ".jpg")
        img_pil.save(out_file, quality=95)
            
    # 5. Criar leitor interativo no temp
    create_html_reader(temp_render_dir, clean_name)
    
    # 6. Copiar arquivos para a pasta de destino final do OneDrive de forma segura
    print(f"[*] Substituindo arquivos no destino final: {output_dir}...")
    
    # Tenta remover o atributo de oculto/somente leitura de todos os arquivos no destino
    os.system(f'attrib -h -r -s "{output_dir}\\*.*" >nul 2>&1')
    
    all_files = os.listdir(temp_render_dir)
    for fname in all_files:
        src_p = os.path.join(temp_render_dir, fname)
        dst_p = os.path.join(output_dir, fname)
        shutil.copy2(src_p, dst_p)
        
    # Limpeza da pasta temp para não acumular
    try:
        shutil.rmtree(temp_render_dir)
    except Exception:
        pass

    print("\n" + "=" * 60)
    print(f"[+] MANGA TRADUZIDO COM SUCESSO!")
    print(f"[+] Pasta salva: {output_dir}")
    print(f"[+] Leitor Web: {os.path.join(output_dir, 'leitor.html')}")
    print("=" * 60 + "\n")
    
    # 7. Disparar Notificações (PC e Celular)
    try:
        from plyer import notification
        notification.notify(
            title="Mangá Traduzido! 🎉",
            message=f"'{clean_name}' foi finalizado com sucesso!",
            app_name="Manga Translator",
            timeout=10
        )
    except Exception as e:
        print(f"[*] Não foi possível mostrar notificação no Windows: {e}")
        
    try:
        import requests
        # Envia notificação grátis e instantânea para o aplicativo 'ntfy' no celular
        requests.post("https://ntfy.sh/jos9011_mangas",
            data=f"O mangá '{clean_name}' acabou de ser traduzido e salvo no seu OneDrive!".encode('utf-8'),
            headers={
                "Title": "Mangá Concluído!",
                "Priority": "default",
                "Tags": "book,tada"
            },
            timeout=5
        )
    except Exception:
        pass
        
    try:
        os.startfile(output_dir)
    except Exception:
        pass
        
    return True

if __name__ == "__main__":
    force_ocr_flag = False
    if len(sys.argv) > 1:
        args = sys.argv[1:]
        chosen_mode = "auto"
        if "--rapidocr" in args:
            chosen_mode = "rapidocr"
            args.remove("--rapidocr")
        elif "--mokuro" in args:
            chosen_mode = "mokuro"
            args.remove("--mokuro")
            
        if "--force-ocr" in args:
            force_ocr_flag = True
            args.remove("--force-ocr")
        elif "--clean-cache" in args:
            force_ocr_flag = True
            args.remove("--clean-cache")
            
        target = " ".join(args)
    else:
        print("=" * 60)
        print("  SISTEMA AUTOMATICO DE TRADUCAO DE MANGA [PT-BR]")
        print("=" * 60)
        target = input("Arraste ou digite o caminho da pasta do manga: ").strip()
        chosen_mode = "auto"
        
    if target:
        process_manga(target, ocr_mode=chosen_mode, force_ocr=force_ocr_flag)
    else:
        print("[!] Nenhuma pasta informada.")
