# -*- coding: utf-8 -*-
"""
Manga Translation & Typesetting Pipeline (PT-BR Scanlation Tool)
Created for Antigravity & User Workflows.

Features:
- Mokuro OCR integration and coordinate extraction
- Smart balloon cleaning: white fill for solid speech bubbles + OpenCV inpainting for tones/artwork
- Scanlation-grade typesetting with Comic Sans MS / Segoe UI Bold
- Automatic bubble bounds detection, font sizing, word wrapping, and 2px white stroke outlines
- Modern standalone web reader generation (Page-by-page & Webtoon infinite scroll)
"""

import os
import sys
import json
import re
import html
import urllib.parse
import argparse
import subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import textwrap

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
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r'(\d+)', s)]

def run_mokuro_ocr(manga_dir):
    """Executes Mokuro on the given manga directory."""
    print(f"[*] Executando Mokuro OCR em: {manga_dir}")
    cmd = [sys.executable, "-m", "mokuro", manga_dir, "--disable_confirmation"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        print(f"[!] Erro ao rodar Mokuro:\n{res.stderr}")
        return False
    print("[+] Mokuro OCR concluído com sucesso!")
    return True

def extract_mokuro_data(mokuro_file, output_json):
    """Parses .mokuro file into structured JSON with block coordinates and Japanese text."""
    with open(mokuro_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    extracted = []
    for p_idx, page in enumerate(data.get("pages", [])):
        page_num = p_idx + 1
        blocks = []
        for b_idx, block in enumerate(page.get("blocks", [])):
            text = " ".join(line.strip() for line in block.get("lines", []) if line.strip())
            if text:
                blocks.append({
                    "block_idx": b_idx,
                    "box": block.get("box"),
                    "text": text
                })
        if blocks:
            extracted.append({
                "page": page_num,
                "img": page.get("img_path"),
                "blocks": blocks
            })
            
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(extracted, f, ensure_ascii=False, indent=2)
        
    print(f"[+] Extraídos dados de {len(extracted)} páginas para: {output_json}")
    return extracted

def fit_text_in_bubble(draw, text, max_w, max_h, font_path):
    """Fits text inside speech balloon boundaries using proportional sizing and wrapping."""
    words = text.replace('\n', ' ').split()
    if not words:
        return ImageFont.truetype(font_path, 14), []
        
    for font_size in range(26, 10, -2):
        font = ImageFont.truetype(font_path, font_size)
        for num_lines in range(1, 6):
            words_per_line = int(np.ceil(len(words) / num_lines))
            candidate_lines = []
            for i in range(0, len(words), words_per_line):
                candidate_lines.append(' '.join(words[i:i+words_per_line]))
                
            fits = True
            for l in candidate_lines:
                bb = draw.textbbox((0, 0), l, font=font)
                if (bb[2] - bb[0]) > max_w:
                    fits = False
                    break
            
            if fits:
                line_h = (draw.textbbox((0, 0), "Ag", font=font)[3] - draw.textbbox((0, 0), "Ag", font=font)[1]) * 1.25
                if len(candidate_lines) * line_h <= max_h:
                    return font, candidate_lines
                    
    font = ImageFont.truetype(font_path, 11)
    return font, textwrap.wrap(' '.join(words), width=10, break_long_words=False)

def typeset_manga(manga_dir, extracted_json, translations_dict, output_dir):
    """Cleans balloons and typesets Portuguese translation directly into images."""
    os.makedirs(output_dir, exist_ok=True)
    font_path = get_best_font()
    
    with open(extracted_json, "r", encoding="utf-8") as f:
        extracted = json.load(f)
        
    print(f"[*] Iniciando diagramação de {len(extracted)} páginas em {output_dir}...")
    
    for idx, page_info in enumerate(extracted):
        page_num = page_info["page"]
        img_name = page_info["img"]
        img_path = os.path.join(manga_dir, img_name)
        
        if not os.path.exists(img_path):
            continue
            
        img_cv = cv2.imread(img_path)
        if img_cv is None:
            continue
            
        h_img, w_img = img_cv.shape[:2]
        cleaned = img_cv.copy()
        blocks = page_info.get("blocks", [])
        page_trans = translations_dict.get(str(page_num), translations_dict.get(page_num, []))
        
        # 1. Erase text in balloons
        for b_idx, block in enumerate(blocks):
            xmin, ymin, xmax, ymax = block["box"]
            xmin = max(0, min(w_img - 1, xmin))
            ymin = max(0, min(h_img - 1, ymin))
            xmax = max(0, min(w_img, xmax))
            ymax = max(0, min(h_img, ymax))
            
            if xmax <= xmin or ymax <= ymin:
                continue
                
            roi = cleaned[ymin:ymax, xmin:xmax]
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            white_ratio = np.mean(gray > 220)
            
            if white_ratio > 0.55:
                # White speech bubble fill
                cv2.rectangle(cleaned, (max(0, xmin - 3), max(0, ymin - 3)), 
                              (min(w_img, xmax + 3), min(h_img, ymax + 3)), (255, 255, 255), -1)
            else:
                # Tone / Art inpainting
                mask = (gray < 160).astype(np.uint8) * 255
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
                mask = cv2.dilate(mask, kernel, iterations=2)
                cleaned[ymin:ymax, xmin:xmax] = cv2.inpaint(roi, mask, inpaintRadius=4, flags=cv2.INPAINT_TELEA)

        # 2. Draw translated text
        img_pil = Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img_pil)
        
        for b_idx, block in enumerate(blocks):
            if b_idx >= len(page_trans):
                continue
            text = page_trans[b_idx]
            if not text or text.strip() in ("...", "…"):
                continue
                
            box = block["box"]
            xmin, ymin, xmax, ymax = box
            bw = xmax - xmin
            bh = ymax - ymin
            
            cx = (xmin + xmax) / 2
            cy = (ymin + ymax) / 2
            
            bubble_w = max(bw * 1.8, min(bh * 0.75, 200), 75)
            bubble_h = max(bh, 45)
            
            font, lines = fit_text_in_bubble(draw, text, bubble_w, bubble_h, font_path)
            if not lines:
                continue
                
            line_h = (draw.textbbox((0, 0), "Ag", font=font)[3] - draw.textbbox((0, 0), "Ag", font=font)[1]) * 1.25
            total_h = len(lines) * line_h
            start_y = cy - (total_h / 2) + (line_h / 2)
            
            for i, line in enumerate(lines):
                ly = start_y + (i * line_h)
                draw.text((cx, ly), line, font=font, fill=(0, 0, 0), stroke_width=2, stroke_fill=(255, 255, 255), anchor="mm")
                
        out_file = os.path.join(output_dir, os.path.splitext(img_name)[0] + ".jpg")
        img_pil.save(out_file, quality=95)
        
    # Copy any non-text pages (covers, blank, credits)
    for f in os.listdir(manga_dir):
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            out_f = os.path.join(output_dir, os.path.splitext(f)[0] + ".jpg")
            if not os.path.exists(out_f):
                src = Image.open(os.path.join(manga_dir, f)).convert("RGB")
                src.save(out_f, quality=95)
                
    print(f"[+] Diagramação completa concluída em: {output_dir}")
    create_html_reader(output_dir)

def create_html_reader(images_dir, title=None):
    """Gera leitor web moderno, imersivo e adaptativo para celular, tablet e desktop."""
    import urllib.parse
    images = [f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f != "leitor.html"]
    images.sort(key=natural_sort_key)

    if not images:
        print("[!] Nenhuma imagem encontrada para criar o leitor.")
        return

    resolved_title = title or os.path.basename(os.path.abspath(images_dir)).replace(" [PT-BR]", "").replace("[PT-BR]", "").strip() or "Leitor de Mangá Traduzido"
    safe_title = html.escape(str(resolved_title))
    images_json = json.dumps(images, ensure_ascii=False).replace("</", "<\\/")
    first_src = urllib.parse.quote(images[0])
    scroll_imgs_html = "".join(
        f'<img src="{urllib.parse.quote(img)}" loading="lazy" decoding="async" alt="Página {i+1}">'
        for i, img in enumerate(images)
    )
    jump_opts_html = "".join(
        f'<option value="{i}">Pág {i+1} / {len(images)}</option>'
        for i in range(len(images))
    )

    html_content = f"""<!DOCTYPE html>
<!-- manga-studio-reader-v2 -->
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#121212">
<title>{safe_title} [PT-BR]</title>
<style>
  :root {{
    --safe-top: env(safe-area-inset-top, 0px);
    --safe-bottom: env(safe-area-inset-bottom, 0px);
    --accent: #1db954;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }}
  html, body {{ max-width: 100%; overflow-x: hidden; background-color: #0e0e0e; color: #f1f1f1; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    min-height: 100vh;
    min-height: 100dvh;
  }}
  button, select {{
    background: #242424;
    color: #fff;
    border: 1px solid rgba(255,255,255,0.14);
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    touch-action: manipulation;
    min-height: 38px;
  }}
  button:hover, select:hover {{ background: #303030; }}
  button:active {{ transform: scale(0.97); }}

  header {{
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    background: rgba(16, 16, 16, 0.94);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid rgba(255,255,255,0.08);
    padding: calc(8px + var(--safe-top)) 14px 8px 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    z-index: 100;
  }}
  .header-left {{
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex: 1;
  }}
  .btn-back {{
    padding: 6px 10px;
    min-width: 38px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }}
  h1 {{
    font-size: 15px;
    font-weight: 700;
    color: #fff;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .controls {{
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }}

  .reader-container {{
    margin-top: calc(58px + var(--safe-top));
    margin-bottom: calc(68px + var(--safe-bottom));
    display: flex;
    flex-direction: column;
    align-items: center;
    max-width: 960px;
    width: 100%;
    padding: 6px 10px;
    flex: 1;
  }}
  .reader-container.scroll-active {{
    margin-bottom: calc(28px + var(--safe-bottom));
  }}
  .page-view {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 100%;
    flex: 1;
  }}
  .page-stage {{
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
  }}
  .page-view img {{
    max-width: 100%;
    max-height: calc(100dvh - 134px - var(--safe-top) - var(--safe-bottom));
    width: auto;
    height: auto;
    object-fit: contain;
    border-radius: 4px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.65);
    cursor: pointer;
    user-select: none;
  }}
  .scroll-view {{
    display: none;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    width: 100%;
  }}
  .scroll-view img {{
    width: 100%;
    max-width: 100%;
    height: auto;
    display: block;
    border-radius: 4px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.5);
  }}

  .bottom-nav {{
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: rgba(16, 16, 16, 0.94);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-top: 1px solid rgba(255,255,255,0.08);
    padding: 8px 14px calc(8px + var(--safe-bottom)) 14px;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 10px;
    z-index: 100;
  }}
  .bottom-nav button {{
    min-width: 105px;
    white-space: nowrap;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }}
  .bottom-nav button.primary {{
    background: var(--accent);
    color: #000;
    border-color: var(--accent);
    font-weight: 700;
  }}
  #pageJumpSelect {{
    text-align: center;
    min-width: 104px;
    max-width: 150px;
    flex: 0 1 auto;
  }}

  .btn-scroll-top {{
    display: none;
    position: fixed;
    right: 14px;
    bottom: calc(16px + var(--safe-bottom));
    z-index: 99;
    border-radius: 9999px;
    padding: 10px 16px;
    background: rgba(29, 185, 84, 0.92);
    color: #000;
    border: none;
    font-weight: 800;
    box-shadow: 0 4px 16px rgba(0,0,0,0.55);
  }}

  @media (max-width: 640px) {{
    header {{
      padding: calc(6px + var(--safe-top)) 10px 6px 10px;
    }}
    h1 {{
      font-size: 13.5px;
    }}
    select {{
      font-size: 16px;
      padding: 6px 8px;
    }}
    .reader-container {{
      padding: 0;
    }}
    .reader-container.scroll-active .scroll-view {{
      gap: 4px;
    }}
    .reader-container.scroll-active .scroll-view img {{
      border-radius: 0;
    }}
    .bottom-nav {{
      justify-content: space-between;
      padding: 8px 10px calc(8px + var(--safe-bottom)) 10px;
      gap: 6px;
    }}
    .bottom-nav button {{
      flex: 1;
      min-width: 0;
      min-height: 42px;
      padding: 8px 4px;
      font-size: 13px;
    }}
    #pageJumpSelect {{
      min-width: 92px;
      max-width: 132px;
    }}
  }}
</style>
</head>
<body>
<header>
  <div class="header-left">
    <button class="btn-back" onclick="goBack()" title="Voltar" aria-label="Voltar">←</button>
    <h1 title="{safe_title}">{safe_title}</h1>
  </div>
  <div class="controls">
    <select id="modeSelect" onchange="toggleMode()" aria-label="Modo de Leitura">
      <option value="single">Página</option>
      <option value="scroll">Webtoon</option>
    </select>
  </div>
</header>

<div class="reader-container" id="readerContainer">
  <div id="pageView" class="page-view">
    <div class="page-stage">
      <img id="currentImg" src="{first_src}" alt="Página 1" onclick="handleImageClick(event)">
    </div>
  </div>
  <div id="scrollView" class="scroll-view">
    {scroll_imgs_html}
  </div>
</div>

<div class="bottom-nav" id="bottomNav">
  <button onclick="prevPage()">◀ Anterior</button>
  <select id="pageJumpSelect" onchange="jumpToPage(this.value)" aria-label="Selecionar página">
    {jump_opts_html}
  </select>
  <button class="primary" onclick="nextPage()">Próxima ▶</button>
</div>

<button class="btn-scroll-top" id="btnScrollTop" onclick="window.scrollTo({{top: 0, behavior: 'smooth'}})">↑ Topo</button>

<script>
  const images = {images_json};
  let currentIndex = 0;
  const currentImg = document.getElementById('currentImg');
  const pageJumpSelect = document.getElementById('pageJumpSelect');
  const pageView = document.getElementById('pageView');
  const scrollView = document.getElementById('scrollView');
  const modeSelect = document.getElementById('modeSelect');
  const bottomNav = document.getElementById('bottomNav');
  const btnScrollTop = document.getElementById('btnScrollTop');
  const readerContainer = document.getElementById('readerContainer');

  function imgUrl(name) {{
    return encodeURIComponent(name);
  }}

  function goBack() {{
    if (window.opener && !window.opener.closed) {{
      window.close();
      setTimeout(() => {{
        if (!window.closed) {{
          if (window.history.length > 1) window.history.back();
          else window.location.href = '/';
        }}
      }}, 180);
      return;
    }}
    if (window.history.length > 1) {{
      window.history.back();
    }} else {{
      window.location.href = '/';
    }}
  }}

  function updatePage() {{
    currentImg.src = imgUrl(images[currentIndex]);
    if (pageJumpSelect) pageJumpSelect.value = String(currentIndex);
    window.scrollTo(0, 0);
    if (currentIndex + 1 < images.length) {{
      const preloadNext = new Image();
      preloadNext.src = imgUrl(images[currentIndex + 1]);
    }}
  }}
  function prevPage() {{ if (currentIndex > 0) {{ currentIndex--; updatePage(); }} }}
  function nextPage() {{ if (currentIndex < images.length - 1) {{ currentIndex++; updatePage(); }} }}
  function jumpToPage(val) {{
    const idx = parseInt(val, 10);
    if (!isNaN(idx) && idx >= 0 && idx < images.length) {{
      currentIndex = idx;
      updatePage();
    }}
  }}

  function handleImageClick(e) {{
    const rect = currentImg.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    if (clickX < rect.width * 0.28) {{
      prevPage();
    }} else {{
      nextPage();
    }}
  }}

  function toggleMode() {{
    if (modeSelect.value === 'scroll') {{
      pageView.style.display = 'none';
      scrollView.style.display = 'flex';
      bottomNav.style.display = 'none';
      btnScrollTop.style.display = 'inline-block';
      readerContainer.classList.add('scroll-active');
    }} else {{
      scrollView.style.display = 'none';
      pageView.style.display = 'flex';
      bottomNav.style.display = 'flex';
      btnScrollTop.style.display = 'none';
      readerContainer.classList.remove('scroll-active');
      updatePage();
    }}
  }}

  // Swipe horizontal no celular (ignora quando usuario esta dando zoom)
  let touchStartX = 0, touchStartY = 0, touchStartTime = 0, multiTouch = false;
  pageView.addEventListener('touchstart', (e) => {{
    if (e.touches.length > 1) {{ multiTouch = true; return; }}
    multiTouch = false;
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    touchStartTime = Date.now();
  }}, {{ passive: true }});

  pageView.addEventListener('touchend', (e) => {{
    if (multiTouch || modeSelect.value !== 'single') return;
    if (window.visualViewport && window.visualViewport.scale > 1.05) return;
    const t = e.changedTouches && e.changedTouches[0];
    if (!t) return;
    const dx = t.clientX - touchStartX;
    const dy = t.clientY - touchStartY;
    const dt = Date.now() - touchStartTime;
    if (dt < 450 && Math.abs(dx) > 55 && Math.abs(dx) > Math.abs(dy) * 1.6) {{
      if (dx < 0) nextPage();
      else prevPage();
    }}
  }}, {{ passive: true }});

  document.addEventListener('keydown', (e) => {{
    if (modeSelect.value === 'single') {{
      if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') {{ e.preventDefault(); nextPage(); }}
      else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {{ e.preventDefault(); prevPage(); }}
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline Completo de Tradução e Diagramação de Mangá")
    subparsers = parser.add_subparsers(dest="command")
    
    # Subcommand: ocr
    p_ocr = subparsers.add_parser("ocr", help="Executar Mokuro OCR e extrair JSON")
    p_ocr.add_argument("manga_dir", help="Caminho da pasta do mangá com imagens")
    
    # Subcommand: reader
    p_reader = subparsers.add_parser("reader", help="Gerar leitor HTML para uma pasta de imagens")
    p_reader.add_argument("images_dir", help="Pasta das imagens")
    
    # Subcommand: typeset
    p_typeset = subparsers.add_parser("typeset", help="Diagramar tradução nas imagens")
    p_typeset.add_argument("manga_dir", help="Pasta original com imagens")
    p_typeset.add_argument("extracted_json", help="Arquivo extracted_raw_text.json")
    p_typeset.add_argument("translations_json", help="Arquivo com as traduções em JSON")
    p_typeset.add_argument("output_dir", help="Pasta destino das imagens diagramadas")
    
    args = parser.parse_args()
    
    if args.command == "ocr":
        run_mokuro_ocr(args.manga_dir)
        # Look for generated .mokuro file in parent directory
        parent = os.path.dirname(os.path.abspath(args.manga_dir))
        stem = os.path.basename(os.path.abspath(args.manga_dir))
        mokuro_f = os.path.join(parent, stem + ".mokuro")
        if os.path.exists(mokuro_f):
            out_json = os.path.join(parent, f"{stem}_extracted.json")
            extract_mokuro_data(mokuro_f, out_json)
    elif args.command == "reader":
        create_html_reader(args.images_dir)
    elif args.command == "typeset":
        with open(args.translations_json, "r", encoding="utf-8") as f:
            t_data = json.load(f)
        typeset_manga(args.manga_dir, args.extracted_json, t_data, args.output_dir)
    else:
        parser.print_help()
