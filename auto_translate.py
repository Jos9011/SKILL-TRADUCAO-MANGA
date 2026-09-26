# -*- coding: utf-8 -*-
r"""
Auto Manga Translator & Typesetter (PT-BR)
Salva automaticamente em: C:\Users\ja329\OneDrive\Documentos\MANGAS

Suporta:
- Arrastar e soltar pastas no .bat
- OCR automático de alta precisão (RapidOCR com suporte a texto colorido + Mokuro)
- Detecção automática de idioma (Japonês, Inglês, Coreano, Espanhol -> PT-BR)
- Limpeza cirúrgica de balões (fill branco preservando bordas + Telea inpainting para arte)
- Diagramação com Comic Sans MS Bold, centralização e outline de contraste
- Proteção total contra alucinações de IA, notas de chatbot e inversões anatômicas
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
import urllib.request
from rapidocr_onnxruntime import RapidOCR
from deep_translator import MyMemoryTranslator, GoogleTranslator
from tqdm import tqdm

try:
    import wordninja
except ImportError:
    wordninja = None

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Diretório padrão fixo de saída solicitado pelo usuário
BASE_OUTPUT_DIR = r"C:\Users\ja329\OneDrive\Documentos\MANGAS"

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
    
    # 1. Se os caracteres latinos forem predominantemente maiores
    if latin_chars > 20 and latin_chars > (total_asian * 2):
        lower = full_str.lower()
        spanish_markers = [" el ", " la ", " de ", " que ", " y ", " en ", " un ", " por ", " con ", " para "]
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

# Dicionário de Onomatopeias e Efeitos Sonoros de Mangá (tradução direta sem alucinação de LLM)
SFX_DICTIONARY = {
    'SPRT': 'SPLASH',
    'SPLRRRT': 'SPLASH',
    'SLICK': 'SLICK',
    'BOING': 'BOING',
    'FLASH': 'FLASH',
    'DRIP': 'PINGA',
    'SCRATCH': 'RASC',
    'STRETCH': 'ESTICA',
    'PUAH': 'PUAH',
    'SLORP': 'SLURP',
    'LICK': 'LAMBE',
    'GROPE': 'APALPA',
    'ZLRCH': 'ZLRCH',
    'GLUG': 'GLUG',
    'PANT': 'OFEGA',
    'GASP': 'ARF',
    'SIGH': 'SUSPIRO',
    'THUMP': 'TUM',
    'DOOM': 'BUM',
    'CREAK': 'RHEEE',
    'CLANG': 'CLANG',
    'SMACK': 'SMACK',
    'KISS': 'BEIJO',
    'CHU': 'CHU',
    'AH': 'AH',
    'HAH': 'HAH',
    'UGH': 'UGH',
    'NGH': 'NGH',
    'MNH': 'MNH',
    'AAH': 'AAH',
    'GRIN': 'SORRISO',
    'GIGGLE': 'RISINHO',
    'SLAP': 'TAPA',
    'BANG': 'BUM',
    'TWITCH': 'TREME',
    'THROB': 'PULSA',
    'PINCH': 'BELISCA',
    'RUB': 'ESFREGA',
    'FAP': 'FAP',
    'ZUP': 'ZUP',
    'ZUR': 'ZUR',
    'SHLICK': 'SHLICK',
    'JUPOK': 'CHUP',
    'GUPOK': 'CHUP',
    'SNIFF': 'CHEIRA',
    'GULP': 'GLUP',
    'CHOMP': 'MHAM',
    'WAG': 'ABANA',
    'TUG': 'PUXA',
    'STRIP': 'TIRA',
    'SPREAD': 'ABRE',
    'FREEZE': 'CONGELA',
    'JOLT': 'SOBRESSALTO',
    'SHIVER': 'TREME',
    'SPLRT': 'SPLASH',
    'SPLRRT': 'SPLASH',
    'SPLRCH': 'SPLASH',
    'SLRCH': 'SLRCH',
    'SLURP': 'SLURP',
    'SLURRRRRRP': 'SLURP'
}

COMMON_SOUNDS = set(SFX_DICTIONARY.keys()) | {
    'AH', 'HAH', 'AHN', 'MNH', 'UGH', 'NGH', 'AAH', 'AHA', 'FWAA', 'NYAA',
    'HYAH', 'NYAH', 'FUH', 'JYAA', 'CHOP', 'DROP', 'FREEZE', 'SLIP', 'SHH'
}

def translate_sfx_phrase(text):
    """Detecta frases compostas de onomatopeias e traduz diretamente sem chamar a IA."""
    if not text:
        return None
    raw_clean = re.sub(r'[^A-Za-z0-9\s!?.,~-]', '', text).strip()
    if not raw_clean:
        return None
    tokens = [t for t in re.split(r'[\s,]+', raw_clean) if t]
    if not tokens:
        return None
    words = [re.sub(r'[^A-Za-z]', '', t).upper() for t in tokens if re.search(r'[A-Za-z]', t)]
    if not words:
        return None
    if all(w in COMMON_SOUNDS or w in SFX_DICTIONARY for w in words):
        translated_parts = []
        for t in tokens:
            w = re.sub(r'[^A-Za-z]', '', t).upper()
            punct = re.sub(r'[A-Za-z0-9]', '', t)
            tr = SFX_DICTIONARY.get(w, w)
            translated_parts.append(tr + punct if punct else tr)
        return " ".join(translated_parts)
    return None

PRESERVE_WORDS = {
    'ONII-SAN', 'ONE-SAN', 'SENSEI', 'SENPAI', 'KOHAI', 'KOUHAI',
    'OTAKU', 'COSPLAY', 'ISEKAI', 'DOUJIN', 'HENTAI', 'MANGA',
    'PT-BR', 'R18', 'PDF', 'JPG', 'PNG', 'WEBP', 'NORUN', 'MISHA', 'CHISE', 'LOVEMEA'
}

def repair_glued_text(text, src_lang="en-US"):
    """Separa palavras coladas no OCR em inglês/latino usando wordninja e regex."""
    if not text or src_lang in ("ja-JP", "zh-CN", "ko-KR"):
        return text
        
    if re.match(r'^(?:https?://|www\.|discord\.gg)', text, re.IGNORECASE):
        return text

    # Corrige falta de espaço após pontuação: 'PANTIES,AND' -> 'PANTIES, AND'
    text = re.sub(r'([,;:!?])([A-Za-z])', r'\1 \2', text)
    text = re.sub(r'(\.{2,})([A-Za-z])', r'\1 \2', text)

    # Separa CamelCase ou colagens óbvias com números
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'([A-Za-z])(\d)', r'\1 \2', text)
    text = re.sub(r'(\d)([A-Za-z])', r'\1 \2', text)
    
    if not wordninja:
        return text

    tokens = text.split()
    fixed_tokens = []
    
    for token in tokens:
        clean_tok = re.sub(r'[^a-zA-Z]', '', token)
        # Se a palavra for longa e não for termo reservado
        if len(clean_tok) >= 10 and clean_tok.upper() not in PRESERVE_WORDS:
            splits = wordninja.split(clean_tok)
            if len(splits) >= 2:
                if token.isupper():
                    fixed_tok = ' '.join(s.upper() for s in splits)
                elif token.islower():
                    fixed_tok = ' '.join(s.lower() for s in splits)
                else:
                    fixed_tok = ' '.join(splits)
                fixed_tokens.append(fixed_tok)
                continue
        fixed_tokens.append(token)
        
    return ' '.join(fixed_tokens)

def should_merge_lines(b1, b2):
    """Verifica se duas caixas de OCR pertencem ao MESMO balão, evitando fusão de balões adjacentes."""
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
    
    min_h = max(min(h1, h2), 1)
    max_h = max(h1, h2)
    min_w = max(min(w1, w2), 1)
    max_w = max(w1, w2)
    
    if max_h > min_h * 2.8 and (gap_y > 15 or gap_x > 15):
        return False

    # 1. TEXTO HORIZONTAL (Ocidental / Inglês / Coreano horizontal)
    if w1 >= h1 or w2 >= h2:
        # Se NÃO há sobreposição horizontal, NUNCA juntar (são balões ou colunas diferentes)
        if overlap_x <= 0:
            return False
            
        cx1 = (x1_min + x1_max) / 2
        cx2 = (x2_min + x2_max) / 2
        center_dist_x = abs(cx1 - cx2)
        overlap_ratio_x = overlap_x / min_w
        
        # Devem estar bem alinhados horizontalmente (linhas do mesmo balão)
        if (overlap_ratio_x >= 0.40 and center_dist_x <= max_w * 0.45) or overlap_ratio_x >= 0.65:
            if gap_y <= max(max_h * 1.30, 28):
                return True
                
        return False

    # 2. TEXTO VERTICAL (Mangá Japonês / Chinês vertical)
    if h1 > w1 and h2 > w2:
        # Se NÃO há sobreposição vertical, NUNCA juntar (são balões verticais distintos)
        if overlap_y <= 0:
            return False
            
        cy1 = (y1_min + y1_max) / 2
        cy2 = (y2_min + y2_max) / 2
        center_dist_y = abs(cy1 - cy2)
        overlap_ratio_y = overlap_y / min_h
        
        if (overlap_ratio_y >= 0.40 and center_dist_y <= max_h * 0.45) or overlap_ratio_y >= 0.65:
            if gap_x <= max(max_w * 1.5, 32):
                return True
                
        return False
        
    return False

def smart_group_bubbles(blocks):
    """Agrupa linhas de texto próximas usando conectividade de grafos, suportando leitura oriental e ocidental."""
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
        full_text = repair_glued_text(full_text)
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

def clean_speech_bubble(img, box):
    """Limpeza inteligente de balões: remove 100% de textos pretos, coloridos e corações sem danificar a borda."""
    xmin, ymin, xmax, ymax = box
    bw = xmax - xmin
    bh = ymax - ymin
    ih, iw = img.shape[:2]
    
    pad_x = max(int(bw * 0.40), 45)
    pad_y = max(int(bh * 0.40), 45)
    
    x0 = max(0, xmin - pad_x)
    y0 = max(0, ymin - pad_y)
    x1 = min(iw, xmax + pad_x)
    y1 = min(ih, ymax + pad_y)
    
    roi = img[y0:y1, x0:x1]
    if roi.size == 0:
        return
        
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    
    # Verifica se a região tem fundo branco preponderante (balão de fala)
    white_ratio = np.mean(gray > 200)
    if white_ratio > 0.45:
        # Detecta textos pretos, coloridos (rosa/vermelho/azul) e corações
        is_text = (gray < 175) | ((hsv[:, :, 1] > 25) & (gray < 238))
        text_mask = is_text.astype(np.uint8) * 255
        
        contours, _ = cv2.findContours(text_mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        clean_mask = np.zeros_like(text_mask)
        rh, rw = gray.shape
        
        for c in contours:
            cx, cy, cw, ch = cv2.boundingRect(c)
            # Se o contorno encosta na borda externa do ROI, pode ser a borda do balão ou arte externa
            touches_margin = (cx <= 1 or cy <= 1 or (cx + cw) >= rw - 1 or (cy + ch) >= rh - 1)
            # Mas se está dentro do núcleo da caixa de texto detectada pelo OCR, é texto garantido!
            in_text_core = (cx >= (xmin - x0 - 6) and (cx + cw) <= (xmax - x0 + 6) and
                            cy >= (ymin - y0 - 6) and (cy + ch) <= (ymax - y0 + 6))
            if in_text_core or not touches_margin:
                cv2.drawContours(clean_mask, [c], -1, 255, -1)
                
        clean_mask = cv2.dilate(clean_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        roi[clean_mask > 0] = (255, 255, 255)
    else:
        # Inpainting seguro para texturas, retículas e arte de fundo
        is_text = (gray < 165) | ((hsv[:, :, 1] > 35) & (gray < 235))
        mask = cv2.dilate(is_text.astype(np.uint8) * 255, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=2)
        img[y0:y1, x0:x1] = cv2.inpaint(roi, mask, inpaintRadius=4, flags=cv2.INPAINT_TELEA)

def wrap_text_to_width(draw, text, font, max_w):
    """Quebra texto por palavras usando largura em pixels real da fonte (sem deformações)."""
    paragraphs = text.split('\n')
    all_lines = []
    for p in paragraphs:
        words = p.split()
        if not words:
            continue
        curr = []
        for w in words:
            test_l = ' '.join(curr + [w])
            bbox = draw.textbbox((0, 0), test_l, font=font)
            if (bbox[2] - bbox[0]) <= max_w:
                curr.append(w)
            else:
                if curr:
                    all_lines.append(' '.join(curr))
                    curr = [w]
                else:
                    all_lines.append(w)
                    curr = []
        if curr:
            all_lines.append(' '.join(curr))
    return all_lines

def fit_text_to_box(draw, text, max_w, max_h, font_path):
    """Ajusta proporcionalmente o tamanho da fonte e quebras de linha para preencher o balão esteticamente."""
    # Limpa emojis e símbolos não suportados pela fonte TTF para evitar retângulos 'tofu'
    text = re.sub(r'[\u2660-\u2667\u2764\ufe0f♥❤♡★☆]', '', text).strip()
    words = text.split()
    if not words:
        return ImageFont.truetype(font_path, 12), []
        
    ideal_max = int(min(max_h * 0.45, max_w * 0.35, 68))
    max_font_size = max(24, min(ideal_max, 68))
    
    for font_size in range(max_font_size, 9, -2):
        font = ImageFont.truetype(font_path, font_size)
        line_h = (draw.textbbox((0, 0), "Ag", font=font)[3] - draw.textbbox((0, 0), "Ag", font=font)[1]) * 1.22
        max_possible_lines = int(max_h / line_h)
        if max_possible_lines < 1:
            continue
            
        greedy_lines = wrap_text_to_width(draw, text, font, max_w)
        if len(greedy_lines) <= max_possible_lines:
            # Se a última linha tiver apenas 1 palavra curta pendurada, tenta distribuir de forma equilibrada (formato balão)
            best_lines = greedy_lines
            if len(greedy_lines) > 1 and len(greedy_lines[-1].split()) == 1 and len(greedy_lines[-1]) < 6:
                target_w = max_w * 0.88
                balanced = []
                b_cur = []
                for w in words:
                    test_l = ' '.join(b_cur + [w])
                    w_len = draw.textbbox((0, 0), test_l, font=font)[2] - draw.textbbox((0, 0), test_l, font=font)[0]
                    if w_len <= target_w or (not b_cur and w_len <= max_w):
                        b_cur.append(w)
                    else:
                        if b_cur:
                            balanced.append(' '.join(b_cur))
                            b_cur = [w]
                        else:
                            balanced.append(w)
                            b_cur = []
                if b_cur:
                    balanced.append(' '.join(b_cur))
                if len(balanced) <= max_possible_lines and all((draw.textbbox((0, 0), l, font=font)[2] - draw.textbbox((0, 0), l, font=font)[0]) <= max_w for l in balanced):
                    best_lines = balanced
                    
            return font, best_lines
            
    # Fallback dinâmico usando tamanho 10 e wrapping proporcional (nunca width=16 rígido)
    font = ImageFont.truetype(font_path, 10)
    fallback_lines = wrap_text_to_width(draw, text, font, max_w)
    return font, fallback_lines

def check_ollama_available(prefer_uncensored=False):
    """Verifica se o servidor Ollama local está ativo e seleciona o modelo ideal priorizando fluência em PT-BR."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                models = [m["name"] for m in data.get("models", [])]
                if models:
                    # Modelos multilíngues de alta qualidade comprovada em Português
                    best_pt_models = ["llama3.1", "qwen2.5", "mistral", "gemma2", "llama3.2", "llama3"]
                    selected_model = None
                    
                    # 1. Procura primeiro modelos limpos oficiais (evita viés de chatbot/alucinação de 'dolphin')
                    for pref in best_pt_models:
                        for m in models:
                            if pref in m.lower() and "dolphin" not in m.lower():
                                selected_model = m
                                break
                        if selected_model:
                            break
                            
                    # 2. Se não encontrar sem dolphin, busca qualquer um que coincida
                    if not selected_model:
                        for pref in best_pt_models:
                            for m in models:
                                if pref in m.lower():
                                    selected_model = m
                                    break
                            if selected_model:
                                break
                                
                    if not selected_model:
                        selected_model = models[0]
                        
                    # Executa aquecimento (warm-up) e ativa keep_alive: 60m para pré-carregar o modelo na VRAM
                    print(f"[*] Pré-carregando modelo local '{selected_model}' na VRAM (keep_alive: 60m)...")
                    try:
                        warm_req = urllib.request.Request(
                            "http://localhost:11434/api/chat",
                            data=json.dumps({
                                "model": selected_model,
                                "messages": [{"role": "user", "content": "oi"}],
                                "stream": False,
                                "keep_alive": "60m"
                            }).encode('utf-8'),
                            headers={'Content-Type': 'application/json'}
                        )
                        with urllib.request.urlopen(warm_req, timeout=120) as warm_resp:
                            pass
                        print(f"[+] Modelo '{selected_model}' ativo na memória com sucesso!")
                    except Exception as we:
                        print(f"[*] Aviso no warm-up do Ollama: {we}")
                        
                    return True, selected_model
        return False, None
    except Exception:
        return False, None

