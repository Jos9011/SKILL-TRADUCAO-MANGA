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
import subprocess
import math
import zipfile
import unicodedata
import html
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import textwrap
import urllib.request
import urllib.error
from rapidocr_onnxruntime import RapidOCR
from deep_translator import MyMemoryTranslator, GoogleTranslator
from tqdm import tqdm

try:
    import pyphen
    _pyphen_dic = pyphen.Pyphen(lang='pt_BR')
except Exception:
    _pyphen_dic = None

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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

def load_config(cli_args=None):
    """Carrega as configurações com prioridade: CLI > Variáveis de Ambiente > config.json > Padrões."""
    cfg = {
        "provider": "auto",
        "openrouter_api_key": "",
        "openrouter_api_keys": [],
        "openrouter_model": "nvidia/nemotron-3.5-lightning:free",
        "openrouter_fallback_model": "google/gemma-4-31b-it:free",
        "ollama_host": "http://localhost:11434",
        "ollama_model": "dolphin-llama3:latest",
        "temperature": 0.0
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                cfg.update(user_cfg)
        except Exception as e:
            print(f"[*] Aviso ao ler config.json: {e}")

    # Variáveis de ambiente
    if os.environ.get("OPENROUTER_API_KEY"):
        cfg["openrouter_api_key"] = os.environ.get("OPENROUTER_API_KEY")
    if os.environ.get("OPENROUTER_API_KEYS"):
        cfg["openrouter_api_keys"] = [k.strip() for k in os.environ.get("OPENROUTER_API_KEYS").split(",") if k.strip()]
    if os.environ.get("OLLAMA_HOST"):
        cfg["ollama_host"] = os.environ.get("OLLAMA_HOST")
    if os.environ.get("TRANSLATE_PROVIDER"):
        cfg["provider"] = os.environ.get("TRANSLATE_PROVIDER")
    if os.environ.get("MANGA_TRANSLATE_MODEL"):
        cfg["ollama_model"] = os.environ.get("MANGA_TRANSLATE_MODEL")
        cfg["openrouter_model"] = os.environ.get("MANGA_TRANSLATE_MODEL")

    # Argumentos CLI
    if cli_args:
        if cli_args.get("provider"):
            cfg["provider"] = cli_args["provider"]
        if cli_args.get("model"):
            cfg["ollama_model"] = cli_args["model"]
            cfg["openrouter_model"] = cli_args["model"]
        if cli_args.get("host"):
            cfg["ollama_host"] = cli_args["host"]
        if cli_args.get("key"):
            cfg["openrouter_api_key"] = cli_args["key"]

    # Consolidação do Pool de Chaves sem duplicatas
    keys_pool = []
    raw_keys = cfg.get("openrouter_api_keys", [])
    if isinstance(raw_keys, list):
        for k in raw_keys:
            if isinstance(k, str) and k.strip() and k.strip() not in keys_pool:
                keys_pool.append(k.strip())
    elif isinstance(raw_keys, str) and raw_keys.strip():
        for k in raw_keys.split(","):
            k = k.strip()
            if k and k not in keys_pool:
                keys_pool.append(k)

    single_k = str(cfg.get("openrouter_api_key", "")).strip()
    if single_k and single_k not in keys_pool:
        keys_pool.insert(0, single_k)

    cfg["openrouter_api_keys"] = keys_pool
    if keys_pool and not cfg.get("openrouter_api_key"):
        cfg["openrouter_api_key"] = keys_pool[0]

    return cfg

FONT_DIR = os.path.join(SCRIPT_DIR, "fonts")
ANIME_ACE_FONT = os.path.join(FONT_DIR, "animeace2_reg.ttf")
KOMIKA_FONT = os.path.join(FONT_DIR, "Komika_Axis.ttf")
ANIME_ACE_ITALIC = os.path.join(FONT_DIR, "animeace_i.ttf")
MANGA_TEMPLE_ITALIC = os.path.join(FONT_DIR, "mangati.ttf")
SHOUT_FONT = os.path.join(FONT_DIR, "shout.ttf")
DIALOGUE_FONT = os.path.join(FONT_DIR, "dialogue.ttf")
DIALOGUE_ITALIC_FONT = os.path.join(FONT_DIR, "dialogue_italic.ttf")

FONT_CANDIDATES = [
    ANIME_ACE_FONT,
    KOMIKA_FONT,
    DIALOGUE_FONT,
    r"C:\Windows\Fonts\comicbd.ttf",   # Comic Sans MS Bold
    r"C:\Windows\Fonts\segoeuib.ttf",  # Segoe UI Bold
    r"C:\Windows\Fonts\arialbd.ttf"    # Arial Bold
]

def get_best_font():
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return "arial.ttf"

def select_font_for_bubble(text, is_shout=False, is_thought=False):
    """Seleciona dinamicamente a melhor fonte tipográfica de scanlation profissional para o balão."""
    clean = text.strip()
    
    # 1. Gritos, exclamações enfáticas ou onomatopeias
    if is_shout or clean.endswith('!!') or clean.endswith('!?') or clean.endswith('!?!') or (clean.endswith('!') and len(clean.split()) <= 4 and clean.isupper()):
        if os.path.exists(SHOUT_FONT):
            return SHOUT_FONT
        if os.path.exists(KOMIKA_FONT):
            return KOMIKA_FONT
        if os.path.exists(r"C:\Windows\Fonts\impact.ttf"):
            return r"C:\Windows\Fonts\impact.ttf"
            
    # 2. Pensamentos, sussurros, notas e diálogos suaves (itálico)
    if is_thought or (clean.startswith('(') and clean.endswith(')')) or '~' in clean or clean.startswith('*'):
        if os.path.exists(ANIME_ACE_ITALIC):
            return ANIME_ACE_ITALIC
        if os.path.exists(MANGA_TEMPLE_ITALIC):
            return MANGA_TEMPLE_ITALIC
        if os.path.exists(DIALOGUE_ITALIC_FONT):
            return DIALOGUE_ITALIC_FONT
        if os.path.exists(r"C:\Windows\Fonts\comici.ttf"):
            return r"C:\Windows\Fonts\comici.ttf"
            
    # 3. Diálogo padrão de scanlation profissional (Anime Ace 2.0 BB -> Komika Axis -> Comic Neue)
    if os.path.exists(ANIME_ACE_FONT):
        return ANIME_ACE_FONT
    if os.path.exists(KOMIKA_FONT):
        return KOMIKA_FONT
    if os.path.exists(DIALOGUE_FONT):
        return DIALOGUE_FONT
        
    return get_best_font()

_NOTDEF_CACHE = {}
_FALLBACK_FONTS = {}

def sanitize_lettering_text(text):
    """Normaliza caracteres asiáticos (zenkaku), macrons e pontuações para compatibilidade total com fontes TrueType sem gerar quadrados 'tofu'."""
    if not text:
        return ""
    # 0. Decodifica entidades HTML e elimina vazamentos web tipo &#13;, &#x20;, &nbsp;, etc.
    text = html.unescape(text)
    text = re.sub(r'&#[0-9]+;', ' ', text)
    text = re.sub(r'&#x[0-9a-fA-F]+;', ' ', text)
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('\r', ' ').replace('\n', ' ')

    # 1. Normalização NFKC: converte zenkaku (largura total) para caracteres padrão (ASCII)
    # Transforma ．．． -> ..., ： -> :, ！ -> !, ？ -> ?, １２３ -> 123
    text = unicodedata.normalize('NFKC', text)
    
    # 2. Mapeamento de macrons de romanização (Kōyō -> KOYO, Chōhō -> CHOHO)
    macron_map = str.maketrans({
        'Ā': 'A', 'ā': 'a',
        'Ē': 'E', 'ē': 'e',
        'Ī': 'I', 'ī': 'i',
        'Ō': 'O', 'ō': 'o',
        'Ū': 'U', 'ū': 'u',
    })
    text = text.translate(macron_map)
    
    # 3. Padrões adicionais de pontuação asiática e caracteres gráficos
    trans_punct = {
        '…': '...',
        '―': '-',
        '—': '-',
        '–': '-',
        '〜': '~',
        '～': '~',
        '〰': '~',
        '“': '"',
        '”': '"',
        '‘': "'",
        '’': "'",
        '「': '"',
        '」': '"',
        '『': "'",
        '』': "'",
        '【': '[',
        '】': ']',
        '〔': '[',
        '〕': ']',
        '《': '"',
        '》': '"',
        '〈': "'",
        '〉': "'",
        '：': ':',
        '；': ';',
        '，': ',',
        '。': '.',
        '！': '!',
        '？': '?',
        '・': '·',
        '♥': '♡',
        '●': '·',
        '◎': '·',
        '▼': '·',
        '♪': '♪',
        '°': '°',
    }
    for k, v in trans_punct.items():
        text = text.replace(k, v)
        
    return text

_NOTDEF_CACHE = {}
_FALLBACK_CACHE = {}

def is_char_supported(char, font, default_font_path=None):
    try:
        fpath = getattr(font, 'path', default_font_path or '')
        if fpath not in _NOTDEF_CACHE:
            _NOTDEF_CACHE[fpath] = bytes(font.getmask(chr(0xFFFF)))
        notdef = _NOTDEF_CACHE[fpath]
        m = bytes(font.getmask(char))
        return m != notdef and len(m) > 0
    except Exception:
        return False

def get_glyph_font(char, primary_font):
    """Encontra a melhor fonte da cadeia tipográfica para o caractere, garantindo ZERO quadrados 'tofu'."""
    if is_char_supported(char, primary_font):
        return primary_font
        
    fsize = getattr(primary_font, 'size', 20)
    
    # Cadeia de fontes de fallback profissionais do Windows:
    # 1. Símbolos, corações, notas musicais, estrelas
    # 2. Caracteres CJK (chinês, japonês, coreano) para nunca virar caixa preta
    # 3. Segoe UI padrão e Emoji
    fallback_candidates = [
        ("sym", r"C:\Windows\Fonts\seguisym.ttf"),
        ("cjk", r"C:\Windows\Fonts\msyh.ttc"),
        ("cjk_jp", r"C:\Windows\Fonts\msgothic.ttc"),
        ("segoe", r"C:\Windows\Fonts\segoeui.ttf"),
        ("emj", r"C:\Windows\Fonts\seguiemj.ttf")
    ]
    
    for key_name, fpath in fallback_candidates:
        if os.path.exists(fpath):
            cache_k = (key_name, fsize)
            if cache_k not in _FALLBACK_CACHE:
                try:
                    _FALLBACK_CACHE[cache_k] = ImageFont.truetype(fpath, fsize)
                except Exception:
                    continue
            cand_font = _FALLBACK_CACHE[cache_k]
            if is_char_supported(char, cand_font, fpath):
                return cand_font
                
    return None

def draw_manga_text_line(draw, xy, line, font, fill=(0, 0, 0), stroke_width=0, stroke_fill=(255, 255, 255), anchor="mm"):
    """Desenha linha tipográfica com suporte multi-fonte transparente e garantia anti-tofu absoluta (zero quadrados)."""
    line = sanitize_lettering_text(line)
    if not line:
        return

    char_widths = []
    for c in line:
        if c.isspace():
            bb = draw.textbbox((0, 0), " ", font=font)
            char_widths.append((c, font, max(4, bb[2] - bb[0])))
            continue
            
        use_f = get_glyph_font(c, font)
        if use_f is None:
            # Nunca desenha caixa preta ou caractere corrompido
            continue
            
        bb = draw.textbbox((0, 0), c, font=use_f)
        char_widths.append((c, use_f, max(1, bb[2] - bb[0])))

    if not char_widths:
        return

    tot_w = sum(w for _, _, w in char_widths)
    cx, cy = xy
    if anchor == "mm":
        curr_x = cx - (tot_w / 2.0)
    elif anchor == "lm":
        curr_x = cx
    else:
        curr_x = cx - (tot_w / 2.0)

    for c, use_f, w in char_widths:
        if c.isspace():
            curr_x += w
            continue
        draw.text((curr_x, cy), c, font=use_f, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, anchor="lm")
        curr_x += w

def load_project_glossary(manga_dir):
    """Carrega glossário personalizado (termos, nomes de personagens) da pasta do mangá ou global."""
    candidates = [
        os.path.join(manga_dir, "glossary.json"),
        os.path.join(manga_dir, "termos.txt"),
        os.path.join(SCRIPT_DIR, "glossary.json"),
        os.path.join(r"C:\Users\ja329\tools\manga-translator", "glossary.json"),
        os.path.join(r"C:\Users\ja329\OneDrive\Documentos\MANGAS\SKILL-TRADUCAO-MANGA-main", "glossary.json")
    ]
    glossary = {"characters": {}, "terms": {}}
    for c in candidates:
        if os.path.exists(c):
            try:
                if c.endswith(".json"):
                    with open(c, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            glossary["characters"].update(data.get("characters", {}))
                            glossary["terms"].update(data.get("terms", {}))
                elif c.endswith(".txt"):
                    with open(c, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and "->" in line:
                                k, v = line.split("->", 1)
                                glossary["terms"][k.strip()] = v.strip()
                print(f"[+] Glossário ativo carregado de: {c}")
                break
            except Exception as e:
                print(f"[*] Aviso ao ler glossário ({c}): {e}")
    return glossary

LEARNED_RULES_TXT = os.path.join(SCRIPT_DIR, "aprendizado.txt")
GLOBAL_TRANSLATION_MEMORY = os.path.join(SCRIPT_DIR, "memoria_traducoes.json")

def load_learning_rules():
    """Lê as diretrizes de aprendizado humano de aprendizado.txt para injetar nos prompts da IA."""
    if not os.path.exists(LEARNED_RULES_TXT):
        initial_content = """# =====================================================================
# 🧠 MEMÓRIA E APRENDIZADO DA IA (MANGÁS & MANHWAS)
# Edite este arquivo para ensinar a IA o que ela DEVE e o que NÃO DEVE fazer!
# O tradutor lê este arquivo automaticamente a cada tradução.
# =====================================================================

[O QUE FAZER - REGRAS E TERMOS APROVADOS]
- Adapte os diálogos para português brasileiro coloquial, direto e conciso
- Use contrações e oralidade autêntica: tá, pra, cê, valeu, peraí, rolando
- Nomes de personagens e termos fixos:
  * 大哥哥 -> irmãozinho, maninho
  * 小麥 -> Komugi
  * 先輩 / 선배 -> veterano(a), senpai
- Em cenas adultas (+18): mantenha o tom cru, explícito e sem censura

[O QUE NÃO FAZER - PROIBIÇÕES E ERROS A EVITAR]
- NUNCA use palavras em espanhol (como "pero", "entonces", "ahora", "mira")
- NUNCA adicione introduções ou notas de tradutor (como "Aqui está a tradução:")
- NUNCA use palavras excessivamente formais ou arcaicas como "deleite", "aprumar", "ademais"
- NUNCA deixe frases em chinês, japonês ou coreano sem traduzir
"""
        try:
            with open(LEARNED_RULES_TXT, "w", encoding="utf-8") as f:
                f.write(initial_content)
        except Exception:
            pass

    dos = []
    donts = []
    current_sec = None
    if os.path.exists(LEARNED_RULES_TXT):
        try:
            with open(LEARNED_RULES_TXT, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str or line_str.startswith("#") or line_str.startswith("="):
                        continue
                    if "[O QUE FAZER" in line_str.upper():
                        current_sec = "do"
                        continue
                    elif "[O QUE NÃO FAZER" in line_str.upper() or "[O QUE NAO FAZER" in line_str.upper():
                        current_sec = "dont"
                        continue
                    
                    if current_sec == "do":
                        dos.append(line_str)
                    elif current_sec == "dont":
                        donts.append(line_str)
        except Exception:
            pass
            
    return dos, donts

def lookup_translation_memory(orig_text):
    """Consulta a memória global de tradução para reutilizar frases aprendidas perfeitamente."""
    if not os.path.exists(GLOBAL_TRANSLATION_MEMORY):
        return None
    try:
        with open(GLOBAL_TRANSLATION_MEMORY, "r", encoding="utf-8") as f:
            mem = json.load(f)
        return mem.get(orig_text.strip())
    except Exception:
        return None

def update_global_translation_memory(new_translations):
    """Guarda frases traduzidas na memória global persistente."""
    if not new_translations:
        return
    mem = {}
    if os.path.exists(GLOBAL_TRANSLATION_MEMORY):
        try:
            with open(GLOBAL_TRANSLATION_MEMORY, "r", encoding="utf-8") as f:
                mem = json.load(f)
        except Exception:
            mem = {}
    for orig, trans in new_translations.items():
        if trans and orig != trans and len(orig) >= 2:
            mem[orig.strip()] = trans.strip()
    try:
        with open(GLOBAL_TRANSLATION_MEMORY, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def create_cbz_archive(source_dir, output_cbz_path):
    """Cria um arquivo .cbz (Comic Book Zip) compacto para leitura direta em apps móveis."""
    try:
        image_files = [f for f in os.listdir(source_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        image_files.sort(key=natural_sort_key)
        if not image_files:
            return False
            
        with zipfile.ZipFile(output_cbz_path, 'w', zipfile.ZIP_DEFLATED) as cbz:
            for img in image_files:
                img_path = os.path.join(source_dir, img)
                cbz.write(img_path, arcname=img)
        print(f"[+] Arquivo CBZ criado com sucesso: {output_cbz_path} ({len(image_files)} páginas)")
        return True
    except Exception as e:
        print(f"[!] Erro ao criar arquivo CBZ: {e}")
        return False

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
        words = re.findall(r'\b[a-zA-Z]+\b', lower)
        spanish_words = {"el", "la", "de", "que", "y", "en", "un", "una", "por", "con", "para", "los", "las", "del", "al"}
        sp_count = sum(1 for w in words if w in spanish_words)
        if len(words) > 0 and (sp_count / len(words)) > 0.08:
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
    'DROP': 'PINGA',
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
    'FLICK': 'PETELECO',
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
    'SHAKE': 'TREME',
    'STEP': 'TOC TOC',
    'STEPS': 'TOC TOC',
    'GRAB': 'AGARRA',
    'CRAB': 'AGARRA',
    'SQUEEZE': 'APERTA',
    'POUND': 'TUM TUM',
    'PLOP': 'PLOP',
    'SQUIRT': 'JATO',
    'RUSTLE': 'FARFALHA',
    'GLANCE': 'OLHADA',
    'CHOKE': 'COF COF',
    'COUGH': 'COF COF',
    'SNORT': 'SNORT',
    'BOOM': 'BUM',
    'CLICK': 'CLIQUE',
    'CLACK': 'CLAC',
    'TAP': 'TOC',
    'PAT': 'PAT',
    'STROKE': 'ACARICIA',
    'SWOOSH': 'VUUSH',
    'WHOOSH': 'VUUSH',
    'ZOOM': 'ZUM',
    'THUD': 'TUM',
    'CRASH': 'CRASH',
    'SLOSH': 'CHUÁ',
    'SQUISH': 'SQUISH',
    'WOBBLE': 'BALANÇA',
    'FLUTTER': 'TREMULA',
    'JIGGLE': 'BALANÇA',
    'BOUNCE': 'QUICA',
    'NOM': 'NHAC',
    'BITE': 'MORDE',
    'CHEW': 'MASTIGA',
    'GLIDE': 'DESLIZA',
    'SLIDE': 'DESLIZA',
    'PUSH': 'EMPURRA',
    'PULL': 'PUXA',
    'TREMBLE': 'TREME',
    'GROAN': 'GEMIDO',
    'MOAN': 'GEMIDO',
    'WHIMPER': 'CHORAMINGA',
    'BLUSH': 'CORA',
    'STARE': 'ENCARA',
    'PEEK': 'ESPIA',
    'GLARE': 'OLHAR',
    'WINK': 'PISCA',
    'NOD': 'ACENA',
    'WAVE': 'ACENA',
    'SPLAT': 'SPLAT',
    'SPLRT': 'SPLASH',
    'SPLRRT': 'SPLASH',
    'SPLRCH': 'SPLASH',
    'SLRCH': 'SLRCH',
    'SLURP': 'SLURP',
    'SLURRRRRRP': 'SLURP'
}

COMMON_SOUNDS = set(SFX_DICTIONARY.keys()) | {
    'AH', 'HAH', 'AHN', 'MNH', 'UGH', 'NGH', 'AAH', 'AHA', 'FWAA', 'NYAA',
    'HYAH', 'NYAH', 'FUH', 'JYAA', 'CHOP', 'DROP', 'FREEZE', 'SLIP', 'SHH',
    'OH', 'OOH', 'WOAH', 'HMM', 'TCH'
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

    # 1. Corrige quebras de linha com hífens (ex: 'MON- ARCH' -> 'MONARCH')
    text = re.sub(r'([A-Za-z]+)-\s+([A-Za-z]+)', r'\1\2', text)

    # 2. Corrige pronomes e nomes divididos erroneamente pelo OCR
    text = re.sub(r'\bS\s+he\b', 'She', text)
    text = re.sub(r'\bs\s+he\b', 'she', text)
    text = re.sub(r'\bH\s+e\b', 'He', text)
    text = re.sub(r'\bh\s+e\b', 'he', text)
    text = re.sub(r'\bI\s+t\b', 'It', text)
    text = re.sub(r'\bi\s+t\b', 'it', text)
    text = re.sub(r'\bNo\s+run\b', 'Norun', text, flags=re.IGNORECASE)

    # 3. Corrige falta de espaço após pontuação: 'PANTIES,AND' -> 'PANTIES, AND'
    text = re.sub(r'([,;:!?])([A-Za-z])', r'\1 \2', text)
    text = re.sub(r'(\.{2,})([A-Za-z])', r'\1 \2', text)

    # 4. Separa CamelCase ou colagens óbvias com números (ex: 'Ofroyalty' -> 'Of royalty')
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'([A-Za-z])(\d)', r'\1 \2', text)
    text = re.sub(r'(\d)([A-Za-z])', r'\1 \2', text)
    
    if not wordninja:
        return text

    tokens = text.split()
    fixed_tokens = []
    
    for token in tokens:
        clean_tok = re.sub(r'[^a-zA-Z]', '', token)
        # Se a palavra tiver 4+ letras e não for nome/termo reservado
        if len(clean_tok) >= 4 and clean_tok.upper() not in PRESERVE_WORDS:
            splits = wordninja.split(clean_tok)
            if len(splits) >= 2 and len(splits) < len(clean_tok):
                prefix = re.match(r'^[^a-zA-Z]+', token)
                suffix = re.search(r'[^a-zA-Z]+$', token)
                p_str = prefix.group(0) if prefix else ''
                s_str = suffix.group(0) if suffix else ''
                if token.isupper():
                    fixed_tok = ' '.join(s.upper() for s in splits)
                elif token.islower():
                    fixed_tok = ' '.join(s.lower() for s in splits)
                else:
                    fixed_tok = ' '.join(splits)
                fixed_tokens.append(p_str + fixed_tok + s_str)
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
            allowed_gap_y = max(min(min_h * 1.1, 45), 28)
            if gap_y <= allowed_gap_y:
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
            # O vão horizontal entre colunas adjacentes do mesmo balão deve ser proporcional à largura da linha
            allowed_gap_x = max(min(min_w * 0.9, 60), 38)
            if gap_x <= allowed_gap_x:
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
    """Quebra texto por palavras usando largura em pixels real da fonte com balanceamento anti-viúvas/órfãos."""
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
            
    # Rebalanceamento anti-órfão: evita que a última linha fique com 1 única palavra solta de até 5 letras
    if len(all_lines) >= 2:
        last_words = all_lines[-1].split()
        prev_words = all_lines[-2].split()
        if len(last_words) == 1 and len(last_words[0]) <= 5 and len(prev_words) >= 3:
            word_to_shift = prev_words[-1]
            cand_prev = ' '.join(prev_words[:-1])
            cand_last = word_to_shift + ' ' + all_lines[-1]
            bb_last = draw.textbbox((0, 0), cand_last, font=font)
            if (bb_last[2] - bb_last[0]) <= max_w:
                all_lines[-2] = cand_prev
                all_lines[-1] = cand_last
                
    return all_lines

def wrap_text_diamond(draw, text, font, max_w, max_h):
    """Quebra texto no formato de diamante/elipse típico dos balões de mangá com suporte a hifenização PT-BR e anti-órfãos."""
    words = text.split()
    if not words:
        return []
        
    line_bbox = draw.textbbox((0, 0), "Ag", font=font)
    line_h = (line_bbox[3] - line_bbox[1]) * 1.15
    max_k = max(1, int(max_h / line_h))
    
    single_bbox = draw.textbbox((0, 0), text, font=font)
    if (single_bbox[2] - single_bbox[0]) <= max_w:
        return [text]

    def get_allowed_w(li, total_lines):
        if total_lines <= 1:
            return max_w
        # y varia de -0.85 a +0.85 (curvatura da elipse do balão)
        y = ((li + 0.5) - total_lines / 2.0) / (total_lines / 2.0) * 0.85
        factor = math.sqrt(max(0.25, 1.0 - y * y))
        return max_w * factor

    best_lines = None
    best_penalty = float('inf')

    # Testa números de linhas de 2 até max_k
    for k in range(2, max_k + 1):
        lines = []
        w_idx = 0
        possible = True
        words_copy = list(words)
        
        for li in range(k):
            allowed_w = get_allowed_w(li, k)
            curr = []
            while w_idx < len(words_copy):
                w = words_copy[w_idx]
                test_l = ' '.join(curr + [w])
                bbox = draw.textbbox((0, 0), test_l, font=font)
                if (bbox[2] - bbox[0]) <= allowed_w or not curr:
                    curr.append(w)
                    w_idx += 1
                else:
                    # Tenta hifenização silábica segura (anti-órfão: ambas as partes com >= 3 caracteres)
                    if _pyphen_dic and len(w) >= 7 and not curr:
                        hyphenated = _pyphen_dic.inserted(w).split('-')
                        if len(hyphenated) > 1:
                            part1 = ""
                            p_idx = 0
                            while p_idx < len(hyphenated) - 1:
                                candidate = part1 + hyphenated[p_idx]
                                rem = "".join(hyphenated[p_idx + 1:])
                                if len(candidate) >= 3 and len(rem) >= 3:
                                    bb = draw.textbbox((0, 0), candidate + "-", font=font)
                                    if (bb[2] - bb[0]) <= allowed_w:
                                        part1 = candidate
                                        p_idx += 1
                                    else:
                                        break
                                else:
                                    p_idx += 1
                            if part1:
                                part2 = "".join(hyphenated[p_idx:])
                                if len(part2) >= 3:
                                    curr.append(part1 + "-")
                                    words_copy[w_idx] = part2
                                    continue
                    break
            if curr:
                lines.append(' '.join(curr))
            elif w_idx < len(words_copy):
                possible = False
                break
                
        if possible and w_idx == len(words_copy):
            # Verifica se todas as linhas cabem na largura útil
            all_fit = True
            for l_str in lines:
                bb = draw.textbbox((0, 0), l_str, font=font)
                if (bb[2] - bb[0]) > max_w:
                    all_fit = False
                    break
            if all_fit:
                penalty = 0
                last_words = lines[-1].split()
                if len(last_words) == 1 and len(lines) > 1:
                    if len(last_words[0]) <= 3:
                        penalty += 50
                    else:
                        penalty += 15
                if penalty < best_penalty:
                    best_penalty = penalty
                    best_lines = lines
                    if penalty == 0:
                        return lines
                        
    if best_lines:
        return best_lines
                
    # Fallback para quebra proporcional linear se diamond estrito não encaixar
    return wrap_text_to_width(draw, text, font, max_w)

def fit_text_to_box(draw, text, max_w, max_h, font_path):
    """Ajusta proporcionalmente o tamanho da fonte e quebras de linha com 18% de breathing room e leading de scanlation."""
    text = sanitize_lettering_text(text).strip()
    words = text.split()
    if not words:
        return ImageFont.truetype(font_path, 12), []
        
    # Margens de segurança de scanlation (18% horizontal e 20% vertical de breathing room)
    usable_w = max(24, int(max_w * 0.82))
    usable_h = max(24, int(max_h * 0.80))

    ideal_max = int(min(usable_h * 0.45, usable_w * 0.35, 56))
    max_font_size = max(18, min(ideal_max, 56))
    
    # Busca tamanho ideal com passo 1 para ajuste contínuo suave
    for font_size in range(max_font_size, 7, -1):
        font = ImageFont.truetype(font_path, font_size)
        line_bbox = draw.textbbox((0, 0), "Ag", font=font)
        line_h = (line_bbox[3] - line_bbox[1]) * 1.15
        max_possible_lines = int(usable_h / line_h)
        if max_possible_lines < 1:
            continue
            
        candidate_lines = wrap_text_diamond(draw, text, font, usable_w, usable_h)
        if candidate_lines and len(candidate_lines) <= max_possible_lines:
            # Verifica se todas as linhas respeitam estritamente a largura útil
            if all((draw.textbbox((0, 0), l, font=font)[2] - draw.textbbox((0, 0), l, font=font)[0]) <= usable_w for l in candidate_lines):
                return font, candidate_lines
            
    # Fallback dinâmico linear se o diamante for restritivo demais para balões estreitos
    for fallback_size in range(12, 7, -1):
        font = ImageFont.truetype(font_path, fallback_size)
        fallback_lines = wrap_text_to_width(draw, text, font, usable_w)
        line_bbox = draw.textbbox((0, 0), "Ag", font=font)
        line_h = (line_bbox[3] - line_bbox[1]) * 1.15
        if len(fallback_lines) * line_h <= usable_h:
            return font, fallback_lines

    font = ImageFont.truetype(font_path, 8)
    return font, wrap_text_to_width(draw, text, font, usable_w)

def check_openrouter_key_status(api_key, model_name=None):
    """
    Verifica se a chave OpenRouter é válida e se possui saldo/limite diário restante.
    Retorna: (is_valid: bool, remaining_requests: int or None, status_message: str)
    """
    if not api_key or not str(api_key).strip():
        return False, 0, "Chave vazia"
    api_key = str(api_key).strip()
    try:
        url = "https://openrouter.ai/api/v1/auth/key"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/Jos9011/SKILL-TRADUCAO-MANGA",
                "X-Title": "Manga Translator PT-BR"
            }
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status == 200:
                body = json.loads(response.read().decode('utf-8'))
                data = body.get("data", {})
                free_reqs = data.get("free_model_daily_requests", {})
                if free_reqs:
                    rem = free_reqs.get("remaining")
                    limit = free_reqs.get("limit", 50)
                    used = free_reqs.get("used", 0)
                    if rem is not None and rem <= 0:
                        return False, 0, f"Limite diário atingido ({used}/{limit} reqs usadas)"
                    return True, rem, f"{used}/{limit} reqs usadas (restam {rem})"

                limit_rem = data.get("limit_remaining")
                if limit_rem is not None and limit_rem <= 0:
                    return False, 0, "Orçamento/Crédito esgotado"
                return True, 9999, "Conta com créditos / Ilimitada"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return False, 0, "Limite diário atingido (HTTP 429)"
        elif e.code in (401, 403):
            return False, 0, f"Chave inválida ou não autorizada (HTTP {e.code})"
        return False, 0, f"Erro HTTP {e.code}"
    except Exception as e:
        if model_name:
            try:
                test_req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=json.dumps({
                        "model": model_name,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 5
                    }).encode('utf-8'),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/Jos9011/SKILL-TRADUCAO-MANGA",
                        "X-Title": "Manga Translator PT-BR"
                    }
                )
                with urllib.request.urlopen(test_req, timeout=10) as resp:
                    if resp.status == 200:
                        return True, None, "Chave ativa (ping OK)"
            except urllib.error.HTTPError as he:
                if he.code == 429:
                    return False, 0, "Limite diário atingido (HTTP 429)"
                return False, 0, f"Erro HTTP {he.code}"
            except Exception:
                pass
        return False, None, f"Erro de conexão: {e}"

def check_openrouter_available(api_key, model_name):
    """Wrapper retrocompatível para checar disponibilidade de chave."""
    ok, rem, _ = check_openrouter_key_status(api_key, model_name)
    return ok

def query_openrouter_chat(messages, model_name, api_key=None, temperature=0.0, max_tokens=1024, timeout=75, engine_opts=None):
    """
    Executa requisição à API do OpenRouter com suporte a Pool de Chaves e Auto-Failover/Rotação imediata.
    Se a chave atual atingir o limite (HTTP 429 / 50 reqs/dia), rotaciona automaticamente para a próxima chave
    cadastrada em 'openrouter_api_keys' no config.json sem interromper a tradução do mangá.
    """
    engine_opts = engine_opts if engine_opts is not None else {}
    key_pool = engine_opts.get("api_keys", [])
    if not key_pool:
        k = api_key or engine_opts.get("api_key", "")
        if k:
            key_pool = [k]

    if not key_pool:
        raise ValueError("Nenhuma chave OpenRouter fornecida.")

    total_keys = len(key_pool)
    curr_idx = engine_opts.get("current_key_idx", 0)
    if curr_idx >= total_keys:
        curr_idx = 0

    exhausted = engine_opts.setdefault("exhausted_keys", set())
    tried_count = 0

    while tried_count < total_keys:
        # Pula chaves que já sabemos que estão esgotadas se houver outras livres no pool
        if curr_idx in exhausted and len(exhausted) < total_keys:
            curr_idx = (curr_idx + 1) % total_keys
            continue

        active_key = key_pool[curr_idx]
        url = "https://openrouter.ai/api/v1/chat/completions"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Authorization": f"Bearer {active_key.strip()}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Jos9011/SKILL-TRADUCAO-MANGA",
                "X-Title": "Manga Translator PT-BR"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # Alerta amigável se a chave atual estiver prestes a bater o limite diário
                rem_header = resp.headers.get("X-RateLimit-Remaining") or resp.headers.get("x-ratelimit-remaining")
                if rem_header is not None:
                    try:
                        rem_val = int(rem_header)
                        if 0 < rem_val <= 3:
                            print(f"\n[*] Aviso: Chave OpenRouter #{curr_idx + 1} quase no limite ({rem_val} requisições restantes).")
                    except Exception:
                        pass

                res = json.loads(resp.read().decode('utf-8'))
                engine_opts["current_key_idx"] = curr_idx
                engine_opts["api_key"] = active_key
                return res.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode('utf-8', errors='ignore')
            except Exception:
                pass

            is_rate_limit = (e.code == 429) or ("rate limit" in err_body.lower()) or ("free-models-per-day" in err_body.lower())
            is_auth_error = (e.code in (401, 403))

            if is_rate_limit or is_auth_error:
                exhausted.add(curr_idx)
                tried_count += 1
                masked = active_key[:8] + "..." + active_key[-4:] if len(active_key) > 12 else "***"
                motivo = "Limite diário (50 reqs/dia) atingido" if is_rate_limit else f"Autenticação falhou ({e.code})"

                # Procura a próxima chave disponível que ainda não foi esgotada
                next_idx = None
                for candidate in range(total_keys):
                    if candidate not in exhausted:
                        next_idx = candidate
                        break

                if next_idx is not None:
                    next_masked = key_pool[next_idx][:8] + "..." + key_pool[next_idx][-4:] if len(key_pool[next_idx]) > 12 else "***"
                    print(f"\n[!] Chave #{curr_idx + 1} ({masked}): {motivo}.")
                    print(f"[+] ROTACIONANDO CHAVE AUTOMATICAMENTE -> Ativando Chave Reserva #{next_idx + 1} ({next_masked})...")
                    curr_idx = next_idx
                    engine_opts["current_key_idx"] = curr_idx
                    engine_opts["api_key"] = key_pool[curr_idx]
                    time.sleep(1.0)
                    continue
                else:
                    print(f"\n[!] TODAS as {total_keys} chaves OpenRouter cadastradas atingiram o limite diário.")
                    raise e
            else:
                # Se for indisponibilidade temporária de modelo (404, 500, 502, 503), tenta o modelo fallback
                fallback_m = engine_opts.get("fallback_model")
                if fallback_m and fallback_m != model_name and e.code in (404, 500, 502, 503):
                    print(f"\n[*] Modelo '{model_name}' instável (HTTP {e.code}). Tentando modelo fallback: '{fallback_m}'...")
                    model_name = fallback_m
                    time.sleep(1.0)
                    continue
                raise e
        except Exception as e:
            raise e

    raise RuntimeError("Todas as chaves OpenRouter configuradas estão esgotadas.")

def check_ollama_available(prefer_uncensored=False, host="http://localhost:11434", custom_model=None):
    """Verifica se o servidor Ollama (local ou remoto) está ativo e seleciona o modelo ideal priorizando Dolphin 2.9 em modo sem censura."""
    try:
        host = host.rstrip('/')
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                models = [m["name"] for m in data.get("models", [])]
                if models:
                    selected_model = None

                    # 1. Se foi pedido um modelo específico na config
                    if custom_model:
                        for m in models:
                            if custom_model.lower() in m.lower():
                                selected_model = m
                                break

                    # 2. Se prioriza sem censura, busca especificamente variantes do Dolphin 2.9
                    if not selected_model and prefer_uncensored:
                        dolphin_candidates = ["dolphin-llama3", "dolphin-2.9", "dolphin", "uncensored"]
                        for pref in dolphin_candidates:
                            for m in models:
                                if pref in m.lower():
                                    selected_model = m
                                    break
                            if selected_model:
                                break

                    # 3. Modelos multilíngues de alta qualidade para PT-BR
                    if not selected_model:
                        best_pt_models = ["dolphin-llama3", "dolphin", "qwen2.5", "llama3.1", "mistral", "gemma2", "llama3.2", "llama3"]
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
                    print(f"[*] Conectado ao Ollama em '{host}'. Modelo selecionado: '{selected_model}'")
                    try:
                        warm_req = urllib.request.Request(
                            f"{host}/api/chat",
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
                        print(f"[+] Modelo '{selected_model}' ativo com sucesso!")
                    except Exception as we:
                        print(f"[*] Aviso no warm-up do Ollama: {we}")

                    return True, selected_model
        return False, None
    except Exception:
        # Se for localhost e o servidor não estiver respondendo, tenta iniciar automaticamente
        if "localhost" in host or "127.0.0.1" in host:
            ollama_exe_paths = [
                r"C:\Users\ja329\AppData\Local\Programs\Ollama\ollama.exe",
                shutil.which("ollama")
            ]
            for o_path in ollama_exe_paths:
                if o_path and os.path.exists(o_path):
                    try:
                        print("[*] Servidor Ollama local desligado. Iniciando serviço em segundo plano...")
                        subprocess.Popen([o_path, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        for _ in range(8):
                            time.sleep(1)
                            try:
                                with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as r:
                                    if r.status == 200:
                                        print("[+] Servidor Ollama iniciado e pronto com sucesso!")
                                        return check_ollama_available(prefer_uncensored=prefer_uncensored, host=host, custom_model=custom_model)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    break
        return False, None

def query_ollama_chat(messages, model_name, host="http://localhost:11434", temperature=0.0, num_predict=1024, timeout=75):
    """Executa requisição à API do Ollama."""
    host = host.rstrip('/')
    url = f"{host}/api/chat"
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "keep_alive": "60m",
        "options": {
            "temperature": temperature,
            "num_predict": num_predict
        }
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        return res.get("message", {}).get("content", "").strip()

def init_ai_translation_engine(cfg, is_adult=True):
    """
    Inicializa o melhor motor de IA disponível com base em config.json.
    Suporta Pool de Chaves OpenRouter com rotação e failover automático de cota diária.
    Retorna: (engine_type, model_name, engine_opts)
    engine_type pode ser: 'openrouter', 'ollama', ou None (fallback)
    """
    provider = cfg.get("provider", "auto").lower()
    keys = cfg.get("openrouter_api_keys", [])
    model = cfg.get("openrouter_model", "nvidia/nemotron-3.5-lightning:free")
    fallback_model = cfg.get("openrouter_fallback_model", "google/gemma-4-31b-it:free")

    # 1. OpenRouter (100% Nuvem - Sem usar recursos do PC)
    if provider in ("openrouter", "cloud") or (provider == "auto" and keys):
        if keys:
            print(f"[*] Analisando Pool de Chaves OpenRouter ({len(keys)} chave(s) configurada(s))...")
            active_key = None
            active_idx = 0
            exhausted_keys = set()

            for idx, k in enumerate(keys):
                masked = k[:8] + "..." + k[-4:] if len(k) > 12 else "***"
                ok, rem, msg = check_openrouter_key_status(k, model)
                if ok:
                    print(f"  [+] Chave #{idx + 1} ({masked}): PRONTA [{msg}]")
                    if active_key is None:
                        active_key = k
                        active_idx = idx
                else:
                    print(f"  [!] Chave #{idx + 1} ({masked}): Indisponível [{msg}]")
                    exhausted_keys.add(idx)

            if active_key is not None:
                masked_act = active_key[:8] + "..." + active_key[-4:] if len(active_key) > 12 else "***"
                print(f"[+] Motor OpenRouter Nuvem ativado com Chave #{active_idx + 1} ({masked_act}) | Modelo: {model}")
                engine_opts = {
                    "api_key": active_key,
                    "api_keys": keys,
                    "current_key_idx": active_idx,
                    "exhausted_keys": exhausted_keys,
                    "fallback_model": fallback_model,
                    "temperature": cfg.get("temperature", 0.0),
                    "cfg": cfg
                }
                return "openrouter", model, engine_opts
            else:
                print(f"[!] Todas as chaves OpenRouter configuradas estão esgotadas no momento.")
        elif provider in ("openrouter", "cloud"):
            print(f"[!] Erro: Provedor configurado como 'openrouter', mas 'openrouter_api_keys'/'openrouter_api_key' está vazia em config.json.")

    # 2. Ollama (Remoto na Nuvem / Colab ou Local)
    host = cfg.get("ollama_host", "http://localhost:11434")
    model_pref = cfg.get("ollama_model", "dolphin-llama3:latest")
    print(f"[*] Verificando conexão com Ollama em '{host}'...")
    ollama_ok, selected_model = check_ollama_available(prefer_uncensored=is_adult, host=host, custom_model=model_pref)
    if ollama_ok:
        return "ollama", selected_model, {"host": host, "temperature": cfg.get("temperature", 0.0), "cfg": cfg}

    return None, None, {"cfg": cfg}

def clean_ai_translation(text, original_text="", is_adult=True):
    """Higieniza rigorosamente a saída da IA: elimina notas, 'Obs:', prefixos e normaliza anatomia."""
    if not text:
        return original_text.strip()
        
    cleaned = sanitize_lettering_text(text).strip()
    
    # 0. Detectar e ignorar mensagens de recusa de IA ou vazamentos de prompt
    refusal_markers = [
        'idioma desconhecido', 'forneça o texto original',
        'como uma inteligência artificial', 'como uma ia',
        'como um modelo de linguagem', 'não posso cumprir',
        'não posso ajudar', 'não posso atender', 'cannot fulfill', "can't fulfill",
        'você é um tradutor', 'regras obrigatórias', 'traduza o texto original',
        'como modelo de ia', 'as an ai', 'system message', 'mensagem do sistema',
        'i am dolphin', 'sou o dolphin'
    ]
    if any(rm in cleaned.lower() for rm in refusal_markers):
        sfx_try = translate_sfx_phrase(original_text)
        if sfx_try:
            return sfx_try
        norm_sfx = re.sub(r'[^A-Z]', '', original_text.upper())
        if norm_sfx in SFX_DICTIONARY:
            return SFX_DICTIONARY[norm_sfx]
        return ""
        
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
            return ""

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
        if re.match(r'^(?:traduzindo\s+o\s+texto|vou\s+traduzir|aqui\s+est[áa]\s*(?:a\s+tradu[çc][ãa]o|o\s+texto|:))', l_str, flags=re.IGNORECASE):
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

        # Tip (manga adulto) -> Ponta / Glande (NUNCA canto ou gorjeta)
        if re.search(r'\btip\b', orig_lower):
            cleaned = _preserve_case(r'\bcanto\b', 'ponta', cleaned)
            cleaned = _preserve_case(r'\bgorjeta\b', 'ponta', cleaned)
            cleaned = _preserve_case(r'\bdica\b', 'ponta', cleaned)

        # Sucking / Suck -> Chupando / Chupar
        if re.search(r'\b(suck|sucking|sucks)\b', orig_lower):
            cleaned = _preserve_case(r'\bsuckar\b', 'chupar', cleaned)
            cleaned = _preserve_case(r'\bsucking\b', 'chupando', cleaned)

        # Thrusts -> Estocadas / Empurrões
        if re.search(r'\bthrusts?\b', orig_lower):
            cleaned = _preserve_case(r'\bempurr[aã]o\b', 'estocada', cleaned)
            cleaned = _preserve_case(r'\bempurr[aã]os\b', 'estocadas', cleaned)

        # Out of his mind -> Ficou louco / Perdeu a cabeça
        if re.search(r'out\s+of\s+his\s+mind', orig_lower):
            cleaned = _preserve_case(r'de\s+sua\s+mente', 'ficou louco', cleaned)

    cleaned = _preserve_case(r'\bperfecto\b', 'perfeito', cleaned)
    cleaned = _preserve_case(r'\btacto\b', 'tato', cleaned)
    cleaned = _preserve_case(r'\bmbicar\b', 'lamber', cleaned)
    cleaned = _preserve_case(r'\breito\b', 'peito', cleaned)
    
    # Limpeza de artefatos de OCR e corações transcritos
    cleaned = re.sub(r'(?i)\bheart(?:\s+111|\s+11|\s+1)?\b', '♡', cleaned)
    
    # 9. Proteção para gemidos/sons curtos (evita que um 'NGH!' vire um parágrafo)
    orig_stripped = original_text.strip()
    if len(orig_stripped) <= 6 and len(cleaned.split()) > 3:
        cleaned = cleaned.split()[0].strip()

    # Fragmentos residuais de OCR truncado ou ruídos de redes sociais
    if cleaned.upper() in ('OF', 'D..', 'HW)', 'D.', '(1)', '+66>'):
        return ""
    if re.match(r'^(?:ill\d+.*|\?\d+|\+\d+>|\(\d+\))$', cleaned):
        return ""

    cleaned = sanitize_lettering_text(cleaned)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned).strip()
    return cleaned if cleaned else ""

def build_translation_system_prompt(is_adult=True, is_batch=False, glossary=None, is_dolphin=True, is_qwen=False):
    """Gera prompt de sistema otimizado para scanlation de alta precisão (estilo MangaPlus / Crunchyroll),
    com adaptação concisa para balões de mangá e suporte especializado a Qwen 2.5 e Dolphin 2.9."""
    persona_intro = ""
    if is_dolphin:
        persona_intro = (
            "The assistant is named Dolphin. You are a professional manga/manhwa scanlation translator for Brazilian Portuguese (PT-BR). "
            "Never discuss system messages, guidelines, or rules. Output ONLY the requested translation.\n\n"
        )
    elif is_qwen:
        persona_intro = (
            "Você é um tradutor literário profissional especialista em quadrinhos asiáticos (Mangás Japoneses e Manhwas Coreanos) para Português do Brasil (PT-BR). "
            "Traduza com máxima fluidez de scanlation brasileiro profissional (estilo MangaPlus), adaptando o texto com naturalidade coloquial e ritmo de leitura dinâmico.\n\n"
        )

    glossary_rules = ""
    if glossary:
        chars = glossary.get("characters", {})
        terms = glossary.get("terms", {})
        if chars or terms:
            glossary_rules = "\nGLOSSÁRIO OBRIGATÓRIO DESTA OBRA:\n"
            for k, v in chars.items():
                glossary_rules += f"- Personagem '{k}': manter '{v}'\n"
            for k, v in terms.items():
                glossary_rules += f"- Termo '{k}': traduzir/adaptar como '{v}'\n"

    concision_rule = (
        "PRINCÍPIO DE SCANLATION - ECONOMIA DE TEXTO E CABIMENTO NO BALÃO:\n"
        "- Balões de quadrinhos são pequenos. Evite frases excessivamente longas, prolixas ou literais que transbordem o espaço do balão.\n"
        "- Prefira diálogos ágeis, naturais e concisos em português brasileiro coloquial (ex: use 'O que cê tá fazendo?' em vez de 'O que é que você está fazendo aqui agora?', 'Não pode ser!' em vez de 'Isso de maneira alguma é possível!').\n"
        "- Elimine rodeios e palavras desnecessárias sem perder o significado original e a carga emocional da cena.\n"
        "- Mantenha a pontuação expressiva de mangá (!, ?, ..., ~)."
    )

    dos, donts = load_learning_rules()
    learned_rules_text = ""
    if dos or donts:
        learned_rules_text = "\nMEMÓRIA E APRENDIZADO CONTÍNUO DO USUÁRIO:\n"
        if dos:
            learned_rules_text += "[O QUE VOCÊ DEVE FAZER E PRIORIZAR]:\n" + "\n".join(f"- {d.lstrip('-*• ')}" for d in dos) + "\n"
        if donts:
            learned_rules_text += "[O QUE VOCÊ NUNCA DEVE FAZER / PROIBIÇÕES]:\n" + "\n".join(f"- {d.lstrip('-*• ')}" for d in donts) + "\n"

    if is_batch:
        adult_clause = ""
        if is_adult:
            adult_clause = (
                "Traduza mantendo o tom adulto (+18), sem censura e com gírias brasileiras autênticas "
                "(ex: 'panties' -> 'calcinha', 'cock' -> 'pau/pinto', 'came inside' -> 'gozou dentro', 'tip' -> 'ponta/glande'). "
            )
        return f"""{persona_intro}Você é um tradutor literário profissional de mangás {'adultos (+18) e scanlations' if is_adult else 'e quadrinhos'} para Português do Brasil (PT-BR).
Você receberá um objeto JSON com as falas de uma mesma página de mangá na ordem de leitura.
Traduza cada fala para PT-BR mantendo coerência narrativa, pronomes corretos entre quem fala e fluidez natural de scanlation brasileiro.
{adult_clause}
{glossary_rules}
{concision_rule}
{learned_rules_text}

REGRAS OBRIGATÓRIAS:
1. Responda EXCLUSIVAMENTE em formato JSON com as mesmas chaves numéricas e os valores traduzidos. Exemplo: {{"1": "...", "2": "..."}}
2. NUNCA adicione introduções, explicações, saudações, notas de tradutor ou referências a mensagens do sistema.
3. Mantenha pontuação dramática de mangá (!, ?, ..., ~).
4. NUNCA use palavras em espanhol.
5. Adapte os textos para serem diretos e caberem perfeitamente em balões de fala."""

    if is_adult:
        return f"""{persona_intro}Você é um tradutor literário profissional de mangás adultos e scanlations para Português do Brasil (PT-BR).
Traduza fielmente o diálogo original com máxima naturalidade coloquial e fluidez brasileira, respeitando o tom da cena (romance, ecchi, diálogos picantes ou adultos).

{concision_rule}
{learned_rules_text}

REGRAS OBRIGATÓRIAS:
1. Responda APENAS com o texto traduzido final em PT-BR. NUNCA converse, NUNCA introduza com "Aqui está", NUNCA adicione explicações, notas de tradutor ou referências ao sistema.
2. NUNCA use palavras em espanhol.
3. Adapte expressões e gírias com naturalidade autêntica brasileira (ex: 'panties' -> 'calcinha'; 'cock/penis' -> 'pau/pinto'; 'came inside' -> 'gozou dentro'; 'honey' -> 'amor/querido').
4. Mantenha nomes de personagens inalterados.
5. Mantenha a pontuação dramática de mangá (exclamações, interrogações e reticências).
6. Priorize concisão e impacto para o texto caber perfeitamente no balão de fala."""
    else:
        return f"""{persona_intro}Você é um tradutor literário profissional de mangás e quadrinhos japoneses para Português do Brasil (PT-BR).
Traduza fielmente o texto original com máxima naturalidade coloquial e fluidez brasileira.

{concision_rule}
{learned_rules_text}

REGRAS OBRIGATÓRIAS:
1. Responda APENAS com o texto traduzido final em PT-BR. NUNCA converse, NUNCA adicione saudações, notas ou explicações.
2. NUNCA use palavras em espanhol.
3. Mantenha nomes próprios inalterados.
4. Mantenha a pontuação dramática típica de mangás (!?, !!, ..., ~).
5. Priorize concisão e impacto para o texto caber perfeitamente no balão de fala."""

def translate_single_dialogue(text, engine_type, model_name, engine_opts=None, is_adult=True):
    """Traduz uma única fala usando o motor de IA selecionado (OpenRouter ou Ollama) com fallback automático."""
    clean_t = text.strip()
    sfx_res = translate_sfx_phrase(clean_t)
    if sfx_res:
        return sfx_res

    if not engine_type:
        return None

    engine_opts = engine_opts or {}
    is_dolphin = "dolphin" in model_name.lower()
    is_qwen = "qwen" in model_name.lower()
    
    def _do_call(s_prompt):
        try:
            messages = [
                {"role": "system", "content": s_prompt},
                {"role": "user", "content": f"Traduza fielmente para PT-BR:\n\n{clean_t}"}
            ]
            temp = engine_opts.get("temperature", 0.0)
            if engine_type == "openrouter":
                try:
                    raw_resp = query_openrouter_chat(messages, model_name, engine_opts.get("api_key", ""), temperature=temp, max_tokens=300, engine_opts=engine_opts)
                except Exception as o_err:
                    cfg = engine_opts.get("cfg", {})
                    host = cfg.get("ollama_host", "http://localhost:11434")
                    ollama_ok, o_model = check_ollama_available(prefer_uncensored=is_adult, host=host, custom_model=cfg.get("ollama_model"))
                    if ollama_ok:
                        raw_resp = query_ollama_chat(messages, o_model, host=host, temperature=temp, num_predict=300)
                    else:
                        raise o_err
            elif engine_type == "ollama":
                raw_resp = query_ollama_chat(messages, model_name, host=engine_opts.get("host", "http://localhost:11434"), temperature=temp, num_predict=300)
            else:
                return None
                
            cleaned = clean_ai_translation(raw_resp, original_text=clean_t, is_adult=is_adult)
            if cleaned and cleaned.strip().lower() != clean_t.lower():
                return cleaned
        except Exception:
            pass
        return None

    # 1. Tenta prompt adulto
    if is_adult:
        p_adult = build_translation_system_prompt(is_adult=True, is_batch=False, is_dolphin=is_dolphin, is_qwen=is_qwen)
        res = _do_call(p_adult)
        if res:
            return res

    # 2. Fallback neutro
    p_neutral = build_translation_system_prompt(is_adult=False, is_batch=False, is_dolphin=is_dolphin, is_qwen=is_qwen)
    res = _do_call(p_neutral)
    if res:
        return res

    return None

def translate_page_dialogue(bubbles_to_trans, engine_type, model_name, engine_opts=None, is_adult=True, glossary=None):
    """Traduz todas as falas de uma página em lote (JSON) com OpenRouter ou Ollama para máxima coerência narrativa."""
    if not bubbles_to_trans:
        return {}

    engine_opts = engine_opts or {}
    results = {}
    needed = {}
    dialogue_map = {}

    # 1. Resolve SFX e onomatopeias primeiro
    for idx, (orig_text, b_obj) in enumerate(bubbles_to_trans):
        key = str(idx + 1)
        sfx_res = translate_sfx_phrase(orig_text)
        if sfx_res:
            results[orig_text] = sfx_res
        else:
            needed[key] = orig_text
            dialogue_map[key] = orig_text

    if not needed:
        return results

    if not engine_type:
        return results

    is_dolphin = "dolphin" in model_name.lower()
    is_qwen = "qwen" in model_name.lower()
    sys_prompt = build_translation_system_prompt(is_adult=is_adult, is_batch=True, glossary=glossary, is_dolphin=is_dolphin, is_qwen=is_qwen)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": json.dumps(needed, ensure_ascii=False, indent=2)}
    ]

    temp = engine_opts.get("temperature", 0.0)
    try:
        if engine_type == "openrouter":
            try:
                resp_content = query_openrouter_chat(messages, model_name, engine_opts.get("api_key", ""), temperature=temp, max_tokens=1024, engine_opts=engine_opts)
            except Exception as o_err:
                cfg = engine_opts.get("cfg", {})
                host = cfg.get("ollama_host", "http://localhost:11434")
                ollama_ok, o_model = check_ollama_available(prefer_uncensored=is_adult, host=host, custom_model=cfg.get("ollama_model"))
                if ollama_ok:
                    print(f"\n[*] OpenRouter indisponível -> Alternando lote para Ollama ('{o_model}')...")
                    resp_content = query_ollama_chat(messages, o_model, host=host, temperature=temp, num_predict=1024)
                else:
                    raise o_err
        elif engine_type == "ollama":
            resp_content = query_ollama_chat(messages, model_name, host=engine_opts.get("host", "http://localhost:11434"), temperature=temp, num_predict=1024)
        else:
            resp_content = ""

        json_match = re.search(r'\{.*\}', resp_content, flags=re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            for k, trans in parsed.items():
                if k in dialogue_map:
                    orig = dialogue_map[k]
                    cleaned_trans = clean_ai_translation(trans, original_text=orig, is_adult=is_adult)
                    if cleaned_trans and cleaned_trans.strip().lower() != orig.strip().lower():
                        results[orig] = cleaned_trans
    except Exception:
        pass

    # 2. Fallback balão a balão para falas que não vieram no JSON
    for key, orig in needed.items():
        if orig not in results or results[orig].strip().lower() == orig.strip().lower():
            fb_res = translate_single_dialogue(orig, engine_type, model_name, engine_opts=engine_opts, is_adult=is_adult)
            if fb_res and fb_res.strip().lower() != orig.strip().lower():
                results[orig] = fb_res

    return results

def translate_with_ollama(text, model_name, is_adult=True):
    """Alias retrocompatível para tradução de fala única."""
    return translate_single_dialogue(text, "ollama", model_name, {"host": "http://localhost:11434"}, is_adult=is_adult)

def translate_page_dialogue_with_ollama(bubbles_to_trans, model_name, is_adult=True, glossary=None):
    """Alias retrocompatível para tradução de lote por página."""
    return translate_page_dialogue(bubbles_to_trans, "ollama", model_name, {"host": "http://localhost:11434"}, is_adult=is_adult, glossary=glossary)

def translate_batch_texts(text_list, src_lang="auto", is_adult=True, engine_type=None, model_name=None, engine_opts=None):
    """Traduz lista de textos usando o motor selecionado (OpenRouter/Ollama) com fallback para Google/MyMemory."""
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

    translator = MyMemoryTranslator(source=src_lang, target='pt-BR')
    results = []

    for i, t in enumerate(tqdm(text_list, desc="Traduzindo", unit="balão")):
        clean_t = t.strip()
        if not clean_t or clean_t in ("...", "…", "!!", "!?"):
            results.append(clean_t)
            continue

        sfx_res = translate_sfx_phrase(clean_t)
        if sfx_res:
            results.append(sfx_res)
            continue

        norm_sfx = re.sub(r'[^A-Z]', '', clean_t.upper())
        if norm_sfx in SFX_DICTIONARY:
            results.append(SFX_DICTIONARY[norm_sfx])
            continue

        res = None
        if engine_type:
            res = translate_single_dialogue(clean_t, engine_type, model_name, engine_opts=engine_opts, is_adult=is_adult)

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

KOREAN_MODEL_DIR = os.path.join(SCRIPT_DIR, "models", "korean")
KOREAN_REC_PATH = os.path.join(KOREAN_MODEL_DIR, "korean_mobile_v2.0_rec_infer.onnx")
KOREAN_DICT_PATH = os.path.join(KOREAN_MODEL_DIR, "korean_dict.txt")

def ensure_korean_ocr_model():
    """Garante que os arquivos do modelo de OCR Coreano (ONNX + dict) estejam baixados."""
    os.makedirs(KOREAN_MODEL_DIR, exist_ok=True)
    if not os.path.exists(KOREAN_REC_PATH):
        try:
            print("[*] Baixando modelo de OCR Coreano (korean_mobile_v2.0_rec_infer.onnx)...")
            url_m = "https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv1/korean_mobile_v2.0_rec_infer.onnx"
            req = urllib.request.Request(url_m, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as resp, open(KOREAN_REC_PATH, 'wb') as f:
                f.write(resp.read())
        except Exception as e:
            print(f"[!] Erro ao baixar modelo coreano: {e}")
    if not os.path.exists(KOREAN_DICT_PATH):
        try:
            print("[*] Baixando dicionário de Hangul Coreano...")
            url_d = "https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/release/2.7/ppocr/utils/dict/korean_dict.txt"
            req = urllib.request.Request(url_d, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp, open(KOREAN_DICT_PATH, 'wb') as f:
                f.write(resp.read())
        except Exception as e:
            print(f"[!] Erro ao baixar dicionário coreano: {e}")
    return os.path.exists(KOREAN_REC_PATH) and os.path.exists(KOREAN_DICT_PATH)

def get_rapidocr_engine(is_korean=False):
    """Instancia o RapidOCR com suporte a Coreano ou padrão universal."""
    if is_korean:
        if ensure_korean_ocr_model():
            try:
                return RapidOCR(rec_model_path=KOREAN_REC_PATH, rec_keys_path=KOREAN_DICT_PATH)
            except Exception as e:
                print(f"[!] Aviso ao iniciar RapidOCR Coreano: {e}")
    return RapidOCR()

def detect_manga_language_and_engine(manga_dir):
    """
    Detecta automaticamente o idioma da obra e seleciona o motor ideal:
    - 'korean': Manhwa / Coreano (Hangul) -> Usa RapidOCR Coreano (NUNCA usa Mokuro)
    - 'mokuro': Mangá Japonês (Kanji/Kana) -> Usa Mokuro (manga-ocr)
    - 'rapidocr': Ocidental / Inglês / Espanhol -> Usa RapidOCR padrão
    """
    folder_name = os.path.basename(manga_dir)
    # 1. Se o nome da pasta contiver Hangul coreano (ex: 두근두근 공부 시간)
    if re.search(r'[\uac00-\ud7af]', folder_name) or "manhwa" in folder_name.lower() or "webtoon" in folder_name.lower():
        print("[+] Idioma detectado pelo título: COREANO (Hangul) -> Usando RapidOCR Coreano.")
        return "korean"

    # 2. Se o próprio nome contiver Kana japonês
    if re.search(r'[\u3040-\u30ff]', folder_name):
        return "mokuro"

    # 3. Analisa amostra de imagem
    try:
        import glob
        img_files = glob.glob(os.path.join(manga_dir, "*.*"))
        img_files = [f for f in img_files if f.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.bmp'))]
        if not img_files:
            return "mokuro"

        sample_idx = min(len(img_files) // 2, len(img_files) - 1)
        src_path = img_files[sample_idx]

        engine = RapidOCR()
        with open(src_path, "rb") as f:
            img_array = np.asarray(bytearray(f.read()), dtype=np.uint8)
            img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        res, _ = engine(img_cv)
        if not res:
            return "mokuro"

        full_sample_text = " ".join([box[1] for box in res])
        korean_count = len(re.findall(r'[\uac00-\ud7af]', full_sample_text))
        japanese_count = len(re.findall(r'[\u3040-\u30ff]', full_sample_text))
        chinese_count = len(re.findall(r'[\u4e00-\u9fff]', full_sample_text))
        latin_count = len(re.findall(r'[a-zA-Z]', full_sample_text))

        if korean_count > 0:
            return "korean"
        if japanese_count == 0 and chinese_count >= 3:
            print("[+] Obra identificada como CHINÊS (Hanzi) sem kana -> Usando RapidOCR Universal.")
            return "rapidocr"
        if latin_count > 10 and latin_count > (japanese_count * 2):
            return "rapidocr"
        return "mokuro"
    except Exception:
        return "mokuro"

def check_needs_rapidocr(manga_dir):
    """Analisa imagens para determinar se o conteúdo é ocidental/latino ou coreano."""
    engine = detect_manga_language_and_engine(manga_dir)
    return engine != "mokuro"

def is_ocr_noise(text, score):
    """Filtra ruídos de OCR para não apagar detalhes de arte ou fundos."""
    t = text.strip()
    if not t:
        return True
    try:
        sc = float(score)
    except Exception:
        sc = 1.0
    if sc < 0.42:
        return True
    has_letters = bool(re.search(r'[a-zA-Z\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]', t))
    if not has_letters and sc < 0.75:
        return True
    if len(t) <= 1 and sc < 0.60:
        return True
    if len(set(t)) <= 2 and len(t) >= 4 and sc < 0.75:
        return True
    return False

def generate_rapidocr_json(manga_dir, output_json_path, is_korean=False):
    """Extrai textos usando RapidOCR (com suporte a Hangul Coreano e detecção de textos coloridos)."""
    import glob
    
    img_files = glob.glob(os.path.join(manga_dir, "*.*"))
    img_files = [f for f in img_files if f.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.bmp'))]
    img_files.sort(key=natural_sort_key)
    
    engine = get_rapidocr_engine(is_korean=is_korean)
    pages = []
    
    desc_msg = "OCR Coreano (Hangul)" if is_korean else "OCR Universal (RapidOCR)"
    print(f"[*] Extraindo textos usando {desc_msg}...")
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
        
        # Para Coreano, combina detecção no original e no min_bgr
        res, _ = engine(img_cv)
        if not res or len(res) < 2:
            res_alt, _ = engine(min_bgr)
            if res_alt and len(res_alt) > (len(res) if res else 0):
                res = res_alt

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
                
                clean_ocr_text = repair_glued_text(text, src_lang="ko-KR" if is_korean else "en-US")
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
        
    mokuro_data = {"version": "rapidocr_korean" if is_korean else "rapidocr", "pages": pages}
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(mokuro_data, f, ensure_ascii=False)

def is_credits_page(bubbles):
    """Detecta páginas puras de créditos ou recrutamento de scanlators para preservar a arte original."""
    full_text = " ".join([b.get("combined_text", "") for b in bubbles]).lower()
    
    # Se a página contiver texto longo narrativo (>35 palavras, como posfácio ou nota do autor), NÃO é página de créditos
    if len(full_text.split()) > 35:
        if any(sm in full_text for sm in ["recruiting", "raw provider", "join us", "hiring typesetter", "cleaner needed"]):
            return True
        return False
        
    markers = [
        "scanlation", "discord.gg", "patreon", "recruiting",
        "raw provider", "typesetter", "cleaner", "proofreader",
        "redrawn by", "translated by", "join us", "donation",
        "commission", "hiring", "omega scans", "qmega scans", "amega scans",
        "ko-fi", "fantia", "fanbox", "sungroup"
    ]
    matched = sum(1 for m in markers if m in full_text)
    return matched >= 2 or any(m in full_text for m in ["discord.gg", "patreon", "recruiting", "scanlation"])

def is_valid_translation(orig_text, trans_text):
    """Verifica se a tradução é válida e não é uma falha, ruído ou cópia do texto asiático/estrangeiro não traduzido."""
    if not trans_text or not str(trans_text).strip():
        return False
    clean_orig = str(orig_text).strip()
    clean_trans = str(trans_text).strip()
    # Se a tradução ainda contém ideogramas chineses, kana japoneses ou hangul coreano, NÃO foi traduzida para português
    if re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', clean_trans):
        return False
    # Se for idêntico ao original e contiver letras ou caracteres asiáticos, não houve tradução
    if clean_trans.lower() == clean_orig.lower():
        if re.search(r'[a-zA-Z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', clean_orig):
            return False
    return True

def process_manga(manga_dir, target_lang="pt-BR", ocr_mode="auto", force_ocr=False, retranslate=False, is_adult=True, config=None):
    if config is None:
        config = load_config()
    manga_dir = os.path.abspath(manga_dir.strip('\"\''))
    if not os.path.exists(manga_dir) or not os.path.isdir(manga_dir):
        print(f"[!] Erro: Caminho inválido ({manga_dir})")
        return False
        
    manga_name = os.path.basename(manga_dir)
    clean_name = manga_name.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip()
    
    # Carrega glossário específico da obra se existir
    glossary = load_project_glossary(manga_dir)
    
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
        print("[!] LIMPEZA TOTAL DE CACHE: Regerando OCR e traduções...")
        if os.path.exists(cache_dir):
            try: shutil.rmtree(cache_dir)
            except Exception: pass
        os.makedirs(cache_dir, exist_ok=True)
    elif retranslate:
        print("[!] RETRADUÇÃO RÁPIDA: Reutilizando OCR existente e regerando traduções com nova IA...")
        if os.path.exists(cache_file):
            try: os.remove(cache_file)
            except Exception: pass

    print(f"[*] Modo OCR selecionado: {ocr_mode.upper()}")
    if ocr_mode in ("korean", "manhwa"):
        expected_engine = "rapidocr_korean"
    elif ocr_mode == "rapidocr":
        expected_engine = "rapidocr"
    elif ocr_mode == "mokuro":
        expected_engine = "mokuro"
    else:
        print("[*] Analisando nome da obra e imagens para escolher o motor OCR ideal...")
        auto_lang = detect_manga_language_and_engine(manga_dir)
        if auto_lang == "korean":
            expected_engine = "rapidocr_korean"
        elif auto_lang == "rapidocr":
            expected_engine = "rapidocr"
        else:
            expected_engine = "mokuro"

    print(f"[+] Motor OCR definido: {expected_engine.upper()}")

    needs_new_ocr = True
    if not force_ocr and os.path.exists(mokuro_path):
        try:
            with open(mokuro_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            file_version = str(existing_data.get("version", ""))
            pages = existing_data.get("pages", [])
            total_blocks = sum(len(p.get("blocks", [])) for p in pages)
            
            engine_matches = (
                (expected_engine == "rapidocr_korean" and file_version == "rapidocr_korean") or
                (expected_engine == "rapidocr" and file_version == "rapidocr") or
                (expected_engine == "mokuro" and file_version not in ("rapidocr", "rapidocr_korean"))
            )
            
            if total_blocks > 0 and engine_matches:
                print(f"[+] Cache OCR ({expected_engine.upper()}) encontrado ({total_blocks} balões). Reutilizando...")
                needs_new_ocr = False
            else:
                try: os.remove(mokuro_path)
                except Exception: pass
                needs_new_ocr = True
        except Exception:
            needs_new_ocr = True

    if needs_new_ocr:
        if expected_engine == "rapidocr_korean":
            print("[+] Executando RapidOCR Coreano (Hangul)...")
            generate_rapidocr_json(manga_dir, mokuro_path, is_korean=True)
        elif expected_engine == "rapidocr":
            print("[+] Executando RapidOCR Universal com detecção de textos coloridos...")
            generate_rapidocr_json(manga_dir, mokuro_path, is_korean=False)
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
        blocks_for_grouping = []
        for blk in page_info.get("blocks", []):
            xmin, ymin, xmax, ymax = [int(round(float(v))) for v in blk.get("box", [0, 0, 0, 0])]
            is_vertical = blk.get("vertical", True)
            lines = blk.get("lines", [])
            text = " ".join(lines).strip()
            if not text:
                continue
            blocks_for_grouping.append({
                "box": [xmin, ymin, xmax, ymax],
                "text": text,
                "lines": lines,
                "is_vertical": is_vertical
            })
            
        grouped = smart_group_bubbles(blocks_for_grouping)
        bubbles = []
        for b in grouped:
            all_raw_texts.append(b["combined_text"])
            bubbles.append({
                "box": b["box"],
                "raw_boxes": b.get("raw_boxes", [b["box"]]),
                "lines": b["lines"],
                "combined_text": b["combined_text"],
                "is_vertical": b["is_vertical"]
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
                'traduza o texto original', 'como uma inteligência artificial', 'regras obrigatórias',
                'system message', 'mensagem do sistema'
            ]
            for k, v in raw_cache.items():
                if not any(cm in v.lower() for cm in corrupt_markers) and is_valid_translation(k, v):
                    cache[k] = v
        except Exception:
            pass
            
    engine_type, model_name, engine_opts = init_ai_translation_engine(config, is_adult=is_adult)
    if engine_type == "openrouter":
        print(f"[+] MOTOR ATIVO: OpenRouter Cloud (Nuvem) -> Modelo: '{model_name}' (Sem usar recursos do PC)")
    elif engine_type == "ollama":
        print(f"[+] MOTOR ATIVO: Ollama ({engine_opts.get('host')}) -> Modelo: '{model_name}'")
    else:
        print(f"[*] Modo Fallback de Tradução Nuvem ativado (MyMemory/Google).")

    # Traduz página por página com coerência narrativa e suporte a glossário
    for p in tqdm(pages_data, desc="Tradução Contextual", unit="pág"):
        if is_credits_page(p["bubbles"]):
            continue
            
        untranslated = []
        for b in p["bubbles"]:
            orig_text = b["combined_text"].strip()
            # 1. Consulta memória global persistente de tradução aprendida
            if orig_text not in cache or not is_valid_translation(orig_text, cache.get(orig_text, "")):
                mem_hit = lookup_translation_memory(orig_text)
                if mem_hit and is_valid_translation(orig_text, mem_hit):
                    cache[orig_text] = mem_hit
            # Se não está no cache ou o que está no cache não é uma tradução válida para PT
            if orig_text not in cache or not is_valid_translation(orig_text, cache[orig_text]):
                untranslated.append((orig_text, b))
                
        if untranslated:
            if engine_type:
                batch_res = translate_page_dialogue(untranslated, engine_type, model_name, engine_opts=engine_opts, is_adult=is_adult, glossary=glossary)
                for orig, trans in batch_res.items():
                    if trans and is_valid_translation(orig, trans):
                        cache[orig] = clean_ai_translation(trans, original_text=orig, is_adult=is_adult)
                        
            # Se ainda houver textos sem tradução válida, tenta o fallback
            still_untranslated = [item[0] for item in untranslated if item[0] not in cache or not is_valid_translation(item[0], cache[item[0]])]
            if still_untranslated:
                cloud_res = translate_batch_texts(still_untranslated, src_lang=src_lang, is_adult=is_adult, engine_type=engine_type, model_name=model_name, engine_opts=engine_opts)
                for orig, trans in zip(still_untranslated, cloud_res):
                    if trans and is_valid_translation(orig, trans):
                        cache[orig] = clean_ai_translation(trans, original_text=orig, is_adult=is_adult)

    try:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as cf:
            json.dump(cache, cf, ensure_ascii=False, indent=2)
        # Salva novas traduções aprovadas na memória global de aprendizado
        update_global_translation_memory(cache)
    except Exception as e:
        print(f"[!] Aviso: Não foi possível salvar o cache: {e}")

    for p in pages_data:
        for b in p["bubbles"]:
            orig_text = b["combined_text"].strip()
            cached_val = cache.get(orig_text, "")
            cleaned_val = clean_ai_translation(cached_val, original_text=orig_text, is_adult=is_adult) if cached_val else ""
            if cleaned_val and is_valid_translation(orig_text, cleaned_val):
                b["translated_text"] = cleaned_val
            elif cached_val and is_valid_translation(orig_text, cached_val):
                b["translated_text"] = cached_val
            else:
                b["translated_text"] = ""

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
        
        # 4.1 Limpar balões com algoritmo seguro (Apenas se foi traduzido com sucesso)
        for b in bubbles:
            trans_txt = b.get("translated_text", "").strip()
            if not trans_txt or not is_valid_translation(b["combined_text"], trans_txt):
                continue
            for r_box in b.get("raw_boxes", [b["box"]]):
                clean_speech_bubble(cleaned, r_box)
            clean_speech_bubble(cleaned, b["box"])
                
        # 4.2 Desenhar texto traduzido
        img_pil = Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img_pil)
        
        for i, b in enumerate(bubbles):
            text = b.get("translated_text", "").strip().upper()
            if not text or text in ("...", "…"):
                continue
            if not is_valid_translation(b["combined_text"], text):
                continue
                
            xmin, ymin, xmax, ymax = b["box"]
            bw = xmax - xmin
            bh = ymax - ymin
            cx = (xmin + xmax) / 2
            cy = (ymin + ymax) / 2

            # 1. Particionamento espacial inteligente entre balões vizinhos (evita sobreposição)
            x_min_limit = 10
            x_max_limit = w_img - 10
            y_min_limit = 10
            y_max_limit = h_img - 10
            
            for j, other in enumerate(bubbles):
                if i == j:
                    continue
                other_text = other.get("translated_text", "").strip().upper()
                if not other_text or other_text in ("...", "…"):
                    continue
                o_xmin, o_ymin, o_xmax, o_ymax = other["box"]
                o_cx = (o_xmin + o_xmax) / 2
                o_cy = (o_ymin + o_ymax) / 2
                
                # Proximidade vertical: se houver sobreposição vertical ou proximidade < 40px
                if max(ymin, o_ymin) < min(ymax, o_ymax) + 40:
                    if o_cx < cx:
                        mid = (o_xmax + xmin) / 2
                        x_min_limit = max(x_min_limit, mid + 6)
                    elif o_cx > cx:
                        mid = (xmax + o_xmin) / 2
                        x_max_limit = min(x_max_limit, mid - 6)
                        
                # Proximidade horizontal: se houver sobreposição horizontal ou proximidade < 30px
                if max(xmin, o_xmin) < min(xmax, o_xmax) + 30:
                    if o_cy < cy:
                        mid = (o_ymax + ymin) / 2
                        y_min_limit = max(y_min_limit, mid + 6)
                    elif o_cy > cy:
                        mid = (ymax + o_ymin) / 2
                        y_max_limit = min(y_max_limit, mid - 6)

            sub_roi = cleaned[max(0, ymin):min(h_img, ymax), max(0, xmin):min(w_img, xmax)]
            is_white_bg = True
            if sub_roi.size > 0:
                is_white_bg = np.mean(cv2.cvtColor(sub_roi, cv2.COLOR_BGR2GRAY) > 200) > 0.45

            safe_cx = cx
            safe_cy = cy
            safe_min_x, safe_max_x = xmin, xmax
            safe_min_y, safe_max_y = ymin, ymax
            target_w = bw
            target_h = max(bh * 1.20, 50)

            if is_white_bg:
                # Detecta limites do balão branco respeitando estritamente a partição dos vizinhos
                gray_c = cv2.cvtColor(cleaned, cv2.COLOR_BGR2GRAY)
                icx, icy = int(np.clip(cx, 0, w_img - 1)), int(np.clip(cy, 0, h_img - 1))
                
                # Se o pixel central for escuro por arte ou ruído residual, localiza pixel semente claro
                if gray_c[icy, icx] <= 185:
                    y_s0, y_s1 = max(0, int(ymin)), min(h_img, int(ymax))
                    x_s0, x_s1 = max(0, int(xmin)), min(w_img, int(xmax))
                    roi_s = gray_c[y_s0:y_s1, x_s0:x_s1]
                    if roi_s.size > 0:
                        bright_pts = np.argwhere(roi_s > 200)
                        if len(bright_pts) > 0:
                            mid_pt = bright_pts[len(bright_pts) // 2]
                            icy = y_s0 + mid_pt[0]
                            icx = x_s0 + mid_pt[1]

                if gray_c[icy, icx] > 185:
                    b_left = icx
                    while b_left > x_min_limit and gray_c[icy, b_left] > 185: b_left -= 1
                    b_right = icx
                    while b_right < x_max_limit and gray_c[icy, b_right] > 185: b_right += 1
                    b_top = icy
                    while b_top > y_min_limit and gray_c[b_top, icx] > 185: b_top -= 1
                    b_bottom = icy
                    while b_bottom < y_max_limit and gray_c[b_bottom, icx] > 185: b_bottom += 1

                    safe_min_x = max(b_left + 4, x_min_limit)
                    safe_max_x = min(b_right - 4, x_max_limit)
                    safe_min_y = max(b_top + 4, y_min_limit)
                    safe_max_y = min(b_bottom - 4, y_max_limit)

                    if safe_max_x > safe_min_x + 20 and safe_max_y > safe_min_y + 20:
                        safe_cx = (safe_min_x + safe_max_x) / 2
                        safe_cy = (safe_min_y + safe_max_y) / 2
                        target_w = safe_max_x - safe_min_x
                        target_h = safe_max_y - safe_min_y
                    else:
                        target_w = max(bw * 1.25, 70)
                        target_h = max(bh * 1.20, 50)
                else:
                    target_w = max(bw * 1.25, 70)
                    target_h = max(bh * 1.20, 50)
            else:
                target_w = max(bw * 1.25, 70)
                target_h = max(bh * 1.20, 50)
            
            # Margem de segurança na largura considerando os limites da partição e da página
            max_avail_w = min(
                (safe_cx - x_min_limit) * 2 - 8,
                (x_max_limit - safe_cx) * 2 - 8,
                min(safe_cx, w_img - safe_cx) * 2 - 16
            )
            if max_avail_w > 30:
                target_w = min(target_w, max_avail_w)
            
            # Seleciona a melhor fonte tipográfica profissional para a fala
            chosen_font_path = select_font_for_bubble(text)
            font, lines = fit_text_to_box(draw, text, target_w, target_h, chosen_font_path)
            if not lines:
                continue
                
            line_bbox = draw.textbbox((0, 0), "Ag", font=font)
            line_h = (line_bbox[3] - line_bbox[1]) * 1.15
            total_h = len(lines) * line_h
            start_y = safe_cy - (total_h / 2.0) + (line_h / 2.0)
            
            # Margem de segurança de respiro (breathing room) de 10% no topo e base do balão
            pad_y_balloon = max(4, int(target_h * 0.10))
            balloon_top = safe_min_y + pad_y_balloon
            balloon_bottom = safe_max_y - pad_y_balloon
            
            # Garante que a primeira linha nunca ultrapasse o topo do balão
            first_line_top = start_y - (line_h / 2.0)
            if first_line_top < balloon_top:
                start_y += (balloon_top - first_line_top)
                
            # Garante que a última linha nunca ultrapasse o fundo do balão
            last_line_bottom = start_y + (len(lines) - 1) * line_h + (line_h / 2.0)
            if last_line_bottom > balloon_bottom:
                start_y -= (last_line_bottom - balloon_bottom)
                
            # Margem global de proteção para bordas da imagem da página
            if start_y - (line_h / 2.0) < 12:
                start_y = 12 + (line_h / 2.0)
            elif start_y + (len(lines) - 1) * line_h + (line_h / 2.0) > h_img - 12:
                start_y = h_img - 12 - (len(lines) - 1) * line_h - (line_h / 2.0)
                
            font_size = getattr(font, 'size', 20)
            stroke_w = 1 if is_white_bg else max(2, int(round(font_size * 0.08)))
            
            for line_idx, line in enumerate(lines):
                ly = start_y + (line_idx * line_h)
                draw_manga_text_line(draw, (safe_cx, ly), line, font=font, fill=(0, 0, 0), stroke_width=stroke_w, stroke_fill=(255, 255, 255), anchor="mm")
                
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

    # 7. Criar arquivo CBZ para celulares e leitores digitais
    cbz_filename = f"{clean_name} [PT-BR].cbz"
    cbz_dest_path = os.path.join(base_drive_dir, cbz_filename)
    print(f"[*] Gerando arquivo .CBZ para leitura em tablets e celulares...")
    create_cbz_archive(output_dir, cbz_dest_path)

    print("\n" + "=" * 60)
    print(f"[+] MANGA TRADUZIDO COM SUCESSO!")
    print(f"[+] Pasta salva: {output_dir}")
    print(f"[+] Leitor Web: {os.path.join(output_dir, 'leitor.html')}")
    print(f"[+] Arquivo CBZ: {cbz_dest_path}")
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
        
    return {"success": True, "output_dir": output_dir, "cbz_path": cbz_dest_path}

if __name__ == "__main__":
    force_ocr_flag = False
    retranslate_flag = False
    chosen_mode = "auto"
    is_adult_flag = True
    cli_provider = None
    cli_model = None
    cli_host = None
    cli_key = None
    
    if len(sys.argv) > 1:
        args = sys.argv[1:]
        if "--korean" in args or "--manhwa" in args:
            chosen_mode = "korean"
            if "--korean" in args: args.remove("--korean")
            if "--manhwa" in args: args.remove("--manhwa")
        elif "--rapidocr" in args:
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
        elif "--retranslate" in args or "--retrans" in args:
            retranslate_flag = True
            if "--retranslate" in args: args.remove("--retranslate")
            if "--retrans" in args: args.remove("--retrans")
            
        if "--normal" in args or "--safe" in args:
            is_adult_flag = False
            if "--normal" in args: args.remove("--normal")
            if "--safe" in args: args.remove("--safe")
        elif "--adult" in args or "--18" in args:
            is_adult_flag = True
            if "--adult" in args: args.remove("--adult")
            if "--18" in args: args.remove("--18")

        if "--openrouter" in args:
            cli_provider = "openrouter"
            args.remove("--openrouter")
        elif "--ollama" in args:
            cli_provider = "ollama"
            args.remove("--ollama")

        # Parsing de argumentos chave-valor
        i = 0
        while i < len(args):
            if args[i] == "--model" and i + 1 < len(args):
                cli_model = args[i + 1]
                del args[i:i+2]
            elif args[i] == "--host" and i + 1 < len(args):
                cli_host = args[i + 1]
                del args[i:i+2]
            elif args[i] == "--key" and i + 1 < len(args):
                cli_key = args[i + 1]
                del args[i:i+2]
            else:
                i += 1
            
        target = " ".join(args).strip()
    else:
        print("=" * 60)
        print("  SISTEMA AUTOMATICO DE TRADUCAO DE MANGA [PT-BR]")
        print("=" * 60)
        target = input("Arraste ou digite o caminho da pasta do manga: ").strip()

    cli_opts = {}
    if cli_provider: cli_opts["provider"] = cli_provider
    if cli_model: cli_opts["model"] = cli_model
    if cli_host: cli_opts["host"] = cli_host
    if cli_key: cli_opts["key"] = cli_key

    cfg = load_config(cli_opts)

    if target:
        process_manga(target, ocr_mode=chosen_mode, force_ocr=force_ocr_flag, retranslate=retranslate_flag, is_adult=is_adult_flag, config=cfg)
    else:
        print("[!] Nenhuma pasta informada.")