def clean_ai_translation(text, original_text="", is_adult=True):
    """Higieniza rigorosamente a saída da IA: elimina notas, 'Obs:', prefixos e normaliza anatomia."""
    if not text:
        return original_text.strip()
        
    cleaned = text.strip()
    
    # 0. Detectar e ignorar mensagens de recusa de IA ou vazamentos de prompt
    refusal_markers = [
        'idioma desconhecido', 'forneça o texto original',
        'como uma inteligência artificial', 'como uma ia',
        'como um modelo de linguagem', 'não posso cumprir',
        'não posso ajudar', 'não posso atender', 'cannot fulfill', "can't fulfill",
        'você é um tradutor', 'regras obrigatórias', 'traduza o texto original',
        'como modelo de ia', 'as an ai'
    ]
    if any(rm in cleaned.lower() for rm in refusal_markers):
        sfx_try = translate_sfx_phrase(original_text)
        if sfx_try:
            return sfx_try
        norm_sfx = re.sub(r'[^A-Z]', '', original_text.upper())
        if norm_sfx in SFX_DICTIONARY:
            return SFX_DICTIONARY[norm_sfx]
        return original_text.strip()
        
    # Preservar nomes próprios e créditos de scanlators sem deixar a IA alucinar
    clean_lower = original_text.strip().lower()
    if clean_lower in ['alex', 'takuya', 'valirius', 'pr', 'alex yasa', 'omega scans', 'qmega scans', 'amega scans']:
        return original_text.strip()
    if 'discord.gg' in clean_lower or '@gmail.com' in clean_lower:
        return original_text.strip()

    # Se a saída for o próprio texto do prompt repetido
    for p_leak in ['você é um tradutor', 'traduza fielmente', 'regras obrigatórias']:
        if p_leak in cleaned.lower() and len(cleaned) > 80 and len(original_text) < 30:
            sfx_try = translate_sfx_phrase(original_text)
            if sfx_try:
                return sfx_try
            norm_sfx = re.sub(r'[^A-Z]', '', original_text.upper())
            if norm_sfx in SFX_DICTIONARY:
                return SFX_DICTIONARY[norm_sfx]
            return original_text.strip()

    # 1. Eliminar saudações e conversas de assistente ('Vem lá, meu amigo...', 'Estou traduzindo...', 'Aqui está...')
    cleaned = re.sub(r'(?i)^(?:ol[áa]|aqui\s+est[áa]|com\s+certeza|vamos\s+traduzir|estou\s+traduzindo|com\s+base\s+nas\s+regras|veja\s+bem|beleza|entendi|ok|vem\s+l[áa],?\s+meu\s+amigo!?).*?[:\n]+', '', cleaned).strip()

    # Extração se o modelo formatou com 'Tradução: "..."'
    inline_trad = re.search(r'(?:a\s+tradu[çc][ãa]o(?:\s+para\s+.*?)?\s+[eé]\s*:?\s*)["“\']([^"”\']+)["”\']', cleaned, flags=re.IGNORECASE)
    if inline_trad:
        cleaned = inline_trad.group(1).strip()
    else:
        trad_matches = list(re.finditer(r'(?:texto\s+traduzido|tradu[çc][ãa]o(?:\s+(?:para\s+)?(?:o\s+)?(?:portugu[êe]s(?:\s+do\s+brasil)?|pt-br))?)\s*:\s*(.*)', cleaned, flags=re.IGNORECASE))
        if trad_matches:
            for m in reversed(trad_matches):
                candidate = m.group(1).strip()
                candidate = re.split(r'\n+\s*(?:texto\s+original|original)\s*:\s*', candidate, flags=re.IGNORECASE)[0].strip()
                if candidate:
                    cleaned = candidate
                    break

    # 2. Remover metadados, notas de rodapé, 'Obs:' e explicações
    cleaned = re.sub(r'(?is)\bobs(?:\.|erva[çc][ãa]o)?\s*:.*$', '', cleaned).strip()
    cleaned = re.sub(r'(?is)\bsugest[ãa]o\s*:.*$', '', cleaned).strip()
    cleaned = re.sub(r'(?is)\bnota(?:\s+de\s+tradu[çc][ãa]o)?\s*:.*$', '', cleaned).strip()
    cleaned = re.sub(r'(?i)^[a-z0-9_-]+,\s+que\s+[eé]\s+um\s+termo.*$', '', cleaned).strip()

    # 3. Remover parênteses contendo explicações da IA ou meta-comentários
    cleaned = re.sub(r'\[\s*(?:em\s+)?(?:PT-BR|PT|BR)\s*\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\(\s*(?:em\s+)?(?:PT-BR|PT|BR)\s*\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\([^\)]*(?:sugest|express|g[íi]ria|significa|regras|contexto|portugu[êe]s|afeto|fluidez|gozou|surpresa|nega[çc][ãa]o|nunca|ingl[êe]s|japon[êe]s|traduz|mistur)[^\)]*\)', '', cleaned, flags=re.IGNORECASE)
    
    # 4. Limpar linhas vazias ou cabeçalhos soltos
    lines = cleaned.split('\n')
    valid_lines = []
    for line in lines:
        l_str = line.strip()
        if re.match(r'^(?:texto\s+original|original|l[íi]ngua\s+identificada|tradu[çc][ãa]o|texto\s+traduzido|resposta)\s*:', l_str, flags=re.IGNORECASE):
            continue
        if re.match(r'^(?:traduzindo\s+o\s+texto|vou\s+traduzir|aqui\s+est[áa])', l_str, flags=re.IGNORECASE):
            continue
        valid_lines.append(l_str)
    cleaned = '\n'.join(valid_lines).strip()

    # 5. Se houver formato "ORIGINAL -> TRADUÇÃO"
    if '->' in cleaned:
        cleaned = cleaned.split('->')[-1].strip()

    # 6. Remover aspas externas
    cleaned = cleaned.strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1].strip()

    # 7. Remover parênteses e colchetes órfãos
    cleaned = re.sub(r'[\(\[\{]$', '', cleaned).strip()
    cleaned = re.sub(r'^[\)\]\}]', '', cleaned).strip()

    # 8. Correção de termos anatômicos e gírias de mangá
    def _preserve_case(pattern, repl, target_str):
        def _repl_cb(m):
            w = m.group(0)
            if w.isupper():
                return repl.upper()
            elif w[0].isupper():
                return repl.capitalize()
            return repl.lower()
        return re.sub(pattern, _repl_cb, target_str, flags=re.IGNORECASE)

    orig_lower = original_text.lower() if original_text else ""
    if is_adult:
        # Pussy / Cunt -> Buceta (NUNCA pau ou pica)
        if re.search(r'\b(pussy|cunt|vagina|slit|clit|clitoris)\b', orig_lower):
            cleaned = _preserve_case(r'\bpica\b', 'buceta', cleaned)
            cleaned = _preserve_case(r'\bpau\b', 'buceta', cleaned)
            cleaned = _preserve_case(r'\bpiroca\b', 'buceta', cleaned)
            cleaned = _preserve_case(r'\bcaralho\b', 'buceta', cleaned)

        # Cock / Dick / Shaft / Peepee -> Pau / Pinto (NUNCA peito ou pé de peixe)
        if re.search(r'\b(peepee|pecker|penis|cock|dick|shaft|wiener)\b', orig_lower):
            cleaned = _preserve_case(r'\bsua\s+bucetinha\b', 'seu pintinho', cleaned)
            cleaned = _preserve_case(r'\bsua\s+buceta\b', 'seu pau', cleaned)
            cleaned = _preserve_case(r'\bbucetinha\b', 'pintinho', cleaned)
            cleaned = _preserve_case(r'\bbuceta\b', 'pau', cleaned)
            cleaned = _preserve_case(r'\bseu\s+peito\b', 'seu pau', cleaned)
            cleaned = _preserve_case(r'\bseus\s+peitos\b', 'seu pau', cleaned)
            cleaned = _preserve_case(r'\bpeito\b', 'pau', cleaned)
            cleaned = _preserve_case(r'\bp[ée]\s+de\s+peixe\b', 'pintinho', cleaned)

        # Striped Panties / Panties -> Calcinha listrada / Calcinha (NUNCA cuecas ou estriadas)
        if re.search(r'\bstriped\s+panties\b', orig_lower):
            cleaned = _preserve_case(r'\bcuecas?\s+estriadas?\b', 'calcinha listrada', cleaned)
            cleaned = _preserve_case(r'\bcueca\s+listrada\b', 'calcinha listrada', cleaned)
        if re.search(r'\bpanties\b', orig_lower):
            cleaned = _preserve_case(r'\bcuecas?\b', 'calcinha', cleaned)

        # Fiancée -> Noiva (NUNCA noivo)
        if re.search(r'\bfianc[eé]+e?\b', orig_lower):
            cleaned = _preserve_case(r'\bnoivo\b', 'noiva', cleaned)

        # Came inside -> Gozou dentro / Gozei dentro (NUNCA entrei na mamãe)
        if re.search(r'\bcame\s+inside\b', orig_lower):
            cleaned = _preserve_case(r'\bentrei\s+(?:na|dentro\s+da)\b', 'gozei dentro da', cleaned)
            cleaned = _preserve_case(r'\bentrou\s+(?:na|dentro\s+da)\b', 'gozou dentro da', cleaned)
            cleaned = _preserve_case(r'\bentrou\s+na\s+boca\b', 'gozou dentro', cleaned)
            cleaned = _preserve_case(r'\bveio\s+para\s+dentro\b', 'gozou dentro', cleaned)
            cleaned = _preserve_case(r'\bveio\s+dentro\b', 'gozou dentro', cleaned)

        # Honey -> Amor / Querido (NUNCA doce-pessoa)
        if re.search(r'\bhoney\b', orig_lower):
            cleaned = _preserve_case(r'\bdoce-pes[oa]a?\b', 'querido', cleaned)
            cleaned = _preserve_case(r'\bdoce\s+pessoa\b', 'querido', cleaned)

        # Mommy -> Mamãe (NUNCA mamã de Portugal)
        if re.search(r'\bmommy\b', orig_lower):
            cleaned = _preserve_case(r'\bmam[ãa]\b', 'mamãe', cleaned)

        # Such a bad boy -> Que garoto levado / garoto mau
        if re.search(r'such\s+a\s+bad\s+boy', orig_lower):
            cleaned = _preserve_case(r't[áa]\s+t[ãa]o\s+ruim\s+assim.*', 'Que garoto levado...', cleaned)

        # That would be bad -> Isso seria ruim
        if re.search(r'that\s+would\s+be\s+bad', orig_lower):
            cleaned = _preserve_case(r'uau,\s+que\s+coisa!?', 'Isso seria ruim!', cleaned)

        # Pregnant -> Grávida (NUNCA gestante)
        if re.search(r'\bpregnant\b', orig_lower):
            cleaned = _preserve_case(r'\bgestante\b', 'grávida', cleaned)

        # Condom -> Camisinha (NUNCA condomínio)
        if re.search(r'\bcondom\b', orig_lower):
            cleaned = _preserve_case(r'\bcondom[íi]nio\b', 'camisinha', cleaned)

        # Fapping / Jerking off -> Batendo uma / Masturbação (NUNCA fornicando)
        if re.search(r'\b(fap|fapping|jerking\s*off)\b', orig_lower):
            cleaned = _preserve_case(r'\bfornicando\b', 'batendo uma', cleaned)
            cleaned = _preserve_case(r'\bfornica[çc][ãa]o\b', 'masturbação', cleaned)

        # Ooze / Leak -> Escorrendo / Vazando (NUNCA exsudado)
        cleaned = _preserve_case(r'\bexsudad[oa]s?\b', 'escorrendo', cleaned)
        cleaned = _preserve_case(r'\bexsudando\b', 'escorrendo', cleaned)

        # Nipples / Nips -> Mamilos (NUNCA pelos)
        if re.search(r'\b(nipple|nipples|nips|nip)\b', orig_lower):
            cleaned = _preserve_case(r'\bpelos\b', 'mamilos', cleaned)

    cleaned = _preserve_case(r'\bperfecto\b', 'perfeito', cleaned)
    cleaned = _preserve_case(r'\btacto\b', 'tato', cleaned)
    
    # 9. Proteção para gemidos/sons curtos (evita que um 'NGH!' vire um parágrafo)
    orig_stripped = original_text.strip()
    if len(orig_stripped) <= 6 and len(cleaned.split()) > 3:
        cleaned = cleaned.split()[0].strip()

    cleaned = re.sub(r'[ \t]+', ' ', cleaned).strip()
    return cleaned if cleaned else original_text.strip()

def translate_with_ollama(text, model_name, is_adult=True):
    """Traduz texto usando a API nativa /api/chat do Ollama com prompt estrito anti-alucinação e temperature 0.0."""
    url = "http://localhost:11434/api/chat"
    
    clean_t = text.strip()
    # Checagem SFX prioritária
    sfx_res = translate_sfx_phrase(clean_t)
    if sfx_res:
        return sfx_res
    
    if is_adult:
        sys_prompt = """Você é um tradutor literário profissional de mangás adultos e scanlations para Português do Brasil (PT-BR).
Traduza fielmente o diálogo original com máxima naturalidade coloquial e fluidez brasileira, respeitando o tom da cena (romance, ecchi, diálogos picantes ou adultos).

REGRAS OBRIGATÓRIAS:
1. Responda APENAS com o texto traduzido final em PT-BR. NUNCA converse, NUNCA introduza com "Aqui está", NUNCA adicione explicações, notas de tradutor ou parênteses de justificativa.
2. NUNCA use palavras em espanhol (ex: use sempre 'perfeito', NUNCA 'perfecto'; 'vocês', NUNCA 'vosotros').
3. Adapte expressões e gírias com naturalidade autêntica brasileira (ex: 'panties' -> 'calcinha'; 'striped panties' -> 'calcinha listrada'; 'cock/penis' -> 'pau/pinto'; 'came inside' -> 'gozou dentro'; 'honey' -> 'amor/querido'; 'fiancée' -> 'noiva').
4. Mantenha nomes de personagens inalterados (Norun, Misha, Chise, Lovemea, Ichiri).
5. Mantenha a pontuação dramática de mangá (exclamações, interrogações e reticências)."""
    else:
        sys_prompt = """Você é um tradutor literário profissional de mangás e quadrinhos japoneses para Português do Brasil (PT-BR).
Traduza fielmente o texto original com máxima naturalidade coloquial e fluidez brasileira.

REGRAS OBRIGATÓRIAS:
1. Responda APENAS com o texto traduzido final em PT-BR. NUNCA converse, NUNCA adicione saudações, notas ou explicações.
2. NUNCA use palavras em espanhol.
3. Mantenha nomes próprios inalterados (Norun, Misha, Chise, Lovemea).
4. Mantenha a pontuação dramática típica de mangás (!?, !!, ..., ~)."""

    data = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Traduza fielmente para PT-BR:\n\n{text}"}
        ],
        "stream": False,
        "keep_alive": "60m",
        "options": {
            "temperature": 0.0,
            "num_predict": 256
        }
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode('utf-8'))
            resp = result.get("message", {}).get("content", "").strip()
            return clean_ai_translation(resp, original_text=text, is_adult=is_adult)
    except Exception:
        return None

def translate_batch_texts(text_list, src_lang="auto", is_adult=True):
    """Traduz lista de textos usando Ollama local (prioritário, offline, sem erros 401) com fallback para Google."""
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
    print(f"[*] Modo de Conteúdo: {'ADULTO / +18 (Sem Censura)' if is_adult else 'NORMAL / PADRAO'}")
    
    ollama_active, ollama_model = check_ollama_available(prefer_uncensored=is_adult)
    if ollama_active:
        print(f"[+] OLLAMA ATIVO! Motor de IA Local ({ollama_model}) selecionado para máxima privacidade e precisão.")
    else:
        print(f"[*] Ollama não detectado. Usando modo de tradução em nuvem (MyMemory/Google).")
    
    translator = MyMemoryTranslator(source=src_lang, target='pt-BR')
    results = []
    
    for i, t in enumerate(tqdm(text_list, desc="Traduzindo", unit="balão")):
        clean_t = t.strip()
        if not clean_t or clean_t in ("...", "…", "!!", "!?"):
            results.append(clean_t)
            continue
            
        # 0. Checagem SFX composta ou simples direta
        sfx_res = translate_sfx_phrase(clean_t)
        if sfx_res:
            results.append(sfx_res)
            continue
            
        norm_sfx = re.sub(r'[^A-Z]', '', clean_t.upper())
        if norm_sfx in SFX_DICTIONARY:
            results.append(SFX_DICTIONARY[norm_sfx])
            continue
            
        res = None
        
        # 1. Tenta IA Local (Ollama)
        if ollama_active:
            res = translate_with_ollama(clean_t, ollama_model, is_adult=is_adult)
            
        # 2. Fallback Nuvem
        if not res:
            try:
                res = translator.translate(clean_t)
                if "MYMEMORY WARNING" in res:
                    res = GoogleTranslator(source='auto', target='pt').translate(clean_t)
                time.sleep(0.3)
            except Exception:
                try:
                    time.sleep(0.8)
                    res = GoogleTranslator(source='auto', target='pt').translate(clean_t)
                except Exception:
                    res = clean_t
                    
        if res:
            res = clean_ai_translation(res, original_text=clean_t, is_adult=is_adult)
            
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
    """Analisa imagens para determinar se o conteúdo é ocidental/latino."""
    try:
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

def is_ocr_noise(text, score):
    """Filtra ruídos de OCR para não apagar detalhes de arte ou fundos."""
    t = text.strip()
    if not t:
        return True
    try:
        sc = float(score)
    except Exception:
        sc = 1.0
    if sc < 0.45:
        return True
    has_letters = bool(re.search(r'[a-zA-Z\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]', t))
    if not has_letters and sc < 0.75:
        return True
    if len(t) <= 1 and sc < 0.65:
        return True
    if len(set(t)) <= 2 and len(t) >= 4 and sc < 0.75:
        return True
    return False

def generate_rapidocr_json(manga_dir, output_json_path):
    """Extrai textos usando RapidOCR com pré-processamento que realça textos coloridos (ex: rosa/vermelho)."""
    import glob
    
    img_files = glob.glob(os.path.join(manga_dir, "*.*"))
    img_files = [f for f in img_files if f.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.bmp'))]
    img_files.sort(key=natural_sort_key)
    
    engine = RapidOCR()
    pages = []
    
    print("[*] Extraindo textos usando RapidOCR (com detecção avançada de textos coloridos)...")
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
            
        # Gera versão com canal mínimo (min_ch): faz textos rosa, vermelho e azul terem alto contraste
        min_ch = img_cv.min(axis=2)
        min_bgr = cv2.cvtColor(min_ch, cv2.COLOR_GRAY2BGR)
        
        res, _ = engine(min_bgr)
        blocks_for_grouping = []
        if res:
            for box_data in res:
                coords = box_data[0]
                text = box_data[1]
                score = float(box_data[2]) if len(box_data) > 2 else 1.0
                
                if is_ocr_noise(text, score):
                    continue
                    
                xs = [p[0] for p in coords]
                ys = [p[1] for p in coords]
                
                clean_ocr_text = repair_glued_text(text, src_lang="en-US")
                blocks_for_grouping.append({
                    "box": [min(xs), min(ys), max(xs), max(ys)],
                    "text": clean_ocr_text
                })
                
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

def is_credits_page(bubbles):
    """Detecta páginas de créditos/recrutamento de scanlation para evitar destruição de arte."""
    full_text = " ".join([b.get("combined_text", "") for b in bubbles]).lower()
    markers = [
        "scanlation", "scans", "discord.gg", "patreon", "recruiting",
        "raw provider", "typesetter", "cleaner", "proofreader",
        "redrawn by", "translated by", "join us", "donation",
        "commissionrequests", "hiringpaid", "omega scans", "qmega scans", "amega scans"
    ]
    matched = sum(1 for m in markers if m in full_text)
    return matched >= 1

def process_manga(manga_dir, target_lang="pt-BR", ocr_mode="auto", force_ocr=False, is_adult=True):
    manga_dir = os.path.abspath(manga_dir.strip('\"\''))
    if not os.path.exists(manga_dir) or not os.path.isdir(manga_dir):
        print(f"[!] Erro: Caminho inválido ({manga_dir})")
        return False
        
    manga_name = os.path.basename(manga_dir)
    clean_name = manga_name.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip()
    
    # 0. Define o diretório de destino
    base_drive_dir = BASE_OUTPUT_DIR
    try:
        os.makedirs(base_drive_dir, exist_ok=True)
    except Exception as e:
        print(f"[!] Aviso: Não foi possível acessar pasta de destino padrão: {e}")
        base_drive_dir = os.path.dirname(manga_dir)
        
    output_dir = os.path.join(base_drive_dir, f"{clean_name} [PT-BR]")
    os.makedirs(output_dir, exist_ok=True)
    
    cache_dir = os.path.join(output_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    
    import uuid
    temp_render_dir = os.path.join(os.environ.get("TEMP", "C:\\temp"), f"manga_render_tmp_{uuid.uuid4().hex[:8]}")
    os.makedirs(temp_render_dir, exist_ok=True)
    
    print("=" * 60)
    print(f"[*] INICIANDO TRADUCAO DO MANGA")
    print(f"[*] Pasta de Entrada: {manga_dir}")
    print(f"[*] Pasta de Destino: {output_dir}")
    print("=" * 60)
    
    img_files = [f for f in os.listdir(manga_dir) if f.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.bmp'))]
    img_files.sort(key=natural_sort_key)
    
    if not img_files:
        print("[!] Nenhuma imagem encontrada na pasta especificada.")
        return False
        
    print(f"[+] {len(img_files)} imagens encontradas.")
    
    parent_dir = os.path.dirname(manga_dir)
    mokuro_path = os.path.join(cache_dir, manga_name + ".mokuro")
    cache_file = os.path.join(cache_dir, "translation_cache.json")
    html_dest = os.path.join(cache_dir, manga_name + "_mokuro.html")
    
    if force_ocr:
        print("[!] LIMPEZA DE CACHE ATIVADA: Regerando OCR e traduções...")
        if os.path.exists(cache_dir):
            try: shutil.rmtree(cache_dir)
            except Exception: pass
        os.makedirs(cache_dir, exist_ok=True)

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

    needs_new_ocr = True
    if not force_ocr and os.path.exists(mokuro_path):
        try:
            with open(mokuro_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            file_version = str(existing_data.get("version", ""))
            is_file_rapidocr = (file_version == "rapidocr")
            pages = existing_data.get("pages", [])
            total_blocks = sum(len(p.get("blocks", [])) for p in pages)
            
            if total_blocks > 0 and ((use_rapidocr and is_file_rapidocr) or (not use_rapidocr and not is_file_rapidocr)):
                print(f"[+] Cache OCR ({expected_engine.upper()}) encontrado ({total_blocks} balões). Reutilizando...")
                needs_new_ocr = False
            else:
                os.remove(mokuro_path)
                needs_new_ocr = True
        except Exception:
            needs_new_ocr = True

    if needs_new_ocr:
        if use_rapidocr:
            print("[+] Executando RapidOCR com detecção de textos coloridos...")
            generate_rapidocr_json(manga_dir, mokuro_path)
        else:
            print("[*] Executando motor Asiático especializado (Mokuro)...")
            import subprocess
            try:
                subprocess.run([sys.executable, "-m", "mokuro", manga_dir, "--disable_confirmation"], check=True)
                temp_mokuro = os.path.join(parent_dir, manga_name + ".mokuro")
                if os.path.exists(temp_mokuro):
                    shutil.move(temp_mokuro, mokuro_path)
            except subprocess.CalledProcessError as e:
                print(f"[!] Erro ao executar o Mokuro: {e}")
                return False

    if not os.path.exists(mokuro_path):
        print("[!] Arquivo de texto OCR não foi gerado. Falha na leitura.")
        return False

    with open(mokuro_path, "r", encoding="utf-8") as f:
        mokuro_data = json.load(f)
        
    pages_data = []
    all_raw_texts = []
    font_path = get_best_font()
    
    for idx, page_info in enumerate(mokuro_data.get("pages", [])):
        fname = os.path.basename(page_info.get("img_path", ""))
        bubbles = []
        for blk in page_info.get("blocks", []):
            xmin, ymin, xmax, ymax = [int(round(float(v))) for v in blk.get("box", [0, 0, 0, 0])]
            is_vertical = blk.get("vertical", True)
            lines = blk.get("lines", [])
            text = " ".join(lines).strip()
            
            if not text:
                continue
                
            all_raw_texts.append(text)
            bubbles.append({
                "box": [xmin, ymin, xmax, ymax],
                "raw_boxes": [[xmin, ymin, xmax, ymax]],
                "lines": lines,
                "combined_text": text,
                "is_vertical": is_vertical
            })
            
        pages_data.append({
            "page": idx + 1,
            "img": fname,
            "bubbles": bubbles
        })
            
    # 3. Detectar idioma e traduzir com cache
    src_lang = detect_language_from_samples(all_raw_texts)
    print(f"[+] Idioma predominante detectado: '{src_lang.upper()}'")
    
    cache = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as cf:
                raw_cache = json.load(cf)
            # Purga automaticamente entradas corrompidas por alucinações ou vazamentos de IA
            corrupt_markers = [
                'delfim perverso', 'o gato está sentado', 'vem lá, meu amigo',
                'estou traduzindo o texto', 'com base nas regras', 'ok, vamos traduzir',
                'traduza o texto original', 'como uma inteligência artificial', 'regras obrigatórias'
            ]
            for k, v in raw_cache.items():
                if not any(cm in v.lower() for cm in corrupt_markers):
                    cache[k] = v
        except Exception:
            pass
            
    texts_to_translate = []
    text_mapping = []
    
    for p_idx, p in enumerate(pages_data):
        # Se for página de créditos, não desperdiça tokens/chamadas
        if is_credits_page(p["bubbles"]):
            continue
            
        for b_idx, b in enumerate(p["bubbles"]):
            orig_text = b["combined_text"].strip()
            if orig_text not in cache:
                texts_to_translate.append(orig_text)
            text_mapping.append((p_idx, b_idx, orig_text))
            
    if texts_to_translate:
        print(f"[*] Traduzindo {len(texts_to_translate)} balões de fala...")
        translated_results = translate_batch_texts(texts_to_translate, src_lang=src_lang, is_adult=is_adult)
        for orig, trans in zip(texts_to_translate, translated_results):
            cache[orig] = clean_ai_translation(trans, original_text=orig, is_adult=is_adult)
            
        try:
            with open(cache_file, "w", encoding="utf-8") as cf:
                json.dump(cache, cf, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[!] Aviso: Não foi possível salvar o cache: {e}")
            
    for p_idx, b_idx, orig_text in text_mapping:
        cached_val = cache.get(orig_text, orig_text)
        pages_data[p_idx]["bubbles"][b_idx]["translated_text"] = clean_ai_translation(cached_val, original_text=orig_text, is_adult=is_adult)
        
    # 4. Diagramação e Inpainting
    print(f"[*] Iniciando limpeza profissional de balões e diagramação...")
    for idx, p in enumerate(tqdm(pages_data, desc="Diagramação", unit="pág")):
        img_name = p["img"]
        src_path = os.path.join(manga_dir, img_name)
        
        try:
            with open(src_path, "rb") as f:
                img_array = np.asarray(bytearray(f.read()), dtype=np.uint8)
                img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        except Exception:
            img_cv = None
            
        if img_cv is None:
            continue
            
        h_img, w_img = img_cv.shape[:2]
        cleaned = img_cv.copy()
        bubbles = p.get("bubbles", [])
        
        # Páginas de créditos são preservadas intactas
        if is_credits_page(bubbles):
            out_file = os.path.join(temp_render_dir, os.path.splitext(img_name)[0] + ".jpg")
            img_pil = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
            img_pil.save(out_file, quality=95)
            continue
        
        # 4.1 Limpar balões com algoritmo seguro
        for b in bubbles:
            clean_speech_bubble(cleaned, b["box"])
                
        # 4.2 Desenhar texto traduzido com Comic Sans MS Bold
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

            sub_roi = cleaned[max(0, ymin):min(h_img, ymax), max(0, xmin):min(w_img, xmax)]
            is_white_bg = True
            if sub_roi.size > 0:
                is_white_bg = np.mean(cv2.cvtColor(sub_roi, cv2.COLOR_BGR2GRAY) > 200) > 0.45

            safe_cx = cx
            safe_cy = cy
            target_w = bw
            target_h = max(bh * 1.20, 50)

            if is_white_bg:
                # Detecta limites do balão branco para nunca desenhar sobre as bordas pretas
                gray_c = cv2.cvtColor(cleaned, cv2.COLOR_BGR2GRAY)
                icx, icy = int(np.clip(cx, 0, w_img - 1)), int(np.clip(cy, 0, h_img - 1))
                if gray_c[icy, icx] > 190:
                    b_left = icx
                    while b_left > 0 and gray_c[icy, b_left] > 185: b_left -= 1
                    b_right = icx
                    while b_right < w_img - 1 and gray_c[icy, b_right] > 185: b_right += 1
                    b_top = icy
                    while b_top > 0 and gray_c[b_top, icx] > 185: b_top -= 1
                    b_bottom = icy
                    while b_bottom < h_img - 1 and gray_c[b_bottom, icx] > 185: b_bottom += 1

                    pad = 10
                    safe_min_x = b_left + pad
                    safe_max_x = b_right - pad
                    if safe_max_x > safe_min_x + 30:
                        safe_cx = (safe_min_x + safe_max_x) / 2
                        safe_w = safe_max_x - safe_min_x
                        target_w = min(safe_w, max(bw * 1.05, 80))
                    else:
                        target_w = bw

                    safe_min_y = b_top + pad
                    safe_max_y = b_bottom - pad
                    if safe_max_y > safe_min_y + 20:
                        safe_cy = (safe_min_y + safe_max_y) / 2
                        target_h = max(bh * 1.20, safe_max_y - safe_min_y)
                    else:
                        target_h = max(bh * 1.20, 50)
            else:
                target_w = bw
                target_h = max(bh * 1.15, 50)
            
            # Margem de segurança na largura para evitar corte nas bordas da página
            max_avail_w = min(safe_cx, w_img - safe_cx) * 2 - 20
            if max_avail_w > 60:
                target_w = min(target_w, max_avail_w)
            
            font, lines = fit_text_to_box(draw, text, target_w, target_h, font_path)
            if not lines:
                continue
                
            line_h = (draw.textbbox((0, 0), "Ag", font=font)[3] - draw.textbbox((0, 0), "Ag", font=font)[1]) * 1.22
            total_h = len(lines) * line_h
            start_y = safe_cy - (total_h / 2) + (line_h / 2)
            
            # Margem de segurança vertical para não ultrapassar topo ou base da página
            if start_y < 15:
                start_y = 15
            elif start_y + total_h > h_img - 15:
                start_y = max(15, h_img - total_h - 15)
                
            font_size = getattr(font, 'size', 20)
            stroke_w = 1 if is_white_bg else max(2, int(round(font_size * 0.08)))
            
            for line_idx, line in enumerate(lines):
                ly = start_y + (line_idx * line_h)
                draw.text((safe_cx, ly), line, font=font, fill=(0, 0, 0), stroke_width=stroke_w, stroke_fill=(255, 255, 255), anchor="mm")
                
        out_file = os.path.join(temp_render_dir, os.path.splitext(img_name)[0] + ".jpg")
        img_pil.save(out_file, quality=95)
            
    # 5. Criar leitor web responsivo
    create_html_reader(temp_render_dir, clean_name)
    
    # 6. Salvar na pasta final
    print(f"[*] Salvando arquivos traduzidos em: {output_dir}...")
    os.system(f'attrib -h -r -s "{output_dir}\\*.*" >nul 2>&1')
    
    for fname in os.listdir(temp_render_dir):
        src_p = os.path.join(temp_render_dir, fname)
        dst_p = os.path.join(output_dir, fname)
        shutil.copy2(src_p, dst_p)
        
    try:
        shutil.rmtree(temp_render_dir)
    except Exception:
        pass

    print("\n" + "=" * 60)
    print(f"[+] MANGA TRADUZIDO COM SUCESSO!")
    print(f"[+] Pasta salva: {output_dir}")
    print(f"[+] Leitor Web: {os.path.join(output_dir, 'leitor.html')}")
    print("=" * 60 + "\n")
    
    # Notificações
    try:
        import threading
        if hasattr(threading, 'excepthook'):
            threading.excepthook = lambda args: None
        from plyer import notification
        notification.notify(
            title="Mangá Traduzido! 🎉",
            message=f"'{clean_name}' foi finalizado com sucesso!",
            app_name="Manga Translator",
            timeout=10
        )
    except Exception:
        pass
        
    try:
        import requests
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
    chosen_mode = "auto"
    is_adult_flag = True
    
    if len(sys.argv) > 1:
        args = sys.argv[1:]
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
            
        if "--normal" in args or "--safe" in args:
            is_adult_flag = False
            if "--normal" in args: args.remove("--normal")
            if "--safe" in args: args.remove("--safe")
        elif "--adult" in args or "--18" in args:
            is_adult_flag = True
            if "--adult" in args: args.remove("--adult")
            if "--18" in args: args.remove("--18")
            
        target = " ".join(args).strip()
    else:
        print("=" * 60)
        print("  SISTEMA AUTOMATICO DE TRADUCAO DE MANGA [PT-BR]")
        print("=" * 60)
        target = input("Arraste ou digite o caminho da pasta do manga: ").strip()

    if target:
        process_manga(target, ocr_mode=chosen_mode, force_ocr=force_ocr_flag, is_adult=is_adult_flag)
    else:
        print("[!] Nenhuma pasta informada.")
