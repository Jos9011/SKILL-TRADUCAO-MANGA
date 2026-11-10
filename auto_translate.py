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
import io
import base64
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

try:
    from version import __version__, __version_name__, get_version_info
except ImportError:
    try:
        from .version import __version__, __version_name__, get_version_info
    except Exception:
        __version__ = "0.2.0-beta"
        __version_name__ = "v0.2.0 Beta"
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

class _SafeStreamWrapper(io.StringIO):
    def write(self, s):
        try:
            return len(s) if s else 0
        except Exception:
            return 0
    def flush(self):
        pass
    def isatty(self):
        return False

try:
    if sys.stdout is None:
        sys.stdout = _SafeStreamWrapper()
    elif hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr is None:
        sys.stderr = _SafeStreamWrapper()
    elif hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    if getattr(sys, '__stdout__', None) is None:
        sys.__stdout__ = sys.stdout
    if getattr(sys, '__stderr__', None) is None:
        sys.__stderr__ = sys.stderr
    
    # Protege tqdm contra NoneType.write em ambientes sem terminal (ex: pythonw / threads)
    import tqdm.std as _tqdm_std
    _orig_tqdm_init = _tqdm_std.tqdm.__init__
    def _safe_tqdm_init(self, *args, **kwargs):
        if kwargs.get('file') is None:
            kwargs['file'] = sys.stderr if sys.stderr is not None else sys.stdout
        if kwargs.get('file') is None:
            kwargs['file'] = _SafeStreamWrapper()
        return _orig_tqdm_init(self, *args, **kwargs)
    _tqdm_std.tqdm.__init__ = _safe_tqdm_init
    from tqdm import tqdm
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
        "groq_api_key": "",
        "groq_api_keys": [],
        "groq_model": "qwen/qwen3.8-27b",
        "groq_vision_model": "qwen/qwen3.8-27b",
        "groq_fallback_model": "openai/gpt-oss-120b",
        "openrouter_api_key": "",
        "openrouter_api_keys": [],
        "openrouter_model": "nvidia/nemotron-3.5-lightning:free",
        "openrouter_fallback_model": "google/gemma-4-31b-it:free",
        "openrouter_vision_model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "gemini_api_key": "",
        "gemini_api_keys": [],
        "gemini_model": "gemini-2.5-flash",
        "ollama_host": "http://localhost:11434",
        "ollama_model": "dolphin-llama3:latest",
        "ollama_vision_model": "",
        "vision_provider": "auto",
        "temperature": 0.0
    }
    # Restaura perfil salvo no Google Drive se disponível
    drive_profile_cfg = "/content/drive/MyDrive/.manga_studio/config.json"
    if os.path.exists(drive_profile_cfg):
        try:
            with open(drive_profile_cfg, "r", encoding="utf-8") as df:
                cfg.update(json.load(df))
        except Exception:
            pass

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                cfg.update(user_cfg)
        except Exception as e:
            print(f"[*] Aviso ao ler config.json: {e}")

    # Variáveis de ambiente
    if os.environ.get("GROQ_API_KEY"):
        cfg["groq_api_key"] = os.environ.get("GROQ_API_KEY")
    if os.environ.get("GROQ_API_KEYS"):
        cfg["groq_api_keys"] = [k.strip() for k in os.environ.get("GROQ_API_KEYS").split(",") if k.strip()]
    if os.environ.get("GROQ_MODEL"):
        cfg["groq_model"] = os.environ.get("GROQ_MODEL")
    if os.environ.get("GROQ_VISION_MODEL"):
        cfg["groq_vision_model"] = os.environ.get("GROQ_VISION_MODEL")
    if os.environ.get("OPENROUTER_API_KEY"):
        cfg["openrouter_api_key"] = os.environ.get("OPENROUTER_API_KEY")
    if os.environ.get("OPENROUTER_API_KEYS"):
        cfg["openrouter_api_keys"] = [k.strip() for k in os.environ.get("OPENROUTER_API_KEYS").split(",") if k.strip()]
    if os.environ.get("OPENROUTER_VISION_MODEL"):
        cfg["openrouter_vision_model"] = os.environ.get("OPENROUTER_VISION_MODEL")
    if os.environ.get("GEMINI_API_KEY"):
        cfg["gemini_api_key"] = os.environ.get("GEMINI_API_KEY")
    if os.environ.get("GEMINI_API_KEYS"):
        cfg["gemini_api_keys"] = [k.strip() for k in os.environ.get("GEMINI_API_KEYS").split(",") if k.strip()]
    if os.environ.get("GEMINI_MODEL"):
        cfg["gemini_model"] = os.environ.get("GEMINI_MODEL")
    if os.environ.get("VISION_PROVIDER"):
        cfg["vision_provider"] = os.environ.get("VISION_PROVIDER")
    if os.environ.get("OLLAMA_HOST"):
        cfg["ollama_host"] = os.environ.get("OLLAMA_HOST")
    if os.environ.get("OLLAMA_VISION_MODEL"):
        cfg["ollama_vision_model"] = os.environ.get("OLLAMA_VISION_MODEL")
    if os.environ.get("TRANSLATE_PROVIDER"):
        cfg["provider"] = os.environ.get("TRANSLATE_PROVIDER")
    if os.environ.get("MANGA_TRANSLATE_MODEL"):
        cfg["ollama_model"] = os.environ.get("MANGA_TRANSLATE_MODEL")
        cfg["openrouter_model"] = os.environ.get("MANGA_TRANSLATE_MODEL")
        cfg["groq_model"] = os.environ.get("MANGA_TRANSLATE_MODEL")

    # Argumentos CLI
    if cli_args:
        if cli_args.get("provider"):
            cfg["provider"] = cli_args["provider"]
        if cli_args.get("model"):
            cfg["ollama_model"] = cli_args["model"]
            cfg["openrouter_model"] = cli_args["model"]
            cfg["groq_model"] = cli_args["model"]
        if cli_args.get("host"):
            cfg["ollama_host"] = cli_args["host"]
        if cli_args.get("key"):
            k_cli = str(cli_args["key"]).strip()
            if k_cli.startswith("gsk_"):
                cfg["groq_api_key"] = k_cli
            elif k_cli.startswith("AIza"):
                cfg["gemini_api_key"] = k_cli
            else:
                cfg["openrouter_api_key"] = k_cli
        if cli_args.get("groq_key"):
            cfg["groq_api_key"] = cli_args["groq_key"]

    # Consolidação do Pool de Chaves OpenRouter sem duplicatas (com isolamento de provedores)
    keys_pool = []
    raw_keys = cfg.get("openrouter_api_keys", [])
    if isinstance(raw_keys, list):
        for k in raw_keys:
            k_s = str(k).strip() if isinstance(k, str) else ""
            if k_s and not k_s.startswith(("gsk_", "AIza")) and k_s not in keys_pool:
                keys_pool.append(k_s)
    elif isinstance(raw_keys, str) and raw_keys.strip():
        for k in raw_keys.split(","):
            k_s = k.strip()
            if k_s and not k_s.startswith(("gsk_", "AIza")) and k_s not in keys_pool:
                keys_pool.append(k_s)

    single_k = str(cfg.get("openrouter_api_key", "")).strip()
    if single_k and not single_k.startswith(("gsk_", "AIza")) and single_k not in keys_pool:
        keys_pool.insert(0, single_k)

    cfg["openrouter_api_keys"] = keys_pool
    if keys_pool and not cfg.get("openrouter_api_key"):
        cfg["openrouter_api_key"] = keys_pool[0]
    elif str(cfg.get("openrouter_api_key", "")).startswith(("gsk_", "AIza")):
        cfg["openrouter_api_key"] = keys_pool[0] if keys_pool else ""

    # Consolidação do Pool de Chaves Groq sem duplicatas (com isolamento de provedores)
    groq_pool = []
    raw_groq_keys = cfg.get("groq_api_keys", [])
    if isinstance(raw_groq_keys, list):
        for k in raw_groq_keys:
            k_s = str(k).strip() if isinstance(k, str) else ""
            if k_s and not k_s.startswith(("sk-or-", "AIza")) and k_s not in groq_pool:
                groq_pool.append(k_s)
    elif isinstance(raw_groq_keys, str) and raw_groq_keys.strip():
        for k in raw_groq_keys.split(","):
            k_s = k.strip()
            if k_s and not k_s.startswith(("sk-or-", "AIza")) and k_s not in groq_pool:
                groq_pool.append(k_s)

    single_g = str(cfg.get("groq_api_key", "")).strip()
    if single_g and not single_g.startswith(("sk-or-", "AIza")) and single_g not in groq_pool:
        groq_pool.insert(0, single_g)

    cfg["groq_api_keys"] = groq_pool
    if groq_pool and not cfg.get("groq_api_key"):
        cfg["groq_api_key"] = groq_pool[0]
    elif str(cfg.get("groq_api_key", "")).startswith(("sk-or-", "AIza")):
        cfg["groq_api_key"] = groq_pool[0] if groq_pool else ""

    # Consolidação do Pool de Chaves Google Gemini sem duplicatas (com isolamento de provedores)
    gemini_pool = []
    raw_gemini_keys = cfg.get("gemini_api_keys", [])
    if isinstance(raw_gemini_keys, list):
        for k in raw_gemini_keys:
            k_s = str(k).strip() if isinstance(k, str) else ""
            if k_s and not k_s.startswith(("gsk_", "sk-or-")) and k_s not in gemini_pool:
                gemini_pool.append(k_s)
    elif isinstance(raw_gemini_keys, str) and raw_gemini_keys.strip():
        for k in raw_gemini_keys.split(","):
            k_s = k.strip()
            if k_s and not k_s.startswith(("gsk_", "sk-or-")) and k_s not in gemini_pool:
                gemini_pool.append(k_s)

    single_gem = str(cfg.get("gemini_api_key", "")).strip()
    if single_gem and not single_gem.startswith(("gsk_", "sk-or-")) and single_gem not in gemini_pool:
        gemini_pool.insert(0, single_gem)

    cfg["gemini_api_keys"] = gemini_pool
    if gemini_pool and not cfg.get("gemini_api_key"):
        cfg["gemini_api_key"] = gemini_pool[0]
    elif str(cfg.get("gemini_api_key", "")).startswith(("gsk_", "sk-or-")):
        cfg["gemini_api_key"] = gemini_pool[0] if gemini_pool else ""

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
            
    # 2. Pensamentos, sussurros, notas e diálogos suaves (itálico com suporte completo a acentos PT-BR)
    if is_thought or (clean.startswith('(') and clean.endswith(')')) or '~' in clean or clean.startswith('*'):
        if os.path.exists(DIALOGUE_ITALIC_FONT):
            return DIALOGUE_ITALIC_FONT
        if os.path.exists(ANIME_ACE_ITALIC) and not re.search(r'[ÁÀÂÃÉÊÍÓÔÕÚÜÇáàâãéêíóôõúüç]', clean):
            return ANIME_ACE_ITALIC
        if os.path.exists(MANGA_TEMPLE_ITALIC) and not re.search(r'[ÁÀÂÃÉÊÍÓÔÕÚÜÇáàâãéêíóôõúüç~]', clean):
            return MANGA_TEMPLE_ITALIC
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
        '‐': '-',
        '\u2011': '-',
        '\u2012': '-',
        '―': '-',
        '—': '-',
        '–': '-',
        '−': '-',
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
        fsize = int(getattr(font, 'size', 0) or 0)
        cache_key = (fpath, fsize)
        if cache_key not in _NOTDEF_CACHE:
            _NOTDEF_CACHE[cache_key] = bytes(font.getmask(chr(0xFFFF)))
        notdef = _NOTDEF_CACHE[cache_key]
        m = bytes(font.getmask(char))
        return m != notdef and len(m) > 0
    except Exception:
        return False

def get_glyph_font(char, primary_font):
    """Encontra a melhor fonte da cadeia tipográfica para o caractere, garantindo ZERO quadrados 'tofu'."""
    if is_char_supported(char, primary_font):
        return primary_font
        
    fsize = getattr(primary_font, 'size', 20)
    
    # Cadeia de fontes de fallback multiplataforma (Windows + Linux/Colab + embutidas):
    # 1. Símbolos, corações, notas musicais, estrelas
    # 2. Fonte de diálogo local com cobertura latina completa + DejaVu/Noto Linux
    # 3. Caracteres CJK (chinês, japonês, coreano)
    fallback_candidates = [
        ("sym", r"C:\Windows\Fonts\seguisym.ttf"),
        ("dialogue_fb", DIALOGUE_FONT),
        ("komika_fb", KOMIKA_FONT),
        ("cjk", r"C:\Windows\Fonts\msyh.ttc"),
        ("cjk_jp", r"C:\Windows\Fonts\msgothic.ttc"),
        ("segoe", r"C:\Windows\Fonts\segoeui.ttf"),
        ("emj", r"C:\Windows\Fonts\seguiemj.ttf"),
        ("lin_dejavu", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("lin_liberation", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("lin_cjk", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
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

_LINE_WIDTH_CACHE = {}

def measure_manga_line_width(draw, line, font, stroke_width=0):
    """Mede a largura exata em pixels correspondente ao desenho caractere por caractere de draw_manga_text_line."""
    line = sanitize_lettering_text(line)
    if not line:
        return 0.0
    fpath = getattr(font, 'path', '')
    fsize = getattr(font, 'size', 20)
    key = (fpath, fsize, line, int(stroke_width))
    cached = _LINE_WIDTH_CACHE.get(key)
    if cached is not None:
        return cached

    tot_w = 0.0
    has_chars = False
    for c in line:
        if c.isspace():
            bb = draw.textbbox((0, 0), " ", font=font)
            tot_w += max(4, bb[2] - bb[0])
            continue
        use_f = get_glyph_font(c, font)
        if use_f is None:
            continue
        has_chars = True
        bb = draw.textbbox((0, 0), c, font=use_f)
        tot_w += max(1, bb[2] - bb[0])

    if has_chars and stroke_width > 0:
        tot_w += stroke_width * 2.0

    if len(_LINE_WIDTH_CACHE) > 20000:
        _LINE_WIDTH_CACHE.clear()
    _LINE_WIDTH_CACHE[key] = tot_w
    return tot_w

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
                is_local = os.path.dirname(os.path.abspath(c)) == os.path.abspath(manga_dir)
                if c.endswith(".json"):
                    with open(c, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            # Nomes de personagens SÓ são carregados se for o glossário local da própria obra
                            if is_local:
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

def _filter_learning_rules_for_lang(lines, src_lang="auto"):
    """Filtra regras de aprendizado específicas de outros idiomas/obras para economizar tokens em cotas TPM sem perder regras gerais."""
    if not src_lang or src_lang == "auto":
        return lines

    is_asian_ko = (src_lang == "ko-KR")
    is_asian_zh_ja = src_lang in ("zh-CN", "ja-JP")
    is_latin = src_lang in ("en-US", "es-ES")

    filtered = []
    skip_work_block = False
    for line in lines:
        s = line.strip()
        if "DIRETRIZES ESPECÍFICAS DE OBRAS" in s or "DIRETRIZES ESPECIFICAS DE OBRAS" in s:
            skip_work_block = True
            continue
        if skip_work_block:
            if not s.startswith("*") and not s.startswith("- "):
                skip_work_block = False
            elif s.startswith("- ") and not any(k in s for k in ("Boku no", "Slave Is", "奴隶", "Yu-kun")):
                skip_work_block = False
            else:
                if is_latin and ("Boku no Toshiue" in s or "Yu-kun" in s):
                    pass
                elif is_asian_zh_ja and ("Slave Is" in s or "奴隶" in s):
                    pass
                else:
                    continue

        if is_asian_ko:
            if re.search(r'[\u4e00-\u9fff]', s) and not re.search(r'[\uac00-\ud7af]', s):
                continue
            if re.match(r'^[*•-]\s*[a-zA-Z0-9\s\'/\-~!?,]+->', s) and not re.search(r'[\uac00-\ud7af]', s):
                continue
            if any(marker in s for marker in ("Boku no Toshiue", "Slave Is", "Come hang out:", "It's hard (", "Fr I END (", "MARCAS D'ÁGUA DE SCANS CHINESES")):
                continue
        elif is_latin:
            if re.search(r'[\u4e00-\u9fff\uac00-\ud7af\u3040-\u30ff]', s) and "-> " in s:
                continue
            if any(marker in s for marker in ("Slave Is", "MARCAS D'ÁGUA DE SCANS CHINESES", "888 / 8888888")):
                continue

        filtered.append(line)
    return filtered

def load_learning_rules(src_lang="auto"):
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

    if src_lang and src_lang != "auto":
        dos = _filter_learning_rules_for_lang(dos, src_lang=src_lang)
        donts = _filter_learning_rules_for_lang(donts, src_lang=src_lang)

    return dos, donts

def lookup_translation_memory(orig_text):
    """Consulta a memória global de tradução para reutilizar frases aprendidas perfeitamente."""
    if not os.path.exists(GLOBAL_TRANSLATION_MEMORY):
        return None
    clean_key = str(orig_text or "").strip()
    # Palavras curtas em Hangul/CJK dependem 100% do contexto da cena e não devem pular o tradutor contextual
    if re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', clean_key) and len(clean_key) <= 6:
        return None
    try:
        with open(GLOBAL_TRANSLATION_MEMORY, "r", encoding="utf-8") as f:
            mem = json.load(f)
        hit = mem.get(clean_key)
        if hit and ("<x " in str(hit) or "MYMEMORY" in str(hit).upper()):
            return None
        return hit
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
        o_s = str(orig or "").strip()
        t_s = str(trans or "").strip()
        if not t_s or o_s == t_s or len(o_s) < 4:
            continue
        if "<x " in t_s or "MYMEMORY" in t_s.upper() or re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', t_s):
            continue
        mem[o_s] = t_s
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

def get_image_files(directory):
    """Retorna lista ordenada com caminhos completos de todas as imagens suportadas em um diretório (imune a colchetes e caracteres especiais no caminho)."""
    if not directory or not os.path.exists(directory) or not os.path.isdir(directory):
        return []
    valid_exts = ('.webp', '.jpg', '.jpeg', '.png', '.bmp')
    try:
        files = [
            os.path.join(directory, f) for f in os.listdir(directory)
            if f.lower().endswith(valid_exts) and os.path.isfile(os.path.join(directory, f))
        ]
        files.sort(key=lambda p: natural_sort_key(os.path.basename(p)))
        return files
    except Exception as e:
        print(f"[!] Erro ao listar imagens em {directory}: {e}")
        return []

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
    if ko_chars >= 4 and ko_chars > jp_kana and ko_chars >= cjk_ideographs:
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
    clean_s = text.strip()
    # 0. Sequências de 888 / 8888888 (danmaku de palmas / aplausos / sexo pele com pele '啪啪啪' em scans chineses)
    if re.match(r'^(?:8{2,}|8{2,}[\s8]+)$', clean_s):
        return "CLAP CLAP"
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
    'PT-BR', 'R18', 'PDF', 'JPG', 'PNG', 'WEBP', 'NORUN', 'MISHA', 'CHISE', 'LOVEMEA',
    'MADOROMI', 'MIYOBI', 'FURIYA', 'ROCHE'
}

VALID_2LETTER_WORDS = {'in', 'on', 'at', 'to', 'is', 'it', 'he', 'me', 'we', 'my', 'by', 'up', 'so', 'do', 'no', 'go', 'if', 'as', 'of', 'or', 'am', 'an', 'us'}

def repair_glued_text(text, src_lang="en-US"):
    """Separa palavras coladas no OCR em inglês/latino com proteção estrita para nomes, romaji e palavras reais."""
    if not text or src_lang in ("ja-JP", "zh-CN", "ko-KR"):
        return text
        
    if re.match(r'^(?:https?://|www\.|discord\.gg)', text, re.IGNORECASE):
        return text

    # 1. Corrige quebras de linha com hífens preservando honoríficos japoneses
    honorifics = {'san', 'sama', 'kun', 'chan', 'dono', 'senpai', 'sensei', 'tan'}
    def _fix_hyphen(m):
        w1, w2 = m.group(1), m.group(2)
        if w2.lower() in honorifics:
            return f"{w1}-{w2}"
        return f"{w1}{w2}"
    text = re.sub(r'([A-Za-z]+)-\s+([A-Za-z]+)', _fix_hyphen, text)

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

    lm = getattr(wordninja, 'DEFAULT_LANGUAGE_MODEL', None)
    tokens = text.split()
    fixed_tokens = []
    
    for token in tokens:
        clean_tok = re.sub(r'[^a-zA-Z]', '', token)
        # Palavras curtas (< 7 letras) NÃO devem ser separadas por wordninja para não quebrar romaji e nomes
        if len(clean_tok) < 7:
            fixed_tokens.append(token)
            continue
        
        # Preserva palavras reservadas e nomes
        if clean_tok.upper() in PRESERVE_WORDS:
            fixed_tokens.append(token)
            continue

        clean_low = clean_tok.lower()
        # Se a palavra já existe no dicionário/modelo de linguagem com boa frequência, NUNCA divida
        if lm and clean_low in lm._wordcost and lm._wordcost[clean_low] < 12.0:
            fixed_tokens.append(token)
            continue
            
        # Palavras em TitleCase (iniciadas com maiúscula) em mangás são quase sempre Nomes Próprios
        if clean_tok[0].isupper() and clean_tok[1:].islower():
            fixed_tokens.append(token)
            continue

        # Proteção contra sufixos comuns em inglês (masterless, beastkin, etc.)
        is_suffix = False
        for sfx in ('less', 'ness', 'ship', 'ful', 'able', 'like', 'ward', 'wise', 'kin'):
            if clean_low.endswith(sfx):
                base = clean_low[:-len(sfx)]
                if lm and base in lm._wordcost and lm._wordcost[base] < 11.0:
                    is_suffix = True
                    break
        if is_suffix:
            fixed_tokens.append(token)
            continue

        splits = wordninja.split(clean_tok)
        if len(splits) >= 2 and len(splits) < len(clean_tok):
            # Valida rigorosamente cada fragmento
            valid = True
            for s in splits:
                s_low = s.lower()
                if len(s) == 1 and s_low not in {'a', 'i'}:
                    valid = False
                    break
                if len(s) == 2 and s_low not in VALID_2LETTER_WORDS:
                    valid = False
                    break
                if lm:
                    cost = lm._wordcost.get(s_low, 999.0)
                    if cost > 11.0:
                        valid = False
                        break

            if valid:
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

def smart_join_lines(lines, is_cjk=False, preserve_spaces=False):
    """Junta linhas de um mesmo balão com inteligência morfológica:
    - Para texto japonês/chinês (CJK sem espaços), junta sem espaços.
    - Para Coreano (Hangul) ou texto latino, preserva espaços entre linhas."""
    if not lines:
        return ""
    cleaned_lines = [str(l).strip() for l in lines if l and str(l).strip()]
    if not cleaned_lines:
        return ""
    if is_cjk:
        return " ".join(cleaned_lines) if preserve_spaces else "".join(cleaned_lines)
    
    honorifics = {'san', 'sama', 'kun', 'chan', 'dono', 'senpai', 'sensei', 'tan'}
    text = cleaned_lines[0]
    for nxt in cleaned_lines[1:]:
        if text.endswith('-'):
            clean_nxt = nxt.lstrip('-').strip()
            first_w = re.sub(r'[^a-zA-Z]', '', clean_nxt.split()[0]).lower() if clean_nxt else ''
            if first_w in honorifics or (len(first_w) >= 3 and first_w.startswith('s') and all(c == 'a' for c in first_w[1:-1])):
                text = text + clean_nxt
            else:
                text = text[:-1] + clean_nxt
        else:
            text = text + " " + nxt
    return text

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

def is_majority_cjk(lines_text):
    """Retorna True apenas se o bloco for genuinamente CJK/Hangul, evitando que 1 símbolo '人'/'一' em balão inglês cole palavras."""
    if not lines_text:
        return False
    joined = " ".join(str(lt) for lt in lines_text if lt)
    cjk_cnt = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", joined))
    if cjk_cnt == 0:
        return False
    latin_cnt = len(re.findall(r"[A-Za-z]", joined))
    if latin_cnt >= 3 and cjk_cnt < latin_cnt:
        return False
    return True

def is_majority_hangul(lines_text):
    """Retorna True se o bloco contiver predominância de Hangul coreano (cujas linhas quebradas devem manter espaço entre palavras)."""
    if not lines_text:
        return False
    joined = " ".join(str(lt) for lt in lines_text if lt)
    ko_cnt = len(re.findall(r"[\uac00-\ud7af]", joined))
    if ko_cnt == 0:
        return False
    zh_ja_cnt = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff]", joined))
    return ko_cnt >= zh_ja_cnt

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
        is_cjk_bubble = is_majority_cjk(lines_text)
        is_ko_bubble = is_majority_hangul(lines_text)
        full_text = smart_join_lines(lines_text, is_cjk=is_cjk_bubble, preserve_spaces=is_ko_bubble)
        if not is_cjk_bubble:
            full_text = repair_glued_text(full_text)
        raw_boxes = []
        for b in comp_blocks:
            if b.get("raw_boxes"):
                raw_boxes.extend(b["raw_boxes"])
            else:
                raw_boxes.append(b["box"])
        orig_line_count = sum(max(1, int(b.get("orig_line_count", len(b.get("lines", [])) or 1))) for b in comp_blocks)
        
        bubbles.append({
            "box": [xmin, ymin, xmax, ymax],
            "raw_boxes": raw_boxes,
            "orig_line_count": orig_line_count,
            "lines": lines_text,
            "combined_text": full_text,
            "is_vertical": is_vertical
        })
        
    bubbles.sort(key=lambda b: (b["box"][1], b["box"][0]))
    return bubbles

def clean_speech_bubble(img, box, balloon_mask=None):
    """Limpeza cirúrgica em multi-camadas:
    - Isola estritamente o entorno da caixa OCR (evita destruir bordas, cabelos e arte externa com padding gigante).
    - Adapta-se à cor real do papel/balão (sem chapar branco puro #FFFFFF em balões off-white ou creme).
    - Trata texto claro em cartão escuro, contorno duplo (outline de SFX) e halos anti-aliased em fundos variados.
    """
    xmin, ymin, xmax, ymax = [int(round(v)) for v in box]
    bw = xmax - xmin
    bh = ymax - ymin
    ih, iw = img.shape[:2]
    if bw <= 0 or bh <= 0 or ih <= 0 or iw <= 0:
        return

    # Área gravável estrita (apenas margem segura de 4-8px para serifs/acentos, NUNCA 40%/45px!)
    pad_x = min(max(4, int(bw * 0.05)), 8)
    pad_y = min(max(4, int(bh * 0.05)), 8)
    ex0 = max(0, xmin - pad_x)
    ey0 = max(0, ymin - pad_y)
    ex1 = min(iw, xmax + pad_x)
    ey1 = min(ih, ymax + pad_y)
    if ex1 <= ex0 or ey1 <= ey0:
        return

    # Janela de contexto (somente leitura) para diferenciar contornos externos/bordas do balão
    ctx_pad = 22
    cx0 = max(0, xmin - ctx_pad)
    cy0 = max(0, ymin - ctx_pad)
    cx1 = min(iw, xmax + ctx_pad)
    cy1 = min(ih, ymax + ctx_pad)

    ctx_roi = img[cy0:cy1, cx0:cx1]
    erase_roi = img[ey0:ey1, ex0:ex1]
    ocr_roi = img[max(0, ymin):min(ih, ymax), max(0, xmin):min(iw, xmax)]
    if ctx_roi.size == 0 or erase_roi.size == 0:
        return

    gray_ctx = cv2.cvtColor(ctx_roi, cv2.COLOR_BGR2GRAY)
    hsv_ctx = cv2.cvtColor(ctx_roi, cv2.COLOR_BGR2HSV)
    gray_erase = cv2.cvtColor(erase_roi, cv2.COLOR_BGR2GRAY)
    gray_ocr = cv2.cvtColor(ocr_roi, cv2.COLOR_BGR2GRAY) if ocr_roi.size > 0 else gray_erase

    # Coordenadas locais da caixa OCR e da zona gravável dentro de ctx_roi
    ox0, oy0 = max(0, xmin - cx0), max(0, ymin - cy0)
    ox1, oy1 = min(ctx_roi.shape[1], xmax - cx0), min(ctx_roi.shape[0], ymax - cy0)
    lx0, ly0 = ex0 - cx0, ey0 - cy0
    lx1, ly1 = ex1 - cx0, ey1 - cy0
    rh, rw = gray_ctx.shape

    white_ratio_erase = float(np.mean(gray_ocr > 188))
    if white_ratio_erase > 0.45:
        # --- CAMADA A: BALÃO CLARO / BRANCO / OFF-WHITE / TINTADO ---
        # Amostra a cor real do papel priorizando o anel interno ao redor da caixa OCR para não confundir contorno branco (#FFF) de letra com papel cinza/tintado
        sample_gray = gray_erase if gray_erase.size >= 16 else gray_ctx
        sample_bgr = erase_roi if erase_roi.size >= 48 else ctx_roi

        rx0, ry0 = max(0, ox0 - 8), max(0, oy0 - 8)
        rx1, ry1 = min(rw, ox1 + 8), min(rh, oy1 + 8)
        ring_mask = np.zeros((rh, rw), dtype=bool)
        ring_mask[ry0:ry1, rx0:rx1] = True
        ring_mask[max(0, oy0):min(rh, oy1), max(0, ox0):min(rw, ox1)] = False
        ring_grays = gray_ctx[ring_mask]
        ring_bright_mask = ring_grays >= 165
        ring_bright = ring_grays[ring_bright_mask] if ring_grays.size > 0 else np.array([])
        used_ring_paper = False

        if ring_bright.size >= 20:
            ring_med = float(np.median(ring_bright))
            ring_p75 = float(np.percentile(ring_bright, 75))
            # Verifica pixels de fundo longe dos traços das letras (separa balão cinza com contorno branco de balão branco sobre retícula)
            ocr_dark = (gray_ocr < 175).astype(np.uint8)
            near_dark = cv2.dilate(ocr_dark, np.ones((7, 7), np.uint8)) > 0
            far_bright = gray_ocr[(~near_dark) & (gray_ocr >= 165)]
            far_ok = True if far_bright.size < 24 else (float(np.median(far_bright)) < 235.0)
            if ring_med < 236 and ring_p75 < 232 and far_ok and float(np.mean(np.abs(gray_ocr.astype(np.int16) - int(round(ring_med))) <= 20)) >= 0.10:
                ring_match = np.abs(ring_bright.astype(np.int16) - int(round(ring_med))) <= 20
                if np.sum(ring_match) >= 12:
                    ring_bgr_pool = ctx_roi[ring_mask][ring_bright_mask][ring_match]
                    med_bgr = np.median(ring_bgr_pool, axis=0)
                    fill_bgr = (int(round(med_bgr[0])), int(round(med_bgr[1])), int(round(med_bgr[2])))
                    used_ring_paper = True

        if not used_ring_paper:
            inner_bright_thr = max(178, int(np.percentile(sample_gray, 55)))
            bright_mask_s = sample_gray >= inner_bright_thr
            if np.sum(bright_mask_s) >= 12:
                bright_px = sample_bgr[bright_mask_s]
                med_bgr = np.median(bright_px, axis=0)
                b_val, g_val, r_val = int(round(med_bgr[0])), int(round(med_bgr[1])), int(round(med_bgr[2]))
                if min(b_val, g_val, r_val) >= 246 and (max(b_val, g_val, r_val) - min(b_val, g_val, r_val)) <= 8:
                    fill_bgr = (255, 255, 255)
                else:
                    fill_bgr = (b_val, g_val, r_val)
            else:
                fill_bgr = (255, 255, 255)

        bg_luma = int(round(0.114 * fill_bgr[0] + 0.587 * fill_bgr[1] + 0.299 * fill_bgr[2]))
        bg_luma = max(165, bg_luma)
        luma_diff = bg_luma - gray_ctx.astype(np.int16)

        # Limiar adaptativo captura inclusive halos cinzentos suaves sem morder o fundo claro
        dark_delta = max(26, int(bg_luma * 0.13))
        is_text = (luma_diff > dark_delta) | ((hsv_ctx[:, :, 1] > 26) & (gray_ctx < min(244, bg_luma - 8)))
        text_mask = is_text.astype(np.uint8) * 255

        contours, _ = cv2.findContours(text_mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        clean_mask = np.zeros_like(text_mask)

        # Máscara restritiva para contornos grandes que encostam na borda externa do balão
        inner_ocr_mask = np.zeros_like(text_mask)
        ix0_in = min(max(0, ox0 + 1), rw)
        iy0_in = min(max(0, oy0 + 1), rh)
        ix1_in = max(ix0_in, min(rw, ox1 - 1))
        iy1_in = max(iy0_in, min(rh, oy1 - 1))
        inner_ocr_mask[iy0_in:iy1_in, ix0_in:ix1_in] = 255

        for c in contours:
            rcx, rcy, rcw, rch = cv2.boundingRect(c)
            touches_ctx_edge = (rcx <= 1 or rcy <= 1 or (rcx + rcw) >= rw - 1 or (rcy + rch) >= rh - 1)
            is_outer_ring = (rcw >= bw + 14 and rch >= bh + 14) or (rcw > bw + 26) or (rch > bh + 26)
            overlaps_text = not (rcx + rcw < ox0 - 5 or rcx > ox1 + 5 or rcy + rch < oy0 - 5 or rcy > oy1 + 5)
            if not overlaps_text:
                continue

            if not touches_ctx_edge and not is_outer_ring:
                cv2.drawContours(clean_mask, [c], -1, 255, -1)
            elif white_ratio_erase > 0.45:
                # Letra tocou a borda do balão: remove somente os traços estritamente dentro da caixa OCR
                single_c = np.zeros_like(text_mask)
                cv2.drawContours(single_c, [c], -1, 255, -1)
                clean_mask |= (single_c & inner_ocr_mask)

        # Varredura de halo anti-aliasing (+ contorno branco em balão cinza/tintado) e confinamento à erase_box
        dil_clean = cv2.dilate(clean_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)
        halo_near = cv2.dilate(clean_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1) > 0
        halo_ring = halo_near & (luma_diff > 12)
        if bg_luma < 236:
            halo_wide = cv2.dilate(clean_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)), iterations=1) > 0
            halo_ring = halo_ring | (halo_wide & ((gray_ctx.astype(np.int16) - bg_luma) > 26))
        final_mask = ((dil_clean > 0) | halo_ring).astype(np.uint8) * 255

        # Nunca pinta fora de erase_box (e respeita balloon_mask se fornecida)
        erase_gate = np.zeros_like(text_mask)
        erase_gate[ly0:ly1, lx0:lx1] = 255
        if balloon_mask is not None:
            bmask_crop = balloon_mask[cy0:cy1, cx0:cx1]
            if bmask_crop.shape == erase_gate.shape:
                erase_gate &= ((bmask_crop > 0).astype(np.uint8) * 255)
        final_mask &= erase_gate
        ctx_roi[final_mask > 0] = fill_bgr
    else:
        # --- CAMADA B: CARTÕES ESCUROS / TEXTURAS / RETÍCULAS / SFX COLORIDOS ---
        # Amostra a moldura periférica fora da caixa OCR (para inferir polaridade e cor base)
        perim_mask = np.ones((rh, rw), dtype=bool)
        px_in0, py_in0 = max(0, ox0 - 1), max(0, oy0 - 1)
        px_in1, py_in1 = min(rw, ox1 + 1), min(rh, oy1 + 1)
        perim_mask[py_in0:py_in1, px_in0:px_in1] = False
        perim_grays = gray_ctx[perim_mask] if np.any(perim_mask) else gray_ctx.ravel()
        outer_med_gray = float(np.median(perim_grays)) if perim_grays.size > 0 else float(np.median(gray_ctx))
        outer_med_bgr = np.median(ctx_roi[perim_mask], axis=0) if np.any(perim_mask) else np.median(ctx_roi.reshape(-1, 3), axis=0)

        is_white_on_dark = (
            (outer_med_gray < 115)
            and (float(np.mean(gray_ocr > max(92, outer_med_gray + 38))) > 0.04)
            and (float(np.mean(gray_ocr < max(110, outer_med_gray + 26))) > 0.30)
        )

        if is_white_on_dark:
            max_ch = np.max(ctx_roi, axis=2)
            lum_thr = min(208, max(88, outer_med_gray + 34))
            cand_mask = ((gray_ctx > lum_thr) | (max_ch > outer_med_gray + 42)).astype(np.uint8) * 255
        else:
            med_local = cv2.medianBlur(gray_ctx, 21)
            dark_fg = ((med_local.astype(np.int16) - gray_ctx.astype(np.int16)) > 24) | (gray_ctx < 115)
            bgr_dist = np.linalg.norm(ctx_roi.astype(np.float32) - outer_med_bgr.astype(np.float32), axis=2)
            color_fg = (hsv_ctx[:, :, 1] > 35) & (bgr_dist > 38)
            base_fg = dark_fg | color_fg

            # Inclui contorno branco de destaque (outline) colado às letras em SFX/retículas
            outline_white = (gray_ctx.astype(np.int16) - med_local.astype(np.int16)) > 36
            near_fg = cv2.dilate(base_fg.astype(np.uint8) * 255, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)), iterations=1) > 0
            cand_mask = (base_fg | (outline_white & near_fg)).astype(np.uint8) * 255

        contours, _ = cv2.findContours(cand_mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        keep_mask = np.zeros_like(cand_mask)
        inner_ocr_mask = np.zeros_like(cand_mask)
        inner_ocr_mask[max(0, oy0):min(rh, oy1), max(0, ox0):min(rw, ox1)] = 255

        for c in contours:
            rcx, rcy, rcw, rch = cv2.boundingRect(c)
            overlaps_text = not (rcx + rcw < ox0 - 3 or rcx > ox1 + 3 or rcy + rch < oy0 - 3 or rcy > oy1 + 3)
            if not overlaps_text:
                continue
            touches_ctx_edge = (rcx <= 1 or rcy <= 1 or (rcx + rcw) >= rw - 1 or (rcy + rch) >= rh - 1)
            huge_bg = (rcw * rch) > (rw * rh * 0.65) and touches_ctx_edge
            if not huge_bg:
                cv2.drawContours(keep_mask, [c], -1, 255, -1)
            else:
                # Fundo escuro conectado com a arte externa: limita apenas à caixa OCR
                single_c = np.zeros_like(cand_mask)
                cv2.drawContours(single_c, [c], -1, 255, -1)
                keep_mask |= (single_c & inner_ocr_mask)

        # Fallback de segurança se quase nada foi selecionado em cartão pequeno
        if np.sum(keep_mask > 0) < 6:
            keep_mask = cand_mask & inner_ocr_mask

        # Confina estritamente à erase_box (pad 5-10px): ZERO pixels borrados fora do texto!
        erase_gate = np.zeros_like(cand_mask)
        erase_gate[ly0:ly1, lx0:lx1] = 255
        final_mask = cv2.dilate(keep_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1) & erase_gate

        if np.any(final_mask > 0):
            if is_white_on_dark and perim_grays.size > 15 and float(np.std(perim_grays)) < 18.0 and outer_med_gray < 75:
                fill_dark = (int(round(outer_med_bgr[0])), int(round(outer_med_bgr[1])), int(round(outer_med_bgr[2])))
                ctx_roi[final_mask > 0] = fill_dark
            else:
                inpainted = cv2.inpaint(ctx_roi, final_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
                img[ey0:ey1, ex0:ex1] = inpainted[ly0:ly1, lx0:lx1]

def analyze_safe_balloon(cleaned_gray, orig_gray, box, limits):
    """
    Camada geométrica anti-extravasamento:
    Detecta o contorno fechado real do balão (descartando rabichos e vazamentos de borda aberta),
    calcula centro seguro ancorado ao texto original e perfil de larguras por altura.
    """
    ih, iw = cleaned_gray.shape[:2]
    xmin, ymin, xmax, ymax = [int(round(v)) for v in box]
    bw = max(1, xmax - xmin)
    bh = max(1, ymax - ymin)
    cx = (xmin + xmax) / 2.0
    cy = (ymin + ymax) / 2.0
    x_min_limit, x_max_limit, y_min_limit, y_max_limit = limits

    ox0, oy0 = max(0, xmin), max(0, ymin)
    ox1, oy1 = min(iw, xmax), min(ih, ymax)
    sub_c = cleaned_gray[oy0:oy1, ox0:ox1]
    sub_o = orig_gray[oy0:oy1, ox0:ox1] if orig_gray is not None else sub_c
    is_white_bg = float(np.mean(sub_c > 175)) > 0.48 if sub_c.size > 0 else True
    is_dark_card = False
    render_white_on_dark = False
    if not is_white_bg and sub_o.size > 0:
        med_c = float(np.median(sub_c))
        med_o = float(np.median(sub_o))
        if med_c < 85 and float(np.mean(sub_c < 105)) > 0.65:
            is_dark_card = True
            if med_o < 90 and float(np.mean(sub_o > max(92, med_o + 40))) > 0.04:
                render_white_on_dark = True

    result = {
        "is_white_bg": is_white_bg,
        "is_dark_card": is_dark_card,
        "render_white_on_dark": render_white_on_dark,
        "is_enclosed": False,
        "shape_type": "rect" if not is_white_bg else "oval",
        "safe_cx": cx,
        "safe_cy": cy,
        "safe_min_x": max(float(xmin), x_min_limit),
        "safe_max_x": min(float(xmax), x_max_limit),
        "safe_min_y": max(float(ymin), y_min_limit),
        "safe_max_y": min(float(ymax), y_max_limit),
        "target_w": float(bw),
        "target_h": float(bh),
        "band_profile": None
    }

    if is_white_bg or is_dark_card:
        # Janela de busca limitada às partições dos vizinhos e expansão proporcional segura
        sx0 = max(int(math.ceil(x_min_limit)), int(xmin - max(60, bw * 0.85)))
        sx1 = min(int(math.floor(x_max_limit)), int(xmax + max(60, bw * 0.85)))
        sy0 = max(int(math.ceil(y_min_limit)), int(ymin - max(50, bh * 0.75)))
        sy1 = min(int(math.floor(y_max_limit)), int(ymax + max(50, bh * 0.75)))

        if sx1 > sx0 + 16 and sy1 > sy0 + 16:
            s_roi = cleaned_gray[sy0:sy1, sx0:sx1]
            sh, sw = s_roi.shape
            if is_white_bg:
                sub_bg = float(np.median(sub_c)) if sub_c.size > 0 else 245.0
                if sub_bg >= 232:
                    b_thresh = int(np.clip(sub_bg - 26, 190, 212))
                elif sub_bg >= 180:
                    b_thresh = int(np.clip(sub_bg - 28, 150, 200))
                else:
                    hi_p = float(np.percentile(s_roi, 75))
                    b_thresh = int(np.clip(hi_p - 30, 150, 210))
                raw_bin = (s_roi > b_thresh).astype(np.uint8) * 255
            else:
                raw_bin = (s_roi < 95).astype(np.uint8) * 255

            # Fecha eventuais pixels residuais minúsculos de letras antigas sem unir balões separados
            closed = cv2.morphologyEx(raw_bin, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            # Corta rabichos estreitos e micro-frestas na borda do balão
            k_tail = max(5, min(9, int(min(bw, bh) * 0.14) | 1))
            opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_tail, k_tail)))

            # Seleciona componente conectado que melhor cobre a caixa OCR original
            lx0 = max(0, ox0 - sx0)
            ly0 = max(0, oy0 - sy0)
            lx1 = min(sw, ox1 - sx0)
            ly1 = min(sh, oy1 - sy0)

            n_lbl, labels, stats, _ = cv2.connectedComponentsWithStats(opened)
            best_lbl = 0
            best_score = 0
            if lx1 > lx0 and ly1 > ly0 and n_lbl > 1:
                crop_lbl = labels[ly0:ly1, lx0:lx1]
                vals, counts = np.unique(crop_lbl[crop_lbl > 0], return_counts=True)
                for v, cnt in zip(vals, counts):
                    if cnt > best_score:
                        best_score = int(cnt)
                        best_lbl = int(v)

            if best_lbl == 0 and n_lbl <= 1:
                n_lbl2, labels2, stats2, _ = cv2.connectedComponentsWithStats(closed)
                if lx1 > lx0 and ly1 > ly0 and n_lbl2 > 1:
                    crop_lbl2 = labels2[ly0:ly1, lx0:lx1]
                    vals, counts = np.unique(crop_lbl2[crop_lbl2 > 0], return_counts=True)
                    if len(counts) > 0:
                        idx_m = int(np.argmax(counts))
                        best_lbl = int(vals[idx_m])
                        best_score = int(counts[idx_m])
                        labels = labels2
                        stats = stats2

            if best_lbl > 0 and best_score > 16:
                comp = (labels == best_lbl).astype(np.uint8)
                cx_bb, cy_bb, cw_bb, ch_bb, area_bb = stats[best_lbl]

                # Checagem anti-vazamento (detecta fundo aberto sem borda)
                top_touch = float(np.mean(comp[0, :] > 0))
                bot_touch = float(np.mean(comp[-1, :] > 0))
                left_touch = float(np.mean(comp[:, 0] > 0))
                right_touch = float(np.mean(comp[:, -1] > 0))
                open_sides = sum(1 for t in (top_touch, bot_touch, left_touch, right_touch) if t > 0.38)
                fill_roi = float(np.mean(comp > 0))
                leaked_wide = (open_sides >= 2 and fill_roi > 0.62) or (
                    open_sides >= 1 and ((cw_bb > max(bw * 2.15, bw + 125)) or (ch_bb > max(bh * 2.15, bh + 125)))
                )

                if not leaked_wide:
                    result["is_enclosed"] = True
                    # Fecha furos internos estritamente cercados pelo balão (pontos residuais não podem furar o perfil)
                    inv_comp = ((comp == 0).astype(np.uint8) * 255)
                    pad_inv = cv2.copyMakeBorder(inv_comp, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=255)
                    ff_mask = np.zeros((pad_inv.shape[0] + 2, pad_inv.shape[1] + 2), np.uint8)
                    cv2.floodFill(pad_inv, ff_mask, (0, 0), 128)
                    holes_comp = (pad_inv[1:-1, 1:-1] == 255).astype(np.uint8)
                    if np.any(holes_comp) and int(np.sum(holes_comp)) < max(400, int(area_bb * 0.35)):
                        comp = (comp | holes_comp).astype(np.uint8)

                    rect_fill = float(np.sum(comp > 0)) / max(1.0, float(cw_bb * ch_bb))
                    result["shape_type"] = "rect" if (rect_fill >= 0.85 or is_dark_card) else "oval"

                    # Encontra centro seguro dentro da área interior ancorado ao centro OCR original
                    dist = cv2.distanceTransform(comp, cv2.DIST_L2, 5)
                    max_dx = min(bw * 0.30, 32.0)
                    max_dy = min(bh * 0.30, 32.0)
                    ax0 = max(0, int(round((cx - max_dx) - sx0)))
                    ax1 = min(sw, int(round((cx + max_dx) - sx0)) + 1)
                    ay0 = max(0, int(round((cy - max_dy) - sy0)))
                    ay1 = min(sh, int(round((cy + max_dy) - sy0)) + 1)
                    if ax1 > ax0 and ay1 > ay0 and np.any(comp[ay0:ay1, ax0:ax1]):
                        sub_d = dist[ay0:ay1, ax0:ax1]
                        py_m, px_m = np.unravel_index(np.argmax(sub_d), sub_d.shape)
                        local_cx = ax0 + int(px_m)
                        local_cy = ay0 + int(py_m)
                    else:
                        local_cx = int(np.clip(round(cx - sx0), 0, sw - 1))
                        local_cy = int(np.clip(round(cy - sy0), 0, sh - 1))

                    # Verifica coluna/linha contínua ao redor do centro
                    row_comp = comp[local_cy, :] > 0
                    col_comp = comp[:, local_cx] > 0

                    def _cont_span(arr, idx_c):
                        if not arr[idx_c]:
                            hits = np.where(arr)[0]
                            if len(hits) == 0:
                                return idx_c, idx_c
                            idx_c = int(hits[np.argmin(np.abs(hits - idx_c))])
                        l_i = idx_c
                        while l_i > 0 and arr[l_i - 1]:
                            l_i -= 1
                        r_i = idx_c
                        while r_i < len(arr) - 1 and arr[r_i + 1]:
                            r_i += 1
                        return l_i, r_i

                    rx_l, rx_r = _cont_span(row_comp, local_cx)
                    ry_t, ry_b = _cont_span(col_comp, local_cy)

                    inner_pad = max(4, min(9, int(round(min(bw, bh) * 0.08))))
                    smx = max(float(sx0 + rx_l + inner_pad), x_min_limit)
                    smax = min(float(sx0 + rx_r - inner_pad), x_max_limit)
                    smy = max(float(sy0 + ry_t + inner_pad), y_min_limit)
                    smay = min(float(sy0 + ry_b - inner_pad), y_max_limit)

                    if smax > smx + 18 and smay > smy + 18:
                        cand_cx = (smx + smax) / 2.0
                        cand_cy = (smy + smay) / 2.0
                        # Limita deslocamento extremo de centro mesmo dentro de balões muito assimétricos
                        cand_cx = float(np.clip(cand_cx, cx - max_dx, cx + max_dx))
                        cand_cy = float(np.clip(cand_cy, cy - max_dy, cy + max_dy))
                        # Re-centraliza largura/altura simétricas disponíveis em torno do cand_cx/cy
                        half_w = min(cand_cx - smx, smax - cand_cx)
                        if half_w >= 14:
                            smx = cand_cx - half_w
                            smax = cand_cx + half_w
                        result["safe_cx"] = cand_cx
                        result["safe_cy"] = cand_cy
                        result["safe_min_x"] = smx
                        result["safe_max_x"] = smax
                        result["safe_min_y"] = smy
                        result["safe_max_y"] = smay
                        result["target_w"] = max(24.0, smax - smx)
                        result["target_h"] = max(24.0, smay - smy)

                        # Constrói perfil real de larguras por faixa vertical (9 amostras entre topo e base)
                        y_in0 = max(0, int(round(smy - sy0)))
                        y_in1 = min(sh - 1, int(round(smay - sy0)))
                        lcx_final = int(np.clip(round(cand_cx - sx0), 0, sw - 1))
                        if y_in1 > y_in0 + 6:
                            profile = []
                            for frac in np.linspace(0.0, 1.0, 9):
                                yy = int(round(y_in0 + frac * (y_in1 - y_in0)))
                                row_ws = []
                                for dy in range(-2, 3):
                                    ryy = int(np.clip(yy + dy, y_in0, y_in1))
                                    if comp[ryy, lcx_final] > 0:
                                        rl, rr = _cont_span(comp[ryy, :] > 0, lcx_final)
                                        ah = min(lcx_final - (rl + inner_pad), (rr - inner_pad) - lcx_final)
                                        if ah > 0:
                                            row_ws.append(float(ah * 2.0))
                                if not row_ws:
                                    rl, rr = _cont_span(comp[yy, :] > 0, lcx_final)
                                    ah = min(lcx_final - (rl + inner_pad), (rr - inner_pad) - lcx_final)
                                    w_safe = max(18.0, float(ah * 2.0))
                                else:
                                    w_safe = max(18.0, float(np.median(row_ws)))
                                profile.append((float(frac), min(result["target_w"], w_safe)))
                            result["band_profile"] = profile
                        return result

    # Fallback seguro (fundo texturizado, SFX aberto ou borda aberta): mantém ancoragem no texto OCR original
    result["is_enclosed"] = False
    result["safe_cx"] = float(np.clip(cx, x_min_limit + 10, max(x_min_limit + 10, x_max_limit - 10)))
    result["safe_cy"] = float(np.clip(cy, y_min_limit + 10, max(y_min_limit + 10, y_max_limit - 10)))
    max_tw = min((result["safe_cx"] - x_min_limit) * 2.0, (x_max_limit - result["safe_cx"]) * 2.0)
    max_th = min((result["safe_cy"] - y_min_limit) * 2.0, (y_max_limit - result["safe_cy"]) * 2.0)
    fallback_w = max(bw * 1.15, min(bw + 24.0, bw * 1.25))
    # Para coluna vertical CJK estreita em margem lisa (branca ou cinza claro) sem arte ao lado, permite abertura horizontal controlada
    if is_white_bg and bw < 60 and bh > bw * 1.8 and max_tw > bw + 30:
        cand_w = min(max_tw * 0.85, max(90.0, min(145.0, bh * 0.72)))
        wx0 = max(int(math.ceil(x_min_limit)), int(round(result["safe_cx"] - cand_w / 2.0)))
        wx1 = min(int(math.floor(x_max_limit)), int(round(result["safe_cx"] + cand_w / 2.0)))
        wy0 = max(0, int(ymin))
        wy1 = min(ih, int(ymax))
        inner_bg = float(np.median(sub_c)) if sub_c.size > 0 else 255.0
        if wx1 > wx0 + bw and wy1 > wy0 + 10 and inner_bg > 165:
            side_patch = cleaned_gray[wy0:wy1, wx0:wx1].astype(np.float32)
            if side_patch.size > 0:
                uniform_frac = float(np.mean(np.abs(side_patch - inner_bg) < 26.0))
                dark_frac = float(np.mean(side_patch < (inner_bg - 38.0)))
                if uniform_frac > 0.86 and dark_frac < 0.08:
                    fallback_w = max(fallback_w, float(wx1 - wx0 - 6))
    result["target_w"] = max(28.0, min(max_tw if max_tw > 28 else bw, fallback_w))
    result["target_h"] = max(26.0, min(max_th if max_th > 26 else bh, max(bh * 1.10, bh + 12.0)))
    result["safe_min_x"] = result["safe_cx"] - result["target_w"] / 2.0
    result["safe_max_x"] = result["safe_cx"] + result["target_w"] / 2.0
    result["safe_min_y"] = result["safe_cy"] - result["target_h"] / 2.0
    result["safe_max_y"] = result["safe_cy"] + result["target_h"] / 2.0
    return result

def _try_hyphenate_word(draw, word, font, max_w, stroke_width=0, min_len=5):
    """Tenta dividir palavra longa em PT-BR com hífen silábico seguro para caber em max_w."""
    if not _pyphen_dic or len(word) < min_len:
        return None
    clean_parts = _pyphen_dic.inserted(word).split('-')
    if len(clean_parts) <= 1:
        return None
    part1 = ""
    p_idx = 0
    best_split = None
    while p_idx < len(clean_parts) - 1:
        cand = part1 + clean_parts[p_idx]
        rem = "".join(clean_parts[p_idx + 1:])
        min_part = 2 if len(word) <= 7 else 3
        if len(cand) >= min_part and len(rem) >= 2:
            if measure_manga_line_width(draw, cand + "-", font, stroke_width) <= max_w:
                part1 = cand
                p_idx += 1
                best_split = (part1 + "-", rem)
                continue
        if len(cand) < min_part:
            part1 = cand
            p_idx += 1
        else:
            break
    return best_split

def wrap_text_to_width(draw, text, font, max_w, stroke_width=0):
    """Quebra texto por palavras usando largura exata (com suporte a hifenização PT-BR e anti-órfãos)."""
    paragraphs = text.split('\n')
    all_lines = []
    min_h_len = 5 if max_w < 140 else 7
    for p in paragraphs:
        words = list(p.split())
        if not words:
            continue
        curr = []
        idx = 0
        while idx < len(words):
            w = words[idx]
            test_l = ' '.join(curr + [w])
            if measure_manga_line_width(draw, test_l, font, stroke_width) <= max_w:
                curr.append(w)
                idx += 1
            else:
                if curr:
                    all_lines.append(' '.join(curr))
                    curr = []
                else:
                    split_res = _try_hyphenate_word(draw, w, font, max_w, stroke_width, min_len=min_h_len)
                    if split_res:
                        all_lines.append(split_res[0])
                        words[idx] = split_res[1]
                    else:
                        all_lines.append(w)
                        idx += 1
        if curr:
            all_lines.append(' '.join(curr))
            
    # Rebalanceamento anti-órfão: evita que a última linha fique com 1 única palavra solta de até 5 letras
    if len(all_lines) >= 2:
        last_words = all_lines[-1].split()
        prev_words = all_lines[-2].split()
        if len(last_words) == 1 and len(last_words[0]) <= 5 and len(prev_words) >= 3:
            word_to_shift = prev_words[-1]
            if not word_to_shift.endswith('-'):
                cand_prev = ' '.join(prev_words[:-1])
                cand_last = word_to_shift + ' ' + all_lines[-1]
                if measure_manga_line_width(draw, cand_last, font, stroke_width) <= max_w:
                    all_lines[-2] = cand_prev
                    all_lines[-1] = cand_last
                
    return all_lines

def wrap_text_diamond(draw, text, font, max_w, max_h, stroke_width=0, shape_type="oval", band_profile=None, line_spacing=1.14):
    """Quebra texto seguindo o formato real do balão (perfil medido / elipse suave / retângulo) com hifenização ativa PT-BR."""
    words = text.split()
    if not words:
        return []
        
    line_bbox = draw.textbbox((0, 0), "Ag", font=font)
    line_h = max(4.0, (line_bbox[3] - line_bbox[1]) * line_spacing)
    max_k = max(1, int(max_h / line_h))

    def get_allowed_w(li, total_lines):
        if band_profile and total_lines >= 1:
            # Calcula a posição Y real do bloco centralizado dentro da altura do balão
            span = min(1.0, (total_lines * line_h) / max(1.0, float(max_h)))
            y_frac = 0.5 + (((li + 0.5) / float(total_lines)) - 0.5) * span
            y_frac = min(1.0, max(0.0, y_frac))
            xs = [pt[0] for pt in band_profile]
            ws = [pt[1] for pt in band_profile]
            return min(max_w, float(np.interp(y_frac, xs, ws)))
        if shape_type == "rect":
            return max_w
        if total_lines <= 1:
            return max_w
        # Balões verticais estreitos têm corpo mais reto (cápsula), ovais largos curvam mais nas pontas
        is_narrow_vert = (max_h > max_w * 1.35) or (max_w < 120)
        curve = 0.52 if is_narrow_vert else 0.72
        min_f = 0.55 if is_narrow_vert else 0.42
        y = ((li + 0.5) - total_lines / 2.0) / (total_lines / 2.0) * curve
        factor = math.sqrt(max(min_f, 1.0 - y * y))
        return max_w * factor

    single_w = measure_manga_line_width(draw, text, font, stroke_width)
    mid_allowed = get_allowed_w(0, 1)
    if single_w <= mid_allowed:
        return [text]

    min_h_len = 5 if max_w < 140 else 7
    best_lines = None
    best_penalty = float('inf')

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
                tw = measure_manga_line_width(draw, test_l, font, stroke_width)
                if tw <= allowed_w:
                    curr.append(w)
                    w_idx += 1
                elif not curr:
                    # Palavra única maior que allowed_w: tenta hifenização silábica primeiro
                    split_res = _try_hyphenate_word(draw, w, font, allowed_w, stroke_width, min_len=min_h_len)
                    if split_res:
                        curr.append(split_res[0])
                        words_copy[w_idx] = split_res[1]
                        break
                    elif tw <= max_w:
                        curr.append(w)
                        w_idx += 1
                    else:
                        possible = False
                        break
                else:
                    break
            if not possible:
                break
            if curr:
                lines.append(' '.join(curr))
            elif w_idx < len(words_copy):
                possible = False
                break
                
        if possible and w_idx == len(words_copy):
            # Verifica estritamente cada linha contra a largura daquela faixa do balão
            all_fit = True
            for idx_l, l_str in enumerate(lines):
                lw = measure_manga_line_width(draw, l_str, font, stroke_width)
                if lw > max_w or (band_profile and lw > get_allowed_w(idx_l, len(lines)) + 2.0):
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
                # Penalidade leve por muitos hífens se uma quebra sem hífen também couber
                penalty += sum(8 for l in lines if l.endswith('-'))
                if penalty < best_penalty:
                    best_penalty = penalty
                    best_lines = lines
                    if penalty == 0:
                        return lines
                        
    if best_lines:
        return best_lines
                
    # Fallback para quebra proporcional linear usando o menor ancho útil ou max_w
    safe_lin_w = min(max_w, min((get_allowed_w(i, max(2, max_k)) for i in range(max(2, max_k))), default=max_w) * 1.15 if band_profile else max_w)
    return wrap_text_to_width(draw, text, font, safe_lin_w, stroke_width=stroke_width)

def fit_text_to_box_ex(draw, text, max_w, max_h, font_path, stroke_width=1, shape_type="oval", band_profile=None, page_w=None, orig_line_h=None, page_med_h=None, is_display=False, pre_padded=False):
    """Ajusta proporcionalmente fonte e quebras com calibração de escala da página, evitando texto minúsculo ou gigante."""
    text = sanitize_lettering_text(text).strip()
    words = text.split()
    if not words:
        return ImageFont.truetype(font_path, 12), [], 1.14
        
    # Quando a caixa já veio com inner_pad de analyze_safe_balloon, evita corte duplo excessivo
    w_mult = 0.92 if (pre_padded or band_profile is not None) else 0.85
    h_mult = 0.90 if (pre_padded or band_profile is not None) else 0.84
    usable_w = max(24, int(max_w * w_mult))
    usable_h = max(24, int(max_h * h_mult))
    scaled_profile = None
    if band_profile:
        scaled_profile = [(p_y, max(20.0, p_w * w_mult)) for (p_y, p_w) in band_profile]

    # Calibração de teto tipográfico: mantém consistência com a resolução da página e tamanho original
    geom_max = int(min(usable_h * 0.45, usable_w * 0.35, 56))
    if page_w and page_w > 100:
        raw_norm = page_w * 0.023
        norm_cap = max(18, min(40, int(round(page_w * 0.0205))))
        ref_h = orig_line_h if (orig_line_h and orig_line_h >= 10) else (page_med_h or page_w * 0.017)
        if is_display or (orig_line_h and orig_line_h > max(34.0, raw_norm * 1.32)):
            scale_cap = min(56, max(norm_cap, int(round(ref_h * 1.15))))
        else:
            med_anchor = page_med_h if (page_med_h and page_med_h >= 10) else ref_h
            max_dial_cap = max(21, min(42, int(round(page_w * 0.0205))))
            scale_cap = min(max_dial_cap, max(16, int(round(max(ref_h * 0.92, med_anchor * 1.15))), int(round(norm_cap * 0.92))))
            scale_cap = min(scale_cap, max(norm_cap, int(round(med_anchor * 1.25))))
            if len(words) <= 2 and len(text) <= 10 and not is_display:
                # Evita que "SIM!" solto exploda em balão enorme
                scale_cap = min(scale_cap, max(18, int(round(max(ref_h * 0.90, med_anchor * 1.12))), int(round(page_w * 0.0195))))
        ideal_max = min(geom_max if len(words) > 2 else max(geom_max, scale_cap), scale_cap)
    else:
        ideal_max = geom_max

    max_font_size = max(14, min(ideal_max, 56))
    min_readable = max(13, int(round((page_w or 1200) * 0.0105)))
    min_readable = min(min_readable, 15)

    def _eff_stroke(fs):
        if stroke_width == 0:
            return 0
        if stroke_width == 1:
            return 1
        return max(2, int(round(fs * 0.08)))

    def _try_search(hi_fs, lo_fs, lead, use_diamond=True):
        for fs in range(hi_fs, lo_fs - 1, -1):
            font = ImageFont.truetype(font_path, fs)
            st = _eff_stroke(fs)
            line_bbox = draw.textbbox((0, 0), "Ag", font=font)
            line_h = max(4.0, (line_bbox[3] - line_bbox[1]) * lead)
            max_lines = int(usable_h / line_h)
            if max_lines < 1:
                continue
            if use_diamond:
                cands = wrap_text_diamond(draw, text, font, usable_w, usable_h, stroke_width=st, shape_type=shape_type, band_profile=scaled_profile, line_spacing=lead)
            else:
                eff_w = usable_w
                if scaled_profile:
                    # Usa largura segura do terço central para modo compacto em balões estreitos (sem colapsar por micro-entalhe)
                    mid_ws = [pw for py, pw in scaled_profile if 0.2 <= py <= 0.8]
                    if mid_ws:
                        safe_mid_w = float(np.percentile(mid_ws, 25)) if len(mid_ws) >= 3 else min(mid_ws)
                        eff_w = min(usable_w, safe_mid_w)
                cands = wrap_text_to_width(draw, text, font, eff_w, stroke_width=st)
            if cands and len(cands) <= max_lines:
                fits_all = True
                span = min(1.0, (len(cands) * line_h) / max(1.0, float(usable_h)))
                for li, l_str in enumerate(cands):
                    lw = measure_manga_line_width(draw, l_str, font, st)
                    lim_w = usable_w
                    if scaled_profile and len(cands) >= 1:
                        yf = 0.5 + (((li + 0.5) / float(len(cands))) - 0.5) * span
                        yf = min(1.0, max(0.0, yf))
                        lim_w = min(usable_w, float(np.interp(yf, [p[0] for p in scaled_profile], [p[1] for p in scaled_profile])) + 1.5)
                    if lw > lim_w:
                        fits_all = False
                        break
                if fits_all:
                    return font, cands, lead
        return None

    # Passo 1: Busca fonte ideal legível (>= min_readable) no formato do balão (leading 1.14)
    res = _try_search(max_font_size, min_readable, 1.14, use_diamond=True)
    if res:
        return res

    # Passo 2: Antes de encolher para micro-texto (<=12px), tenta leading compacto de scanlation (1.06)
    res = _try_search(min(max_font_size, min_readable + 6), min_readable, 1.06, use_diamond=True)
    if res:
        return res

    # Passo 3: Modo linear compacto com hifenização para balões verticais muito estreitos (>= 12px)
    res = _try_search(min(max_font_size, min_readable + 4), 12, 1.07, use_diamond=False)
    if res:
        return res

    # Passo 4: Degradação suave (11 -> 8px) somente quando realmente inevitável
    res = _try_search(11, 8, 1.08, use_diamond=False)
    if res:
        return res

    font = ImageFont.truetype(font_path, 8)
    return font, wrap_text_to_width(draw, text, font, usable_w, stroke_width=_eff_stroke(8)), 1.08

def fit_text_to_box(draw, text, max_w, max_h, font_path, stroke_width=1, shape_type="oval", band_profile=None, page_w=None, orig_line_h=None, page_med_h=None, is_display=False, pre_padded=False):
    """Wrapper retrocompatível de fit_text_to_box_ex retornando (font, lines)."""
    font, lines, _ = fit_text_to_box_ex(
        draw, text, max_w, max_h, font_path,
        stroke_width=stroke_width, shape_type=shape_type, band_profile=band_profile,
        page_w=page_w, orig_line_h=orig_line_h, page_med_h=page_med_h,
        is_display=is_display, pre_padded=pre_padded
    )
    return font, lines

class GroqRateLimitError(RuntimeError):
    """Exceção dedicada para diferenciar limite transitório de TPM/RPM vs esgotamento diário (TPD) no Groq."""
    def __init__(self, message, is_tpm=False, is_daily=False, is_auth=False, retry_after=0.0):
        super().__init__(message)
        self.is_tpm = is_tpm
        self.is_daily = is_daily
        self.is_auth = is_auth
        self.retry_after = retry_after

def _strip_think_tags(text):
    """Remove blocos <think>...</think> de modelos de raciocínio para não vazar na tradução ou quebrar JSON."""
    if not text:
        return ""
    cleaned = re.sub(r'<think>[\s\S]*?</think>', '', str(text), flags=re.IGNORECASE).strip()
    if '<think>' in cleaned.lower():
        cleaned = re.sub(r'<think>[\s\S]*$', '', cleaned, flags=re.IGNORECASE).strip()
    return cleaned

def check_groq_available(api_key, model_name="qwen/qwen3.8-27b"):
    """Verifica se a chave da API do Groq é válida e se o modelo responde."""
    if not api_key or not str(api_key).strip():
        return False, "Chave vazia"
    api_key = str(api_key).strip()
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5
    }
    if "qwen3" in (model_name or "").lower():
        payload["reasoning_effort"] = "none"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                return True, "Chave válida e pronta"
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="ignore").lower()
        except Exception:
            pass
        if e.code == 404:
            for alt_m in ("qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"):
                if alt_m != model_name:
                    ok_alt, msg_alt = check_groq_available(api_key, model_name=alt_m)
                    if ok_alt:
                        return True, msg_alt
        if e.code == 429 and not any(t in err_body for t in ("tokens per day", "requests per day", "tpd", "rpd")):
            return True, "Chave válida (em pausa breve TPM)"
        return False, f"Erro HTTP {e.code}"
    except Exception as e:
        return False, f"Erro de conexão: {e}"
    return False, "Sem resposta"

def query_groq_chat(messages, model_name, api_key, temperature=0.0, max_tokens=600, timeout=45, fallback_model="openai/gpt-oss-120b", max_retries=2, engine_opts=None, allow_tpm_wait=True):
    """Executa requisição à API ultra-rápida do Groq Cloud com resiliência a picos de tokens (TPM) e rotação inteligente de modelos."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    api_key_clean = str(api_key or "").strip()
    if not api_key_clean:
        raise GroqRateLimitError("Chave Groq vazia.", is_auth=True)
    key_sig = api_key_clean[:12]

    exhausted_groq = engine_opts.setdefault("exhausted_groq_models", set()) if engine_opts is not None else set()
    cooldown_map = engine_opts.setdefault("groq_model_cooldowns", {}) if engine_opts is not None else {}

    # Se o modelo ativo já foi alterado pelo fallback, prioriza o ativo (se não estiver em cooldown ou esgotado)
    if engine_opts and engine_opts.get("active_model") and engine_opts["active_model"] not in exhausted_groq:
        act_m = engine_opts["active_model"]
        if cooldown_map.get(f"{key_sig}:{act_m}", 0) <= time.time():
            model_name = act_m

    target_models = []
    cand_list = [
        model_name,
        fallback_model,
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b"
    ]
    for cand in cand_list:
        if cand and cand not in target_models and cand not in exhausted_groq:
            target_models.append(cand)

    if not target_models:
        raise GroqRateLimitError("Todos os modelos Groq para esta chave atingiram a cota diária.", is_daily=True)

    now = time.time()
    ready_models = [m for m in target_models if cooldown_map.get(f"{key_sig}:{m}", 0) <= now]
    if not ready_models:
        # Todos os modelos estão apenas em janela curta de TPM (não esgotados definitivamente)
        soonest_m = min(target_models, key=lambda m: cooldown_map.get(f"{key_sig}:{m}", 0))
        rem_wait = max(0.5, cooldown_map.get(f"{key_sig}:{soonest_m}", now) - now)
        if not allow_tpm_wait or rem_wait > 40.0:
            raise GroqRateLimitError(
                f"Modelos Groq em pausa TPM ({rem_wait:.1f}s).",
                is_tpm=True,
                retry_after=rem_wait
            )
        print(f"\n[*] Groq TPM: aguardando {rem_wait:.1f}s para liberar janela de '{soonest_m}'...")
        time.sleep(min(rem_wait + 0.3, 40.0))
        cooldown_map.pop(f"{key_sig}:{soonest_m}", None)
        ready_models = [soonest_m] + [m for m in target_models if m != soonest_m]

    last_err = None
    saw_tpm_wait = None
    for m in ready_models:
        m_low = m.lower()
        eff_max_tokens = max(int(max_tokens or 600), 1100) if "gpt-oss" in m_low else max(int(max_tokens or 600), 650)
        payload = {
            "model": m,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": eff_max_tokens
        }
        if "qwen3" in m_low:
            payload["reasoning_effort"] = "none"
        elif "gpt-oss" in m_low:
            payload["reasoning_effort"] = "low"

        for attempt in range(max_retries):
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    "Authorization": f"Bearer {api_key_clean}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    res = json.loads(resp.read().decode('utf-8'))
                    if engine_opts is not None:
                        engine_opts["active_model"] = m
                        cooldown_map.pop(f"{key_sig}:{m}", None)
                    raw_out = res.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
                    return _strip_think_tags(raw_out)
            except urllib.error.HTTPError as e:
                last_err = e
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                err_low = err_body.lower()

                if e.code == 429:
                    wait_sec = 4.0
                    try:
                        retry_h = e.headers.get("retry-after")
                        if retry_h:
                            wait_sec = float(retry_h) + 0.5
                        else:
                            m_retry = re.search(r'try again in\s*(?:(\d+)m)?([\d.]+)s', err_low)
                            if m_retry:
                                mins = float(m_retry.group(1) or 0)
                                secs = float(m_retry.group(2) or 0)
                                wait_sec = mins * 60.0 + secs + 0.5
                    except Exception:
                        pass

                    is_daily = any(tok in err_low for tok in ("tokens per day", "requests per day", " tpd", " rpd"))
                    if is_daily:
                        print(f"\n[!] Modelo '{m}' atingiu cota diária (TPD/RPD) no Groq. Alternando modelo...")
                        exhausted_groq.add(m)
                        break

                    # Limite transitório TPM/RPM: se rápido, espera e retenta; caso contrário põe cooldown curto e alterna sem banir o modelo
                    if wait_sec <= 9.0 and attempt < max_retries - 1:
                        print(f"\n[*] Groq em pausa breve TPM ({wait_sec:.1f}s) no modelo '{m}'...")
                        time.sleep(wait_sec)
                        continue
                    else:
                        cd_sec = min(max(wait_sec, 6.0), 65.0)
                        cooldown_map[f"{key_sig}:{m}"] = time.time() + cd_sec
                        if saw_tpm_wait is None or cd_sec < saw_tpm_wait:
                            saw_tpm_wait = cd_sec
                        print(f"\n[*] Pico TPM em '{m}' (~{cd_sec:.0f}s). Alternando para próximo modelo Groq...")
                        break
                elif e.code in (401, 403):
                    raise GroqRateLimitError(f"Chave Groq não autorizada (HTTP {e.code}).", is_auth=True)
                elif e.code in (400, 404):
                    if "reasoning_effort" in err_low and "reasoning_effort" in payload:
                        payload.pop("reasoning_effort", None)
                        continue
                    print(f"\n[!] Modelo '{m}' indisponível no Groq (HTTP {e.code}). Alternando...")
                    exhausted_groq.add(m)
                    break
                elif e.code in (500, 502, 503, 504):
                    if attempt < max_retries - 1:
                        time.sleep(1.5)
                        continue
                    cooldown_map[f"{key_sig}:{m}"] = time.time() + 15.0
                    break
                else:
                    exhausted_groq.add(m)
                    break
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(1.5)
                    continue
                else:
                    cooldown_map[f"{key_sig}:{m}"] = time.time() + 12.0
                    break

    # Se todos os modelos só bateram TPM momentâneo na única chave, faz 1 espera breve se permitido
    if saw_tpm_wait is not None and len(exhausted_groq) < len(target_models):
        rem_cd = max(1.0, min(cooldown_map.get(f"{key_sig}:{m}", time.time()) - time.time() for m in target_models if m not in exhausted_groq))
        if allow_tpm_wait and rem_cd <= 35.0:
            soonest_m = min([m for m in target_models if m not in exhausted_groq], key=lambda m: cooldown_map.get(f"{key_sig}:{m}", 0))
            print(f"\n[*] Pausando {rem_cd:.1f}s para liberar tokens TPM no Groq ({soonest_m})...")
            time.sleep(rem_cd + 0.3)
            cooldown_map.pop(f"{key_sig}:{soonest_m}", None)
            return query_groq_chat(
                messages, soonest_m, api_key_clean, temperature=temperature, max_tokens=max_tokens,
                timeout=timeout, fallback_model=fallback_model, max_retries=1,
                engine_opts=engine_opts, allow_tpm_wait=False
            )
        raise GroqRateLimitError(f"Pico TPM temporário em todos os modelos Groq ({rem_cd:.1f}s).", is_tpm=True, retry_after=rem_cd)

    if last_err:
        raise last_err
    raise RuntimeError("Falha na consulta ao Groq.")

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

def query_openrouter_chat(messages, model_name, api_key=None, temperature=0.0, max_tokens=1024, timeout=75, engine_opts=None, api_keys=None):
    """
    Executa requisição à API do OpenRouter com suporte a Pool de Chaves e Auto-Failover/Rotação imediata.
    Se a chave atual atingir o limite (HTTP 429 / 50 reqs/dia), rotaciona automaticamente para a próxima chave
    cadastrada em 'openrouter_api_keys' no config.json sem interromper a tradução do mangá.
    """
    engine_opts = engine_opts if engine_opts is not None else {}
    cfg_or_keys = (engine_opts.get("cfg") or {}).get("openrouter_api_keys", [])
    raw_pool = api_keys or engine_opts.get("openrouter_api_keys") or cfg_or_keys or (
        engine_opts.get("api_keys") if engine_opts.get("active_engine") == "openrouter" else []
    )
    # Isolamento estrito de provedores: jamais enviar chaves Groq (gsk_) para OpenRouter
    key_pool = [
        str(k).strip() for k in (raw_pool or [])
        if str(k or "").strip() and not str(k).strip().startswith("gsk_")
    ]
    if not key_pool:
        k = str(api_key or engine_opts.get("openrouter_api_key") or (
            engine_opts.get("api_key", "") if engine_opts.get("active_engine") == "openrouter" else ""
        )).strip()
        if k and not k.startswith("gsk_"):
            key_pool = [k]

    if not key_pool:
        raise ValueError("Nenhuma chave OpenRouter válida fornecida.")

    total_keys = len(key_pool)
    curr_idx = engine_opts.get("openrouter_current_key_idx", engine_opts.get("current_key_idx", 0))
    if curr_idx >= total_keys:
        curr_idx = 0

    exhausted = engine_opts.setdefault("openrouter_exhausted_keys", set())
    if len(exhausted) >= total_keys:
        engine_opts.setdefault("exhausted_engines", set()).add("openrouter")
        raise RuntimeError("Todas as chaves OpenRouter cadastradas atingiram o limite diário.")

    tried_count = 0

    while tried_count < total_keys:
        # Pula chaves que já sabemos que estão esgotadas
        if curr_idx in exhausted:
            tried_count += 1
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
                engine_opts["openrouter_current_key_idx"] = curr_idx
                engine_opts["openrouter_api_key"] = active_key
                if engine_opts.get("active_engine") == "openrouter":
                    engine_opts["current_key_idx"] = curr_idx
                    engine_opts["api_key"] = active_key
                raw_out = res.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
                return _strip_think_tags(raw_out)

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
                    print(f"\n[!] Chave OpenRouter #{curr_idx + 1} ({masked}): {motivo}.")
                    print(f"[+] ROTACIONANDO CHAVE AUTOMATICAMENTE -> Ativando Chave Reserva #{next_idx + 1} ({next_masked})...")
                    curr_idx = next_idx
                    engine_opts["openrouter_current_key_idx"] = curr_idx
                    engine_opts["openrouter_api_key"] = key_pool[curr_idx]
                    time.sleep(1.0)
                    continue
                else:
                    engine_opts.setdefault("exhausted_engines", set()).add("openrouter")
                    print(f"\n[!] TODAS as {total_keys} chaves OpenRouter cadastradas atingiram o limite diário.")
                    raise e
            else:
                # Se for indisponibilidade temporária de modelo (404, 500, 502, 503), tenta o modelo fallback específico do OpenRouter
                fallback_m = (
                    engine_opts.get("openrouter_fallback_model")
                    or (engine_opts.get("cfg") or {}).get("openrouter_fallback_model")
                    or (engine_opts.get("fallback_model") if engine_opts.get("active_engine") == "openrouter" else None)
                )
                if fallback_m and fallback_m != model_name and e.code in (404, 500, 502, 503):
                    print(f"\n[*] Modelo OpenRouter '{model_name}' instável (HTTP {e.code}). Tentando fallback: '{fallback_m}'...")
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

    # 1. Groq Cloud (Ultra-Rápido, 100% Nuvem, Zero Censura)
    groq_keys = list(cfg.get("groq_api_keys", []) or [])
    groq_key = str(cfg.get("groq_api_key", "") or "").strip()
    if groq_key and groq_key not in groq_keys:
        groq_keys.insert(0, groq_key)
    groq_model = cfg.get("groq_model", "qwen/qwen3.8-27b")
    groq_fallback = cfg.get("groq_fallback_model", "openai/gpt-oss-120b")

    if provider in ("groq", "fast") or (provider == "auto" and groq_keys):
        if groq_keys:
            active_groq_key = None
            last_g_msg = ""
            print(f"[*] Verificando conexão com Groq Cloud ({len(groq_keys)} chave(s) | Modelo: {groq_model})...")
            for gk in groq_keys:
                g_ok, g_msg = check_groq_available(gk, groq_model)
                last_g_msg = g_msg
                if g_ok:
                    active_groq_key = gk
                    break
            if active_groq_key:
                masked_g = active_groq_key[:8] + "..." + active_groq_key[-4:] if len(active_groq_key) > 12 else "***"
                print(f"[+] Motor Groq Cloud Ativo com Chave ({masked_g}) | Modelo: '{groq_model}' (Zero Censura | Nuvem)")
                engine_opts = {
                    "api_key": active_groq_key,
                    "groq_api_keys": groq_keys,
                    "openrouter_api_keys": keys,
                    "openrouter_fallback_model": fallback_model,
                    "fallback_model": groq_fallback,
                    "temperature": cfg.get("temperature", 0.0),
                    "cfg": cfg,
                    "active_model": groq_model,
                    "active_engine": "groq",
                    "exhausted_engines": set(),
                    "exhausted_groq_models": set(),
                    "groq_model_cooldowns": {}
                }
                return "groq", groq_model, engine_opts
            else:
                print(f"[!] Groq Cloud indisponível [{last_g_msg}]. Tentando próximo motor...")
        elif provider in ("groq", "fast"):
            print(f"[!] Erro: Provedor configurado como 'groq', mas 'groq_api_key' está vazia em config.json.")

    # 2. OpenRouter (100% Nuvem - Sem usar recursos do PC)
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
                    "openrouter_api_keys": keys,
                    "openrouter_api_key": active_key,
                    "current_key_idx": active_idx,
                    "openrouter_current_key_idx": active_idx,
                    "exhausted_keys": exhausted_keys,
                    "openrouter_exhausted_keys": exhausted_keys,
                    "active_engine": "openrouter",
                    "fallback_model": fallback_model,
                    "openrouter_fallback_model": fallback_model,
                    "temperature": cfg.get("temperature", 0.0),
                    "cfg": cfg
                }
                return "openrouter", model, engine_opts
            else:
                print(f"[!] Todas as chaves OpenRouter configuradas estão esgotadas no momento.")
        elif provider in ("openrouter", "cloud"):
            print(f"[!] Erro: Provedor configurado como 'openrouter', mas 'openrouter_api_keys'/'openrouter_api_key' está vazia em config.json.")

    # 3. Ollama (Remoto na Nuvem / Colab ou Local)
    host = cfg.get("ollama_host", "http://localhost:11434")
    model_pref = cfg.get("ollama_model", "dolphin-llama3:latest")
    print(f"[*] Verificando conexão com Ollama em '{host}'...")
    ollama_ok, selected_model = check_ollama_available(prefer_uncensored=is_adult, host=host, custom_model=model_pref)
    if ollama_ok:
        return "ollama", selected_model, {
            "host": host,
            "temperature": cfg.get("temperature", 0.0),
            "cfg": cfg,
            "active_engine": "ollama",
            "groq_api_keys": groq_keys,
            "openrouter_api_keys": keys,
            "openrouter_fallback_model": fallback_model
        }
    else:
        print(f"[!] Aviso: Ollama não disponível no host '{host}' (ambiente sem GPU ou servidor offline).")
        # Fallback de alta fidelidade para Groq Cloud se disponível
        if groq_keys:
            active_groq_key = None
            for gk in groq_keys:
                g_ok, _ = check_groq_available(gk, groq_model)
                if g_ok:
                    active_groq_key = gk
                    break
            if active_groq_key:
                masked_g = active_groq_key[:8] + "..." + active_groq_key[-4:] if len(active_groq_key) > 12 else "***"
                print(f"[+] Fallback Inteligente: Ativando Groq Cloud com Chave ({masked_g}) | Modelo: '{groq_model}'")
                return "groq", groq_model, {
                    "api_key": active_groq_key,
                    "groq_api_keys": groq_keys,
                    "openrouter_api_keys": keys,
                    "openrouter_fallback_model": fallback_model,
                    "fallback_model": groq_fallback,
                    "temperature": cfg.get("temperature", 0.0),
                    "cfg": cfg,
                    "active_model": groq_model,
                    "active_engine": "groq",
                    "exhausted_engines": {"ollama"},
                    "exhausted_groq_models": set(),
                    "groq_model_cooldowns": {}
                }

    return None, None, {"cfg": cfg}

def collapse_spaced_letters(text):
    """Reconecta letras ou sílabas individuais separadas por kerning da fonte (ex: 'S A A AN' -> 'SAAAN')."""
    def _repl(m):
        toks = m.group(0).split()
        if all(len(t) == 1 for t in toks):
            if set(t.lower() for t in toks).issubset({'a', 'i'}):
                return m.group(0)
            return ''.join(toks)
        return m.group(0)
    return re.sub(r'\b[A-Za-z](?:\s+[A-Za-z]){2,}\b', _repl, text)

def clean_ocr_scan_noise(text):
    """Limpa artefatos típicos de OCR, quebras de linhas e fontes de mangá em inglês/japonês antes de enviar para a IA."""
    if not text:
        return ""
    t = text

    # 1. Reconecta letras individuais espaçadas (kerning de balão)
    t = collapse_spaced_letters(t)

    # 2. Corrige contrações com apóstrofo quebrado ou separado por espaços pelo OCR
    t = re.sub(
        r"\b(WHERE|YOU|I|DON|DIDN|DOESN|ISN|AREN|WASN|WEREN|HAVEN|HASN|HADN|WOULDN|SHOULDN|COULDN|CAN|IT|THAT|WHAT|LET|COUNTRY)\s+([ST]|RE|VE|LL|M|D)\b",
        lambda m: m.group(1) + "'" + m.group(2),
        t,
        flags=re.IGNORECASE
    )
    t = re.sub(r"\b(don|can|won|didn|doesn|isn|aren)['\+]+(?:\s*t)?(?=[^a-zA-Z]|$)", lambda m: m.group(1) + "'t", t, flags=re.IGNORECASE)
    t = re.sub(r"\bhave\s*n[tf]\b", "haven't", t, flags=re.IGNORECASE)
    t = re.sub(r"\bHAVE\s+NT\b", "HAVEN'T", t)
    t = re.sub(r"\bI\s*['\+]+\s*s\b", "It's", t)
    t = re.sub(r"\bI\s*['\+]+\s*m\b", "I'm", t)
    t = re.sub(r"['\+]+s\b", "'s", t)
    t = re.sub(r"\b([A-Za-z]{3,})\s+S\b", r"\1'S", t)
    t = re.sub(r"\bIT\s+LL\b", "IT'LL", t, flags=re.IGNORECASE)

    # 3. Desfragmentação de palavras quebradas por hífens ou espaçamento interno
    t = re.sub(r"(?i)\bCONS\s*E\s*[-]?\s*QUE\s*N\s*CES\b", "CONSEQUENCES", t)
    t = re.sub(r"(?i)\bAC\s*KNOWL(?:[-]|EDGE)?\b", "ACKNOWLEDGE", t)
    t = re.sub(r"(?i)\bWit\s*c\s*H['’\s]*S\b", "Witch's", t)
    t = re.sub(r"(?i)\bWit\s*c\s*H\b", "Witch", t)
    t = re.sub(r"(?i)\bH\s*app\s*Y\b", "HAPPY", t)
    t = re.sub(r"(?i)\bIRU\s*LY\b", "TRULY", t)
    t = re.sub(r"(?i)\bLN\s*ABLE\b", "UNABLE", t)
    t = re.sub(r"(?i)\bln\s*able\b", "unable", t)
    t = re.sub(r"(?i)\b(?:it,\s*)?feels?\s+poo\s*6\b", "feels so good", t)
    t = re.sub(r"(?i)\b(?:poo|ipo)\s*6\b", "good", t)
    t = re.sub(r"(?i)\bwhat\s+am\s+T\s+even\s+s\s*aging\b", "what am I even saying", t)
    t = re.sub(r"(?i)\bARE\s+YO\s+LI\s+OKAY\b", "ARE YOU OKAY", t)
    t = re.sub(r"(?i)\bYO\s+LI\b", "YOU", t)
    t = re.sub(r"(?i)\bI-IS\s+S\s*IHL\s+REAL\s+LIFE\b", "IS THIS REAL LIFE", t)
    t = re.sub(r"(?i)\bS\s*IHL\b", "THIS", t)
    t = re.sub(r"(?i)\bSPITTING\s+WAGE\b", "SPITTING IMAGE", t)
    t = re.sub(r"(?i)\bIS\s+A\s+WIN\s+A\s+DREAM\b", "I SAW IN A DREAM", t)
    t = re.sub(r"(?i)\bOP\s+THEIR\s+HEART\b", "OF THEIR HEART", t)
    t = re.sub(r"(?i)\bDREAM\s+OP\b", "DREAM OF", t)
    t = re.sub(r"(?i)\bM\s*LIST\s+MEET\b", "MUST MEET", t)
    t = re.sub(r"(?i)\bMASTER\s+LESS\b", "MASTERLESS", t)
    t = re.sub(r"(?i)\bBEAST\s+KIN\b", "BEASTKIN", t)
    t = re.sub(r"(?i)\bFURY\s+A(?:\s*-\s*SAMA|\s+SAMA)\b", "Furiya-sama", t)
    t = re.sub(r"(?i)\bFURY\s+A\b", "Furiya", t)
    t = re.sub(r"(?i)\bmad\s+or\s+omi\b", "Madoromi", t)
    t = re.sub(r"(?i)\bmi\s+y\s+obi\b", "Miyobi", t)
    t = re.sub(r"(?i)\bONEE\s+SAM\s+AS\b", "Onee-sama's", t)
    t = re.sub(r"(?i)\bBEDTIME\s+ARRANGEMENT\s+S\b", "BEDTIME ARRANGEMENTS", t)
    t = re.sub(r"(?i)\bARRANGEMENT\s+S\b", "ARRANGEMENTS", t)
    t = re.sub(r"(?i)\bIAM\b", "I AM", t)
    t = re.sub(r"(?i)\bFORME\b", "FOR ME", t)
    t = re.sub(r"(?i)\bNMO\s*AW\b", "MOVE MY", t)
    t = re.sub(r"(?i)\bROCHE\s*[-–—]?\s*SAN\b", "Roche-san", t)
    t = re.sub(r"(?i)\bROCHE\s+SAN\b", "Roche-san", t)
    t = re.sub(r"(?i)\bFU\s*[-–—]?\s*CHAN\b", "Fu-chan", t)
    t = re.sub(r"(?i)\bFU\s+CHAN\b", "Fu-chan", t)
    t = re.sub(r"(?i)\bONEE\s*[-–—]?\s*SAMA\b", "Onee-sama", t)
    t = re.sub(r"(?i)\bONEE\s+SAMA\b", "Onee-sama", t)

    # 4. Outros ruídos e onomatopeias
    t = re.sub(r"(?i)\b(?:p\s*lap|sp\s*lap)\b", "plap", t)
    t = re.sub(r"(?i)\b(?:sch\s*luck|sh\s*luck)\b", "shluck", t)
    t = re.sub(r"\bhit\s*ing\b", "hitting", t, flags=re.IGNORECASE)
    t = re.sub(r"\bWwa\s*it\b", "Wait", t, flags=re.IGNORECASE)
    t = re.sub(r"\bbea\s*lit\s*le\b", "be a little", t, flags=re.IGNORECASE)
    t = re.sub(r"\bdesperate\s*l(?:\.|\s)*\b", "desperately", t, flags=re.IGNORECASE)
    t = re.sub(r"\bop\s*want\b", "really want", t, flags=re.IGNORECASE)
    t = re.sub(r"\bWhere\s*no[^\w\s]*\s*(?:op\s*)?want\b", "Where do you want", t, flags=re.IGNORECASE)

    # Balões de clímax e grito
    t = re.sub(r"\bI\s*CAN(?:\s*['\+]?\s*T)?\s*H\s*OLD\s*IT\s*ANYMORE!*\b", "I CAN'T HOLD IT ANYMORE!", t, flags=re.IGNORECASE)
    t = re.sub(r"\bCAN\s*TH\s*OLD\b", "CAN'T HOLD", t, flags=re.IGNORECASE)
    t = re.sub(r"\bI['\s\+]*[mM]\s+[cC][uU][\s\-_]*[mM]+[\s\-_]*[mM]*[iI][nN][gG]!*", "I'm CUMMING!", t, flags=re.IGNORECASE)
    t = re.sub(r"\b[cC][uU][\s\-_]*[mM]+[\s\-_]*[mM]*[iI][nN][gG]!*", "CUMMING!", t, flags=re.IGNORECASE)
    t = re.sub(r"\b[cC][uU]\s*[mM]\s*[mM][iI][nN][eE]!*", "CUMMING!", t, flags=re.IGNORECASE)

    # Desfragmentação de OCR latino / espanhol
    t = re.sub(r"(?i)\bjoy\s+eri\s*a\b", "joyería", t)
    t = re.sub(r"(?i)\bjoy\s+as\b", "joyas", t)
    t = re.sub(r"(?i)\bjoy\s+a\b", "joya", t)
    t = re.sub(r"(?i)\b(?:ml\s*chas|much\s+as)\b", "muchas", t)
    t = re.sub(r"(?i)\bgraci\s+as\b", "gracias", t)
    t = re.sub(r"(?i)\bti\s+en\s+da\b", "tienda", t)
    t = re.sub(r"(?i)\bti\s+en\s+das\b", "tiendas", t)
    t = re.sub(r"(?i)\ben\s+cim\s+a\b", "encima", t)
    t = re.sub(r"(?i)\btam\s*bi\s*en\b", "también", t)
    t = re.sub(r"(?i)\ba\s*ten\s*der\b", "atender", t)
    t = re.sub(r"(?i)\bde\s+dic\s+aci\s+on\b", "dedicación", t)
    t = re.sub(r"(?i)\ba\s*comp\s*an\s*an\s*te\b", "acompañante", t)
    t = re.sub(r"(?i)\bsir\s+va\s*se\b", "sírvase", t)
    t = re.sub(r"(?i)\bde\s+jar\b", "dejar", t)
    t = re.sub(r"(?i)\blle\s+vas\b", "llevas", t)
    t = re.sub(r"(?i)\blle\s+vo\b", "llevo", t)
    t = re.sub(r"(?i)\blle\s+va\b", "lleva", t)
    t = re.sub(r"(?i)\bpu\s+es\s+tas\b", "puestas", t)
    t = re.sub(r"(?i)\bpu\s+es\s+ta\b", "puesta", t)
    t = re.sub(r"(?i)\bcue\s+r\s*po\b", "cuerpo", t)
    t = re.sub(r"(?i)\bcal\s+i\s+en\s+tu\s+ra\b", "calentura", t)
    t = re.sub(r"(?i)\bvi\s+si\s+ta\b", "visita", t)
    t = re.sub(r"(?i)\bcl\s+i\s+en\s+te\s*la\b", "clientela", t)
    t = re.sub(r"(?i)\bcl\s+i\s+en\s+tes\b", "clientes", t)
    t = re.sub(r"(?i)\bcl\s+i\s+en\s+te\b", "cliente", t)
    t = re.sub(r"(?i)\bsu\s+cur\s+sal\b", "sucursal", t)
    t = re.sub(r"(?i)\bper\s+for\s+aci\s+on\s*es\b", "perforaciones", t)
    t = re.sub(r"(?i)\bac\s+ce\s+so\s+ri\s+os\b", "accesorios", t)
    t = re.sub(r"(?i)\bmo\s+del\s+o\b", "modelo", t)
    t = re.sub(r"(?i)\bam\s+bul\s+an\s+te\b", "ambulante", t)
    t = re.sub(r"(?i)\bto\s+das\b", "todas", t)
    t = re.sub(r"(?i)\bto\s+do\b", "todo", t)
    t = re.sub(r"(?i)\bmer\s+can\s+ci\s*a\b", "mercancía", t)

    # Nomes e ruídos japoneses
    t = re.sub(r"(?i)\bhats\s+uk\s+o\b", "Hatsuko", t)
    t = re.sub(r"(?i)\boya\s+kod\s+on\b", "Oyakodon", t)
    t = re.sub(r"(?i)\bto\s+lg\s+h\b", "tough", t)
    t = re.sub(r"(?i)\bw[\s,;]+(?:i['\s]*m?\s*)?cumming!*", "I'm CUMMING!", t)
    t = re.sub(r"(?i)\bread\s+the\s+j\s+do\s+ow\b", "read the room", t)
    t = re.sub(r"(?i)\bharu\s+na\b", "Haruna", t)
    t = re.sub(r"(?i)\bshun\s+kun\b", "Shun-kun", t)
    t = re.sub(r"(?i)\b(?:yuk\s+un|yuk-un|\.yuk\s*un)\b", "Yu-kun", t)
    t = re.sub(r"(?i)\b(?:natsuki\s+san|natsuki-san)\b", "Natsuki-san", t)
    t = re.sub(r"(?i)\bs\s+ihi\s+woman\b", "This woman", t)
    t = re.sub(r"(?i)\bfr\s+i\s+end\b", "friend", t)
    t = re.sub(r"(?i)\bch\s+il\s+dish\b", "childish", t)
    t = re.sub(r"(?i)\bs\s+que\s+ez\b", "squeeze", t)
    t = re.sub(r"(?i)\bsca\s+a\s+ary\b", "scary", t)
    t = re.sub(r"(?i)\bcome\s+hang\s+ol\s*u\s*it\b", "come hang out", t)
    t = re.sub(r"(?i)\bhang\s+ol\s*u\s*it\b", "hang out", t)
    t = re.sub(r"(?i)\bpee\s*pee\b", "pee-pee", t)
    return t

def clean_ai_translation(text, original_text="", is_adult=True):
    """Higieniza rigorosamente a saída da IA: elimina notas, 'Obs:', prefixos e normaliza anatomia."""
    if not text:
        return original_text.strip()
        
    cleaned = sanitize_lettering_text(_strip_think_tags(text)).strip()
    
    # 0. Detectar e ignorar mensagens de recusa de IA ou vazamentos de prompt
    # 0.1 Eliminar estritamente vazamentos de instruções do sistema (Prompt Leaks)
    prompt_leak_patterns = [
        r'(?i)\b(?:n[ãa]o\s+revele|nao\s+revele)[^.\n]*[.\n]?',
        r'(?i)\bfoque\s+apenas[^.\n]*[.\n]?',
        r'(?i)\b(?:do\s+not\s+reveal|never\s+discuss)[^.\n]*[.\n]?',
        r'(?i)\bvoc[êe]\s+[eé]\s+o\s+agente\s+[12].*?[.\n]?',
        r'(?i)\bdossi[êe]\s+estrutural.*?[.\n]?',
        r'(?i)\bpersona_intro.*?[.\n]?',
        r'(?i)\bdiretrizes\s+de\s+localiza[çc][ãa]o.*?[.\n]?'
    ]
    for plp in prompt_leak_patterns:
        cleaned = re.sub(plp, '', cleaned).strip()

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
        has_female_organ = bool(re.search(r'\b(pussy|cunt|vagina|slit|clit|clitoris)\b', orig_lower))
        has_male_organ = bool(re.search(r'\b(peepee|pecker|penis|cock|dick|shaft|wiener)\b', orig_lower))

        # Pussy / Cunt -> Buceta (apenas se não houver órgão masculino na mesma frase para evitar conflito)
        if has_female_organ and not has_male_organ:
            cleaned = _preserve_case(r'\bpica\b', 'buceta', cleaned)
            cleaned = _preserve_case(r'\bpau\b', 'buceta', cleaned)
            cleaned = _preserve_case(r'\bpiroca\b', 'buceta', cleaned)
            cleaned = _preserve_case(r'\bcaralho\b', 'buceta', cleaned)

        # Cock / Dick / Shaft -> Pau / Pinto (apenas se não houver órgão feminino na mesma frase)
        if has_male_organ and not has_female_organ:
            cleaned = _preserve_case(r'\bsua\s+bucetinha\b', 'seu pintinho', cleaned)
            cleaned = _preserve_case(r'\bsua\s+buceta\b', 'seu pau', cleaned)
            cleaned = _preserve_case(r'\bbucetinha\b', 'pintinho', cleaned)
            cleaned = _preserve_case(r'\bbuceta\b', 'pau', cleaned)
            cleaned = _preserve_case(r'\bseu\s+peito\b', 'seu pau', cleaned)
            cleaned = _preserve_case(r'\bseus\s+peitos\b', 'seu pau', cleaned)
            cleaned = _preserve_case(r'\bpeito\b', 'pau', cleaned)
            cleaned = _preserve_case(r'\bp[ée]\s+de\s+peixe\b', 'pintinho', cleaned)

        # Correção direta de concordância de gênero de órgãos (ex: 'na pau da mamãe' -> 'na buceta da mamãe')
        cleaned = re.sub(r'\b(?:na|a|pela)\s+pau\s+da\b', 'na buceta da', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(?:no|o|pelo)\s+buceta\s+do\b', 'no pau do', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bna\s+pau\b', 'no pau', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\buma\s+pau\b', 'um pau', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bminha\s+pau\b', 'meu pau', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bsua\s+pau\b', 'seu pau', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bno\s+buceta\b', 'na buceta', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bum\s+buceta\b', 'uma buceta', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bmeu\s+buceta\b', 'minha buceta', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bseu\s+buceta\b', 'sua buceta', cleaned, flags=re.IGNORECASE)

        # Underwear / Panties -> Calcinha / Lingerie (NUNCA cuecas para mulheres)
        if re.search(r'\b(underwear|lingerie|panties|undies)\b', orig_lower):
            cleaned = _preserve_case(r'\bcuecas?\s+estriadas?\b', 'calcinha listrada', cleaned)
            cleaned = _preserve_case(r'\bcueca\s+listrada\b', 'calcinha listrada', cleaned)
            cleaned = _preserve_case(r'\bcuecas?\b', 'calcinha', cleaned)
            cleaned = re.sub(r'\bumas\s+calcinhas?\b', 'uma calcinha', cleaned, flags=re.IGNORECASE)

        # Fiancée -> Noiva (NUNCA noivo)
        if re.search(r'\bfianc[eé]+e?\b', orig_lower):
            cleaned = _preserve_case(r'\bnoivo\b', 'noiva', cleaned)

        # Came / Cum / Climax -> Gozou / Gozar (NUNCA veio ou chegou em contexto erótico)
        if re.search(r'\b(came|cum|cumming|climax|orgasm)\b', orig_lower):
            cleaned = _preserve_case(r'\bj[áa]\s+veio\b', 'já gozou', cleaned)
            cleaned = _preserve_case(r'\bela\s+veio\b', 'ela gozou', cleaned)
            cleaned = _preserve_case(r'\bele\s+veio\b', 'ele gozou', cleaned)
            cleaned = _preserve_case(r'\beu\s+vim\b', 'eu gozei', cleaned)
            cleaned = _preserve_case(r'\bveio\s+antes\b', 'gozou antes', cleaned)
            cleaned = _preserve_case(r'\bveio\s+primeiro\b', 'gozou primeiro', cleaned)
            cleaned = _preserve_case(r'\bveio\s+r[áa]pido\b', 'gozou rápido', cleaned)
            cleaned = _preserve_case(r'\bveio\s+muito\b', 'gozou muito', cleaned)
            cleaned = _preserve_case(r'\bveio\s+de\s+novo\b', 'gozou de novo', cleaned)
            cleaned = _preserve_case(r'\bveio\s+duas\s+vezes\b', 'gozou duas vezes', cleaned)
            cleaned = _preserve_case(r'\bveio\s+para\s+dentro\b', 'gozou dentro', cleaned)
            cleaned = _preserve_case(r'\bveio\s+dentro\b', 'gozou dentro', cleaned)
            cleaned = _preserve_case(r'\bentrei\s+(?:na|dentro\s+da)\b', 'gozei dentro da', cleaned)
            cleaned = _preserve_case(r'\bentrou\s+(?:na|dentro\s+da)\b', 'gozou dentro da', cleaned)
            cleaned = _preserve_case(r'\bentrou\s+na\s+boca\b', 'gozou dentro', cleaned)
            cleaned = _preserve_case(r'\bvir-me\b', 'gozar', cleaned)
            cleaned = _preserve_case(r'\bvir-se\b', 'gozar', cleaned)

        # Limpeza de alucinações de OCR em momentos de clímax e gritos
        cleaned = _preserve_case(r'\b(?:estou|t[oô])\s+com\s+bola\b', 'estou gozando', cleaned)
        cleaned = _preserve_case(r'\b(?:eu\s+sou|estou)\s+cumin\s*g\b', 'estou gozando', cleaned)
        cleaned = _preserve_case(r'\b(?:eu\s+sou|estou\s+com|estou|eu\s+sou\s+cu)\s+(?:m\s+ming|cu\s*m+ing|mm\s*ing)\b', 'estou gozando', cleaned)
        cleaned = _preserve_case(r'\bcom\s+m\s+mine\b', 'estou gozando', cleaned)
        cleaned = _preserve_case(r'\b(?:eu\s+)?posso\s+velhar(?:\s+mais)?!*\b', 'não aguento mais segurar!', cleaned)
        cleaned = _preserve_case(r'\bposso\s+velhar\b', 'posso aguentar', cleaned)

        # Gemidos curtos confundidos com 'irmão mais velho' ou falsos amigos
        if re.search(r'\birm[ãa]o\s+mais\s+velho\b', cleaned, flags=re.IGNORECASE) and not re.search(r'\b(?:brother|onii|ani)\b', orig_lower):
            cleaned = re.sub(r'\birm[ãa]o\s+mais\s+velho\b', lambda m: 'Anh' if m.group(0)[0].isupper() else 'anh', cleaned, flags=re.IGNORECASE)

        # O filho falando com a mãe sobre o pai (Dad -> O papai / Meu pai, NUNCA 'Seu pai')
        if re.search(r'\bdad\b', orig_lower) and not re.search(r'\byour\s+dad\b', orig_lower):
            cleaned = _preserve_case(r'\bseu\s+pai\s+nem\s+parece\s+existir\b', 'o papai nem parece existir', cleaned)
            cleaned = _preserve_case(r'\bseu\s+pai\s+nunca\s+chega\b', 'o papai nunca chega', cleaned)
            cleaned = _preserve_case(r'\bseu\s+pai\b', 'o papai', cleaned)

        # 'wet' em cena íntima com mulher é 'molhada'
        if 'wet' in orig_lower:
            cleaned = re.sub(r'\b(est[áa]\s+(?:ficando\s+)?(?:um\s+pouco\s+|muito\s+)?)molhado\b', r'\1molhada', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\bficando\s+(?:muito\s+)?molhado\b', 'ficando muito molhada', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\bt[ãa]o\s+molhado\b', 'tão molhada', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\bmuito\s+molhado\b', 'muito molhada', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\bum\s+pouco\s+molhado\b', 'um pouco molhada', cleaned, flags=re.IGNORECASE)

        # Protagonista masculino falando de si quando criança ('when I was little' -> 'quando eu era pequeno')
        cleaned = _preserve_case(r'\bquando\s+eu\s+era\s+pequena\b', 'quando eu era pequeno', cleaned)

        # Mulher / mãe falando de ser desejada ou ser parceira
        cleaned = re.sub(r'\bser\s+desejado\b', lambda m: 'Ser desejada' if m.group(0)[0].isupper() else 'ser desejada', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(continuarei\s+sendo|serei|sou)\s+seu\s+parceiro\b', r'\1 sua parceira', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bser\s+seu\s+parceiro\b', 'ser sua parceira', cleaned, flags=re.IGNORECASE)

        # Mulher mostrando-se nua
        cleaned = _preserve_case(r'\bse\s+mostraria\s+nu\b', 'se mostraria nua', cleaned)
        cleaned = _preserve_case(r'\bmostrar(?:-se)?\s+nu\b', 'mostrar-se nua', cleaned)
        cleaned = _preserve_case(r'\bficar\s+nu\b', 'ficar nua', cleaned)

        # Sow (insulto/fetiche em mangá adulto) -> Porca / Vadia (NUNCA semear)
        if re.search(r'\bsow\b', orig_lower):
            cleaned = _preserve_case(r'\bsemear\b', 'porca', cleaned)
            cleaned = _preserve_case(r'\bsementeira\b', 'porca', cleaned)
            cleaned = _preserve_case(r'\bsemeadura\b', 'porca', cleaned)
            if cleaned.strip().lower() in ('semear', 'sementeira', 'semeadura'):
                cleaned = 'Porca' if cleaned[0].isupper() else 'porca'

        # Limpeza de gemidos repetidos isolados ('u u u') traduzidos mecanicamente como 'você, você'
        # Nunca substitui 'você' em frases reais em chinês/japonês/coreano/espanhol ou inglês com palavras reais!
        has_second_person_or_words = bool(
            re.search(r'(?:you|your|yours|yo\s*u|t[uú]|usted|contigo|你|您|君|お前|あなた|貴方|너|당신|[a-z]{3,})', orig_lower)
        )
        has_isolated_u_moan = bool(re.search(r'(?:^|[\s,;.!?\-~])u(?:[\s,;.!?\-~]+u)+(?=$|[\s,;.!?\-~])', orig_lower))
        if re.search(r'\bvoc[êe]\b', cleaned, flags=re.IGNORECASE) and has_isolated_u_moan and not has_second_person_or_words:
            cleaned = re.sub(r'\bvoc[êe]\b', 'uh', cleaned, flags=re.IGNORECASE)

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

        # Gírias chinesas de scanlation: 飛機杯 (masturbador) e 乱七八糟 (bagunça)
        if re.search(r'(?:飛機杯|飞机杯|onahole|fleshlight)', orig_lower):
            cleaned = _preserve_case(r'copo\s+de\s+avi[aã]o', 'masturbador', cleaned)
            cleaned = _preserve_case(r'avi[aã]o\s+de\s+papel', 'masturbador', cleaned)
            cleaned = _preserve_case(r'\bcopo\b', 'masturbador', cleaned)

        if re.search(r'(?:乱七八糟|亂七八糟)', orig_lower):
            cleaned = _preserve_case(r'bicho\s+de\s+sete\s+cabe[çc]as', 'uma bagunça', cleaned)
            cleaned = _preserve_case(r'sete\s+tigelas', 'uma bagunça', cleaned)

        # Previne alucinação de nomes externos (como Rudy/Rudeus) que não existem na obra original
        if re.search(r'\b(rudy|rudeus)\b', cleaned, re.IGNORECASE):
            if not re.search(r'(?:ルディ|ルーデウス|鲁迪|鲁德斯|rudeus|rudy)', original_text, re.IGNORECASE):
                cleaned = re.sub(r'(?i)\b(?:pra\s+|para\s+|o\s+)?(?:rudy|rudeus)\b', '', cleaned).strip()
                cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    cleaned = _preserve_case(r'\bperfecto\b', 'perfeito', cleaned)
    cleaned = _preserve_case(r'\btacto\b', 'tato', cleaned)
    cleaned = _preserve_case(r'\bmbicar\b', 'lamber', cleaned)
    cleaned = _preserve_case(r'\breito\b', 'peito', cleaned)

    # PROTEÇÃO ANTI-ALUCINAÇÃO EM TERMOS COMERCIAIS / JOALHERIA / ROUPAS:
    # Se o texto original tratava de joias, joalheria, loja ou roupas, impede que a IA confunda com órgãos genitais
    orig_has_jewelry = bool(re.search(r'(?i)\b(joyas?|joyer[íi]a|tiendas?|ropas?|collares|pulseras|anillos|gemas|jewelry|jewel|store|shop)\b', orig_lower))
    if orig_has_jewelry:
        cleaned = re.sub(r'(?i)\b(?:na|a)\s+buceta\s+dela\b', 'na joalheria', cleaned)
        cleaned = re.sub(r'(?i)\b(?:na|no)\s+buceta\b', 'na joalheria', cleaned)
        cleaned = re.sub(r'(?i)\bo\s+cu\s+da\s+mulher\b', 'o corpo da mulher', cleaned)
        if not re.search(r'(?i)\b(coño|pussy|vagina|cunt|rajita)\b', orig_lower):
            cleaned = re.sub(r'(?i)\bbuceta\b', 'joalheria', cleaned)

    # TRADUÇÃO DE ESPANHOL RESIDUAL -> PORTUGUÊS DO BRASIL:
    cleaned = _preserve_case(r'\bescribiendo\b', 'escrevendo', cleaned)
    cleaned = _preserve_case(r'\bescribendo\b', 'escrevendo', cleaned)
    if re.search(r'[\uac00-\ud7af]', original_text or ""):
        if re.search(r'자지', original_text or "") and re.search(r'쓰[고는거기]', original_text or ""):
            cleaned = _preserve_case(r'\bescrevendo\b', 'usando', cleaned)
            cleaned = _preserve_case(r'\bescrever\b', 'usar', cleaned)
        if '바둑이' in (original_text or "") and cleaned.strip().lower() in ('go', 'go!', 'ir!', 'vai!'):
            cleaned = 'Baduki'
    cleaned = _preserve_case(r'\bml\s*chas\s+gracias\b', 'muito obrigado', cleaned)
    cleaned = _preserve_case(r'\bmuchas\s+gracias\b', 'muito obrigado', cleaned)
    cleaned = _preserve_case(r'\bpelo\s+visit\s*a\b', 'pela visita', cleaned)
    cleaned = _preserve_case(r'\bpor\s+la\s+visita\b', 'pela visita', cleaned)
    cleaned = _preserve_case(r'\btodas\s+las\b', 'todas as', cleaned)
    cleaned = _preserve_case(r'\btodos\s+los\b', 'todos os', cleaned)
    cleaned = _preserve_case(r'\bhoy\b', 'hoje', cleaned)
    cleaned = _preserve_case(r'\bjoyas\b', 'joias', cleaned)
    cleaned = _preserve_case(r'\bjoyer[íi]a\b', 'joalheria', cleaned)
    cleaned = _preserve_case(r'\bjoyeria\b', 'joalheria', cleaned)
    cleaned = _preserve_case(r'\btienda\b', 'loja', cleaned)
    cleaned = _preserve_case(r'\btiendas\b', 'lojas', cleaned)
    cleaned = _preserve_case(r'\bllevas\b', 'usa', cleaned)
    cleaned = _preserve_case(r'\blleva\b', 'usa', cleaned)
    cleaned = _preserve_case(r'\bllevo\b', 'uso', cleaned)
    cleaned = _preserve_case(r'\btodo\s+el\s+dinero\b', 'todo o dinheiro', cleaned)
    cleaned = _preserve_case(r'\bde\s+verdad\b', 'de verdade', cleaned)
    cleaned = _preserve_case(r'\bsin\s+dudar(?:\s+ni\s+un\s+instante)?\b', 'sem hesitar nem um instante', cleaned)
    cleaned = _preserve_case(r'\ben\s+cima\b', 'em cima', cleaned)
    cleaned = _preserve_case(r'\bs[ií]rvase\b', 'fique à vontade', cleaned)
    cleaned = _preserve_case(r'\bacompañante\b', 'acompanhante', cleaned)
    cleaned = _preserve_case(r'\bdisculpe\b', 'desculpe', cleaned)
    cleaned = _preserve_case(r'\bvengan\b', 'venham', cleaned)
    cleaned = _preserve_case(r'\bbienvenidos\b', 'bem-vindos', cleaned)
    cleaned = _preserve_case(r'\bla\s+clientela\b', 'a clientela', cleaned)
    cleaned = _preserve_case(r'\by\s+ya\s+le\s+agarro\s+el\s+gusto\s+por\s+completo\b', 'e já pegou o gosto por completo', cleaned)
    cleaned = _preserve_case(r'\bcalientura\b', 'fogo', cleaned)
    cleaned = _preserve_case(r'\btambien\b', 'também', cleaned)
    cleaned = _preserve_case(r'\bramera\b', 'vadia', cleaned)
    cleaned = _preserve_case(r'\btasa\s*dor\s*a\b', 'avaliadora', cleaned)

    # Proteção de nomes japoneses e termos culturais
    if "hatsuko" in orig_lower or "hats" in orig_lower:
        cleaned = _preserve_case(r'\bchap[ée]us\s+(?:uk\s+o|uk)\b', 'Hatsuko', cleaned)
        cleaned = _preserve_case(r'\bchap[ée]us\b', 'Hatsuko', cleaned)
    cleaned = _preserve_case(r'\boya\s+kod\b', 'oyakodon', cleaned)
    cleaned = _preserve_case(r'\bbonita\s+para\s+lg\s*h\b', 'bem difícil', cleaned)
    cleaned = _preserve_case(r'\bpara\s+lg\s*h\b', 'bem difícil', cleaned)

    # BARREIRA DE FERRO (QUALITY GATE): Nomes de personagens, fontes comic e gírias adultas em tempo real
    if re.search(r'\b(?:yuk\s*un|yu-kun|yu\s*kun)\b', orig_lower):
        cleaned = re.sub(r'(?i)\b(?:vamos\s+na\s+onu|vamos|onu|yuk\s+onu)\b', 'Yu-kun', cleaned)
    if 's ihi woman' in orig_lower or 'natsuki san' in orig_lower:
        cleaned = re.sub(r'(?i)\bs\s*ihi\s*mulher', 'Essa mulher', cleaned)
    if re.search(r'\bfr\s+i\s+end\b', orig_lower) and 'padre' in cleaned.lower():
        cleaned = 'Amiga...'
    if 'ch il dish' in orig_lower:
        cleaned = re.sub(r'(?i)ch\s+il\s+prato\.*', 'infantil...', cleaned)
        cleaned = re.sub(r'(?i)tipo\s+e\s+um\s+pouco', 'gentil e um pouco', cleaned)
    if re.search(r'\bs\s+que\s+ez\b', orig_lower):
        cleaned = re.sub(r'(?i)\beu\s+sei\s+isso\s+ez\b', 'Aperta!', cleaned)
        cleaned = re.sub(r'(?i)\bez\b', 'Aperta!', cleaned)
    if re.search(r'\bwwa\s+it\b', orig_lower):
        cleaned = re.sub(r'(?i)\bwwa\s+isso\b', 'Espere!', cleaned)
    if re.search(r'\bsca\s+a\s+ary\b', orig_lower):
        cleaned = re.sub(r'(?i)\bsca\s+para\s+ary\b', 'Que medo~', cleaned)
    if re.search(r'\bpee\s*pee\b', orig_lower) or 'pee pee' in cleaned.lower():
        cleaned = re.sub(r'(?i)\bpee\s*pee\b', 'pauzinho', cleaned)
    if re.search(r'\bhang\s+(?:ol\s*u\s*it|out)\b', orig_lower):
        cleaned = re.sub(r'(?i)venha\s+pendurar\s+a\s+qualquer\s+hora!?', 'venha me visitar quando quiser!', cleaned)
        cleaned = re.sub(r'(?i)\bpendurar\b', 'visitar', cleaned)
    if re.search(r'\bhard\b', orig_lower) and is_adult and re.search(r'\bdif[íi]cil\b', cleaned, re.IGNORECASE):
        cleaned = re.sub(r'(?i)\bdif[íi]cil\b', 'duro', cleaned)
    if re.search(r'\bcum\b', orig_lower) and is_adult and re.search(r'\bcum\b', cleaned, re.IGNORECASE) and not any(w in cleaned.lower() for w in ['goz', 'porra', 'leite']):
        cleaned = re.sub(r'(?i)\bcum\b', 'gozar', cleaned)

    # Dinâmica familiar enteado/madrasta (mulher) e falsos amigos
    cleaned = _preserve_case(r'\bvoc[êe]\s+[eé]\s+um\s+estranho\b', 'você é uma estranha', cleaned)
    cleaned = _preserve_case(r'\bde\s+forma\s+material\b', 'de forma maternal', cleaned)
    cleaned = _preserve_case(r'\bage\s+de\s+forma\s+material\b', 'fica bancando a mãe', cleaned)
    cleaned = _preserve_case(r'\btoda\s+material\b', 'toda maternal', cleaned)
    cleaned = _preserve_case(r'\bum\s+incomod[áa]vel\b', 'um estorvo', cleaned)
    cleaned = _preserve_case(r'\bincomod[áa]vel\b', 'incômodo', cleaned)

    # Ruídos gráficos de clímax
    cleaned = re.sub(r'(?i)\b[eé],\s+estou\s+gozando\b', 'Estou gozando', cleaned)

    # Proteção contra retorno vazio da IA em momentos cruciais (+18)
    if not cleaned.strip() and original_text.strip():
        if re.search(r'hard\s+cock\s+hits\s+deep', orig_lower):
            cleaned = "O pau duro bate tão fundo que não consigo evitar..."
        elif is_adult and re.search(r'\b(cum|cock|dick|pussy)\b', orig_lower):
            cleaned = "Ah... Estou gozando!"
    
    # Limpeza de artefatos de OCR e corações transcritos ('heart', '√', '✔')
    cleaned = re.sub(r'(?i)\bheart(?:\s+111|\s+11|\s+1)?\b', '♡', cleaned)
    cleaned = re.sub(r'[√✔]+', '♡', cleaned)
    
    # 9. Proteção para gemidos/sons latinos curtos (evita que 'NGH!' vire um parágrafo; nunca trunca frases CJK onde 3-6 ideogramas são sentenças completas!)
    orig_stripped = original_text.strip()
    is_orig_cjk = bool(re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', orig_stripped))
    if not is_orig_cjk and len(orig_stripped) <= 6 and len(cleaned.split()) > 3:
        cleaned = cleaned.split()[0].strip()

    # Fragmentos residuais de OCR truncado ou ruídos de redes sociais
    if cleaned.upper() in ('OF', 'D..', 'HW)', 'D.', '(1)', '+66>'):
        return ""
    if re.match(r'^(?:ill\d+.*|\?\d+|\+\d+>|\(\d+\))$', cleaned):
        return ""

    cleaned = sanitize_lettering_text(cleaned)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned).strip()
    return cleaned if cleaned else ""

def build_translation_system_prompt(is_adult=True, is_batch=False, glossary=None, is_dolphin=True, is_qwen=False, src_lang="auto"):
    """Gera prompt de sistema otimizado para scanlation de alta precisão (estilo MangaPlus / Crunchyroll),
    com adaptação concisa para balões de mangá e suporte especializado a Qwen, GPT-OSS e Dolphin."""
    is_asian = str(src_lang or "").lower() in ("ko-kr", "ko", "ja-jp", "ja", "zh-cn", "zh-tw", "zh")
    if is_asian:
        glossary_rules = ""
        if glossary:
            chars = glossary.get("characters", {})
            terms = glossary.get("terms", {})
            if chars or terms:
                glossary_rules = "\nGLOSSÁRIO DA OBRA:\n"
                for k, v in chars.items():
                    glossary_rules += f"- '{k}' -> '{v}'\n"
                for k, v in terms.items():
                    glossary_rules += f"- '{k}' -> '{v}'\n"

        dos, donts = load_learning_rules(src_lang=src_lang)
        learned_rules_text = ""
        if dos or donts:
            learned_rules_text = "\nREGRAS APRENDIDAS:\n"
            for d in dos[:18]:
                learned_rules_text += f"- {d.lstrip('-*• ')}\n"
            for d in donts[:12]:
                learned_rules_text += f"- PROIBIDO: {d.lstrip('-*• ')}\n"

        adult_short = ""
        if is_adult:
            adult_short = (
                "\nTOM ADULTO (+18, SEM CENSURA):\n"
                "- Use vocabulário explícito e coloquial brasileiro ('buceta', 'pau', 'pinto', 'gozar', 'gozando', 'calcinha', 'tesão').\n"
                "- Coreano (+18): 자지='pau/pinto', 보지='buceta', 쓰고='usando/metendo' (NUNCA 'escrever/escrevendo'), 딸치다/딸치지='bater uma / usar para se masturbar' (NUNCA apenas 'bater em'), 갈 것 같다/싸다='vou gozar/gozar', 야옹/냥='miau', 바둑이='Baduki' (nome próprio, NUNCA 'Go'), -님='-sama/senhor(a)' (NUNCA '-sen'), 수인='bestiais/homens-fera'.\n"
            )

        out_rule = (
            'Responda APENAS JSON válido com as mesmas chaves numéricas: {"1": "..."}. NUNCA use espanhol ou texto asiático residual.'
            if is_batch else
            'Responda APENAS a tradução final em PT-BR coloquial e concisa (para caber no balão), sem notas nem espanhol.'
        )
        return (
            f"Tradutor profissional de scanlation (Manhwa/Mangá -> Português do Brasil coloquial).\n"
            f"Adapte falas curtas, naturais e expressivas mantendo pontuação (!, ?, ..., ~)."
            f"{adult_short}{glossary_rules}{learned_rules_text}\n{out_rule}"
        )

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
            glossary_rules += "- GÊNERO: Se uma personagem for veterana/superior feminina (ex: Haruka-senpai), use SEMPRE artigos e adjetivos femininos ('a Senpai', 'dela', 'ela', 'ficou puta/brava').\n"

    concision_rule = (
        "PRINCÍPIO DE SCANLATION - ECONOMIA DE TEXTO E CABIMENTO NO BALÃO:\n"
        "- Balões de quadrinhos são pequenos. Evite frases excessivamente longas, prolixas ou literais que transbordem o espaço do balão.\n"
        "- Prefira diálogos ágeis, naturais e concisos em português brasileiro coloquial (ex: use 'O que cê tá fazendo?' em vez de 'O que é que você está fazendo aqui agora?', 'Não pode ser!' em vez de 'Isso de maneira alguma é possível!').\n"
        "- Elimine rodeios e palavras desnecessárias sem perder o significado original e a carga emocional da cena.\n"
        "- Mantenha a pontuação expressiva de mangá (!, ?, ..., ~)."
    )

    dos, donts = load_learning_rules(src_lang=src_lang)
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
                "Traduza mantendo o tom adulto (+18), sem censura e com gírias de scanlation brasileiro:\n"
                "- ANATOMIA E GÊNERO: 'pussy/cunt' é SEMPRE feminino ('buceta', 'xoxota'); 'cock/dick/penis' é SEMPRE masculino ('pau', 'pinto', 'rola', 'cacete'). NUNCA confunda o gênero em frases com ambos (ex: 'touch her pussy while sucking my dick' -> 'toca na buceta dela enquanto chupa meu pau').\n"
                "- AÇÕES: 'came / cum / cumming' em contexto sexual é SEMPRE 'gozou', 'gozar', 'gozando' (NUNCA 'veio' ou 'chegou'). 'came inside' -> 'gozou dentro'. 'creampie' -> 'gozada dentro / leitada'.\n"
                "- VESTIMENTA: 'panties / underwear' para mulher é 'calcinha' ou 'lingerie' (NUNCA 'cuecas').\n"
                "- FETICHE: 'sow' em mangás adultos é 'porca' ou 'vadia' (NUNCA o verbo 'semear').\n"
                "- GEMIDOS: 'u u u', 'mph', 'ahn', 'kuh' são sons de prazer; NUNCA traduza a letra 'u' como 'você'."
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
4. NUNCA use palavras em espanhol ou portunhol. Se o texto de entrada estiver em espanhol, traduza absolutamente tudo para português do Brasil ('Muchas gracias' -> 'Muito obrigado', 'joyas' -> 'joias', 'tienda' -> 'loja', 'hoy' -> 'hoje', 'todo el dinero' -> 'todo o dinheiro').
5. NUNCA confunda termos cotidianos/comerciais com termos genitais ('joyería' é 'joalheria', NUNCA 'buceta'; 'cuerpo' é 'corpo', NUNCA 'cu').
6. Adapte os textos para serem diretos e caberem perfeitamente em balões de fala."""

    if is_adult:
        return f"""{persona_intro}Você é um tradutor literário profissional de mangás adultos e scanlations para Português do Brasil (PT-BR).
Traduza fielmente o diálogo original com máxima naturalidade coloquial e fluidez brasileira, respeitando o tom da cena (romance, ecchi, diálogos picantes ou adultos).

VOCABULÁRIO E ADAPTAÇÃO OBRIGATÓRIA:
- 'pussy/cunt' -> SEMPRE feminino: 'buceta', 'xoxota' (NUNCA use 'pau').
- 'cock/dick' -> SEMPRE masculino: 'pau', 'pinto', 'rola', 'cacete'.
- 'came / cum / cumming' em sexo -> 'gozou', 'gozar', 'gozando' (NUNCA use 'veio').
- 'panties / underwear' (mulher) -> 'calcinha' ou 'lingerie' (NUNCA use 'cuecas').
- 'sow' (em eromanga) -> 'porca' ou 'vadia' (NUNCA o verbo 'semear').
- Gemidos ('u u u', 'mph', 'ahn', 'kuh') -> Mantenha o som expressivo do gemido, NUNCA traduza a letra 'u' como 'você'.

{concision_rule}
{learned_rules_text}

REGRAS OBRIGATÓRIAS:
1. Responda APENAS com o texto traduzido final em PT-BR. NUNCA converse, NUNCA introduza com "Aqui está", NUNCA adicione explicações, notas de tradutor ou referências ao sistema.
2. NUNCA use palavras em espanhol.
3. Adapte expressões e gírias com naturalidade autêntica brasileira (ex: 'came inside' -> 'gozou dentro'; 'honey' -> 'amor/querido').
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

def google_translate_free(text, source_lang="auto", target_lang="pt"):
    """Traduz texto diretamente usando Google Translate com detecção de idioma e fallback resiliente."""
    if not text or not str(text).strip():
        return ""
    clean = str(text).strip()

    raw_sl = str(source_lang or "auto").strip()
    sl_map = {
        "ko-kr": "ko", "ko": "ko",
        "ja-jp": "ja", "ja": "ja",
        "zh-cn": "zh-CN", "zh-tw": "zh-TW", "zh": "zh-CN",
        "en-us": "en", "en-gb": "en", "en": "en",
        "es-es": "es", "es": "es",
        "fr-fr": "fr", "fr": "fr",
        "de-de": "de", "de": "de",
        "it-it": "it", "it": "it",
        "ru-ru": "ru", "ru": "ru",
    }
    sl = sl_map.get(raw_sl.lower(), raw_sl)

    # Se source_lang for 'auto', detecta pelo conteúdo para evitar erros de APIs secundárias (ex: MyMemory)
    if sl == "auto":
        if re.search(r'[\uac00-\ud7af]', clean):
            sl = "ko"
        elif re.search(r'[\u3040-\u30ff]', clean):
            sl = "ja"
        elif re.search(r'[\u4e00-\u9fff]', clean):
            sl = "zh-CN"
        elif re.search(r'\b(el|la|los|las|de|en|un|una|por|con|para|del|al|que|es|como|mas|pero)\b', clean, re.IGNORECASE):
            sl = "es"
        else:
            sl = "en"

    # Tentativa 1: Endpoint GTX do Google usando código de idioma normalizado (`sl`)
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={urllib.parse.quote(sl)}&tl={urllib.parse.quote(target_lang)}&dt=t&q=" + urllib.parse.quote(clean)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8"))
            if data and data[0]:
                res_txt = "".join(seg[0] for seg in data[0] if seg and seg[0])
                if res_txt and res_txt.strip() and "<x " not in res_txt:
                    return res_txt.strip()
    except Exception:
        pass

    # Tentativa 2: deep_translator MyMemory com código BCP-47 explícito (NUNCA passa 'auto' nem aceita tags <x />)
    try:
        from deep_translator import MyMemoryTranslator
        mymem_map = {"ko": "ko-KR", "ja": "ja-JP", "zh": "zh-CN", "en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "it": "it-IT", "ru": "ru-RU"}
        mymem_sl = mymem_map.get(sl.lower(), sl if sl != "auto" else "zh-CN")
        res = MyMemoryTranslator(source=mymem_sl, target='pt-BR').translate(clean)
        if res and "<x " not in res and "INVALID SOURCE LANGUAGE" not in res and "MYMEMORY WARNING" not in res:
            return res.strip()
    except Exception:
        pass

    return clean

def execute_translation_request(messages, engine_opts=None, is_adult=True, max_tokens=1024, is_batch=False, dialogue_map=None, src_lang="auto"):
    """
    Roteador Inteligente e Resiliente de IAs.
    Tenta o motor ativo mantendo isolamento estrito de chaves por provedor (Groq vs OpenRouter),
    distinguindo pausas curtas de TPM vs esgotamento diário (TPD) e acionando fallback limpo sem poluir memória global.
    """
    engine_opts = engine_opts if engine_opts is not None else {}
    engine_opts["_last_used_fallback"] = False
    exhausted = engine_opts.setdefault("exhausted_engines", set())
    cfg = engine_opts.get("cfg", {})
    temp = engine_opts.get("temperature", 0.0)
    active_engine = engine_opts.get("active_engine", "groq")

    # 0. SE O MOTOR PRIORITÁRIO CONFIGURADO FOR OLLAMA (Modo Híbrido), TENTA OLLAMA PRIMEIRO
    if active_engine == "ollama" and "ollama" not in exhausted:
        host = engine_opts.get("host") or cfg.get("ollama_host", "http://localhost:11434")
        ollama_ok, o_model = check_ollama_available(prefer_uncensored=is_adult, host=host, custom_model=cfg.get("ollama_model"))
        if ollama_ok:
            try:
                resp = query_ollama_chat(messages, o_model, host=host, temperature=temp, num_predict=max_tokens)
                if resp:
                    return resp
            except Exception as o_err:
                exhausted.add("ollama")
                print(f"\n[!] Ollama indisponível ({o_err}).")
                print(f"[+] ALTERNANDO MOTOR DEFINITIVAMENTE -> Acionando Groq Cloud Nuvem...")
        else:
            exhausted.add("ollama")
            print(f"\n[!] Servidor Ollama offline ou sem GPU. Ativando fallback para Groq Cloud Nuvem...")

    # 1. TENTA GROQ SE AINDA NÃO ESGOTADO (COM ROTAÇÃO ENTRE CHAVES E RESILIÊNCIA A TPM)
    if "groq" not in exhausted:
        all_groq_keys = list(engine_opts.get("groq_api_keys") or cfg.get("groq_api_keys") or [])
        if not all_groq_keys and cfg.get("groq_api_key"):
            all_groq_keys = [cfg.get("groq_api_key")]
        eng_k = str(engine_opts.get("api_key", "") or "").strip()
        if eng_k and (active_engine == "groq" or eng_k.startswith("gsk_")) and eng_k not in all_groq_keys:
            all_groq_keys.insert(0, eng_k)

        exhausted_keys = engine_opts.setdefault("exhausted_groq_keys", set())
        avail_keys = [k.strip() for k in all_groq_keys if k and k.strip() and k.strip() not in exhausted_keys]

        if avail_keys:
            tried_tpm_keys = []
            for idx_k, groq_k in enumerate(avail_keys):
                model_name = engine_opts.get("active_model") or engine_opts.get("model_name") or cfg.get("groq_model", "qwen/qwen3.8-27b")
                fb_model = engine_opts.get("fallback_model") or cfg.get("groq_fallback_model", "openai/gpt-oss-120b")
                try:
                    resp = query_groq_chat(
                        messages,
                        model_name,
                        groq_k,
                        temperature=temp,
                        max_tokens=max_tokens,
                        fallback_model=fb_model,
                        engine_opts=engine_opts,
                        allow_tpm_wait=(len(avail_keys) == 1)
                    )
                    if resp:
                        return resp
                except GroqRateLimitError as g_err:
                    masked_k = groq_k[:8] + "..." + groq_k[-4:] if len(groq_k) > 12 else "***"
                    if g_err.is_tpm and not g_err.is_daily and not g_err.is_auth:
                        tried_tpm_keys.append((groq_k, g_err.retry_after or 12.0))
                        if idx_k + 1 < len(avail_keys):
                            print(f"\n[*] Chave Groq ({masked_k}) em pausa momentânea de TPM. Tentando próxima chave Groq...")
                        continue
                    exhausted_keys.add(groq_k)
                    engine_opts["exhausted_groq_models"] = set()
                    print(f"\n[!] Chave Groq ({masked_k}) esgotada/indisponível ({g_err}).")
                except Exception as g_err:
                    exhausted_keys.add(groq_k)
                    engine_opts["exhausted_groq_models"] = set()
                    masked_k = groq_k[:8] + "..." + groq_k[-4:] if len(groq_k) > 12 else "***"
                    print(f"\n[!] Chave Groq ({masked_k}) falhou ({g_err}).")

            if tried_tpm_keys:
                best_k, wait_s = min(tried_tpm_keys, key=lambda it: it[1])
                sleep_s = min(max(wait_s + 0.5, 2.0), 38.0)
                print(f"\n[*] Todas as chaves Groq atingiram pico breve de TPM. Aguardando {sleep_s:.1f}s para liberar tokens...")
                time.sleep(sleep_s)
                cd_map = engine_opts.get("groq_model_cooldowns", {})
                key_sig = best_k[:12]
                now_t = time.time()
                for ck in list(cd_map.keys()):
                    if ck.startswith(key_sig + ":") and cd_map[ck] <= now_t + 1.0:
                        cd_map.pop(ck, None)
                try:
                    model_name = engine_opts.get("active_model") or engine_opts.get("model_name") or cfg.get("groq_model", "qwen/qwen3.8-27b")
                    fb_model = engine_opts.get("fallback_model") or cfg.get("groq_fallback_model", "openai/gpt-oss-120b")
                    resp = query_groq_chat(
                        messages,
                        model_name,
                        best_k,
                        temperature=temp,
                        max_tokens=max_tokens,
                        fallback_model=fb_model,
                        engine_opts=engine_opts,
                        allow_tpm_wait=False
                    )
                    if resp:
                        return resp
                except GroqRateLimitError as g2:
                    if g2.is_daily or g2.is_auth:
                        exhausted_keys.add(best_k)
                except Exception:
                    pass
            else:
                rem_after = [k.strip() for k in all_groq_keys if k and k.strip() and k.strip() not in exhausted_keys]
                if not rem_after:
                    exhausted.add("groq")
                    print(f"\n[!] Todas as {len(all_groq_keys)} chaves cadastradas do Groq Cloud atingiram as cotas diárias.")
                    print(f"[+] ALTERNANDO MOTOR DEFINITIVAMENTE -> Verificando OpenRouter...")
        else:
            exhausted.add("groq")

    # 2. TENTA OPENROUTER SE AINDA NÃO ESGOTADO (COM ISOLAMENTO ESTRITO DE CHAVES)
    if "openrouter" not in exhausted:
        raw_or_pool = (
            engine_opts.get("openrouter_api_keys")
            or cfg.get("openrouter_api_keys", [])
            or ([cfg.get("openrouter_api_key")] if cfg.get("openrouter_api_key") else [])
        )
        or_keys = [
            str(k).strip() for k in raw_or_pool
            if str(k or "").strip() and not str(k).strip().startswith("gsk_")
        ]
        if or_keys:
            or_model = cfg.get("openrouter_model", "nvidia/nemotron-3.5-lightning:free")
            try:
                resp = query_openrouter_chat(
                    messages,
                    or_model,
                    api_key=or_keys[0],
                    api_keys=or_keys,
                    temperature=temp,
                    max_tokens=max_tokens,
                    engine_opts=engine_opts
                )
                if resp:
                    return resp
            except Exception as or_err:
                exhausted.add("openrouter")
                print(f"\n[!] OpenRouter indisponível ({or_err}).")
                print(f"[+] ALTERNANDO MOTOR DEFINITIVAMENTE -> Verificando Ollama / Google...")
        else:
            exhausted.add("openrouter")

    # 3. TENTA OLLAMA SE AINDA NÃO ESGOTADO
    if "ollama" not in exhausted:
        host = cfg.get("ollama_host", "http://localhost:11434")
        ollama_ok, o_model = check_ollama_available(prefer_uncensored=is_adult, host=host, custom_model=cfg.get("ollama_model"))
        if ollama_ok:
            try:
                resp = query_ollama_chat(messages, o_model, host=host, temperature=temp, num_predict=max_tokens)
                if resp:
                    return resp
            except Exception as o_err:
                exhausted.add("ollama")
                print(f"\n[!] Ollama indisponível ({o_err}).")
        else:
            exhausted.add("ollama")

    # 4. FALLBACK FINAL AUTOMÁTICO: GOOGLE TRANSLATOR (não grava em memoria_traducoes.json)
    engine_opts["_last_used_fallback"] = True
    if not engine_opts.get("_google_announced"):
        print("\n[+] MOTOR DE EMERGÊNCIA ATIVADO: Traduzindo via Google Translator Direto (Alta velocidade, sem bloqueios)...")
        engine_opts["_google_announced"] = True

    if is_batch and dialogue_map:
        batch_out = {}
        fb_set = engine_opts.setdefault("_fallback_originals", set())
        for k, orig in dialogue_map.items():
            fb_set.add(orig)
            try:
                t = google_translate_free(orig, source_lang=src_lang)
                batch_out[k] = clean_ai_translation(t, original_text=orig, is_adult=is_adult)
            except Exception:
                batch_out[k] = orig
        return json.dumps(batch_out, ensure_ascii=False)
    else:
        user_content = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_content = m.get("content", "")
                break
        clean_target = user_content.replace("Traduza fielmente para PT-BR:\n\n", "").strip()
        engine_opts.setdefault("_fallback_originals", set()).add(clean_target)
        try:
            return google_translate_free(clean_target, source_lang=src_lang)
        except Exception:
            return clean_target

def translate_single_dialogue(text, engine_type=None, model_name=None, engine_opts=None, is_adult=True, src_lang="auto"):
    """Traduz uma única fala com roteamento resiliente e fallback instantâneo."""
    clean_t = clean_ocr_scan_noise(text.strip())
    if is_scan_watermark(clean_t):
        return ""
    sfx_res = translate_sfx_phrase(clean_t)
    if sfx_res:
        return sfx_res

    engine_opts = engine_opts if engine_opts is not None else {}

    # 1. Tenta prompt adulto
    if is_adult:
        sys_prompt = build_translation_system_prompt(is_adult=True, is_batch=False, src_lang=src_lang)
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Traduza fielmente para PT-BR:\n\n{clean_t}"}
        ]
        res = execute_translation_request(messages, engine_opts=engine_opts, is_adult=True, max_tokens=350, is_batch=False, src_lang=src_lang)
        cleaned = clean_ai_translation(res, original_text=clean_t, is_adult=True)
        if cleaned and is_valid_translation(clean_t, cleaned):
            if engine_opts.get("_last_used_fallback"):
                engine_opts.setdefault("_fallback_originals", set()).add(text.strip())
            return cleaned

    # 2. Fallback neutro (apenas se o motor anterior não caiu direto para o Google ou se o resultado adulto foi rejeitado)
    sys_prompt = build_translation_system_prompt(is_adult=False, is_batch=False, src_lang=src_lang)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"Traduza fielmente para PT-BR:\n\n{clean_t}"}
    ]
    res = execute_translation_request(messages, engine_opts=engine_opts, is_adult=False, max_tokens=350, is_batch=False, src_lang=src_lang)
    cleaned = clean_ai_translation(res, original_text=clean_t, is_adult=False)
    if cleaned and is_valid_translation(clean_t, cleaned):
        if engine_opts.get("_last_used_fallback"):
            engine_opts.setdefault("_fallback_originals", set()).add(text.strip())
        return cleaned

    engine_opts.setdefault("_fallback_originals", set()).add(text.strip())
    return google_translate_free(clean_t, source_lang=src_lang)

def build_page_spatial_dossier(bubbles_to_trans, page_w=1200, page_h=1800, src_lang="auto"):
    """
    Agente 1 (Mapeador Espacial & Cartógrafo de Balões):
    Inspeciona a geometria dos balões na página, calcula a capacidade de caracteres (typesetting)
    e organiza tudo na ordem canônica de leitura oriental (Direita -> Esquerda, Topo -> Base).
    """
    page_w = max(100, page_w or 1200)
    page_h = max(100, page_h or 1800)
    dossier_bubbles = []
    
    for idx, (orig_text, b_obj) in enumerate(bubbles_to_trans):
        box = b_obj.get("box", [0, 0, 0, 0]) if isinstance(b_obj, dict) else [0, 0, 0, 0]
        xmin, ymin, xmax, ymax = box
        bw = max(1, xmax - xmin)
        bh = max(1, ymax - ymin)
        area = bw * bh
        
        # Posição vertical na página
        if ymin < page_h * 0.35:
            v_pos = "topo"
        elif ymin > page_h * 0.65:
            v_pos = "rodapé"
        else:
            v_pos = "meio"
            
        # Posição horizontal na página
        if xmin > page_w * 0.55:
            h_pos = "direita"
        elif xmax < page_w * 0.45:
            h_pos = "esquerda"
        else:
            h_pos = "centro"
            
        pos_label = f"{v_pos}-{h_pos}"
        
        # Formato e aspecto do balão
        aspect = bw / bh
        if aspect < 0.6:
            b_format = "balão vertical estreito"
        elif aspect > 1.8:
            b_format = "caixa retangular horizontal"
        else:
            b_format = "balão oval / circular de diálogo"
            
        # Orçamento de caracteres recomendados (considera expansão CJK/Hangul -> PT-BR para não podar falas asiáticas)
        raw_char_len = len(orig_text)
        is_asian_src = str(src_lang or "").lower() in ("ko-kr", "ko", "ja-jp", "ja", "zh-cn", "zh-tw", "zh") or bool(
            re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', orig_text)
        )
        char_mult = 2.4 if is_asian_src else 1.35
        if area < 16000:
            floor_c = 28 if is_asian_src else 20
            ceil_c = 70 if is_asian_src else 50
            char_budget = max(floor_c, min(ceil_c, int(raw_char_len * char_mult)))
            cap_desc = f"pequeno (máx recomendável: {char_budget} carac.)"
        elif area < 50000:
            floor_c = 45 if is_asian_src else 40
            ceil_c = 130 if is_asian_src else 100
            char_budget = max(floor_c, min(ceil_c, int(raw_char_len * char_mult)))
            cap_desc = f"médio (máx recomendável: {char_budget} carac.)"
        else:
            floor_c = 80
            ceil_c = 260 if is_asian_src else 240
            char_budget = max(floor_c, min(ceil_c, int(raw_char_len * char_mult)))
            cap_desc = f"amplo (máx recomendável: {char_budget} carac.)"
            
        cleaned_t = clean_ocr_scan_noise(orig_text)
        
        dossier_bubbles.append({
            "pos": pos_label,
            "formato": b_format,
            "capacidade": cap_desc,
            "max_chars": char_budget,
            "xmin": xmin,
            "ymin": ymin,
            "xmax": xmax,
            "ymax": ymax,
            "texto_original": cleaned_t,
            "orig_raw": orig_text
        })
        
    # Ordena pela ordem canônica de mangá (RTL: Direita para Esquerda, Topo para Base)
    # ymin agrupado em faixas de ~160px, xmax decrescente
    dossier_bubbles.sort(key=lambda b: (b["ymin"] // 160, -b["xmax"]))
    
    ordered_bubbles = []
    dialogue_map = {}
    for new_idx, b_info in enumerate(dossier_bubbles):
        k = str(new_idx + 1)
        b_info["id"] = k
        dialogue_map[k] = b_info["orig_raw"]
        ordered_bubbles.append(b_info)
        
    return {
        "layout": "manga_oriental (leitura da direita para a esquerda, topo para base)",
        "idioma_detectado": src_lang,
        "total_baloes": len(ordered_bubbles),
        "baloes": ordered_bubbles
    }, dialogue_map

def build_dual_engine_system_prompt(is_adult=True, glossary=None, src_lang="auto"):
    """Gera o prompt do Agente 2 (Tradutor Literário & Contextualizador de Cena),
    compactando automaticamente para obras asiáticas (Coreano/Japonês/Chinês) para respeitar limites TPM."""
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

    dos, donts = load_learning_rules(src_lang=src_lang)
    learned_rules_text = ""
    if dos or donts:
        learned_rules_text = "\nMEMÓRIA E APRENDIZADO CONTÍNUO DO USUÁRIO:\n"
        if dos:
            learned_rules_text += "[O QUE VOCÊ DEVE FAZER E PRIORIZAR]:\n" + "\n".join(f"- {d.lstrip('-*• ')}" for d in dos) + "\n"
        if donts:
            learned_rules_text += "[O QUE VOCÊ NUNCA DEVE FAZER / PROIBIÇÕES]:\n" + "\n".join(f"- {d.lstrip('-*• ')}" for d in donts) + "\n"

    is_asian = str(src_lang or "").lower() in ("ko-kr", "ko", "ja-jp", "ja", "zh-cn", "zh-tw", "zh")
    if is_asian:
        lang_tag = "COREANO (Hangul / Manhwa)" if "ko" in str(src_lang).lower() else (
            "CHINÊS (Hanzi / Manhua)" if "zh" in str(src_lang).lower() else "JAPONÊS (Mangá)"
        )
        ko_hints = ""
        if "ko" in str(src_lang).lower():
            ko_hints = (
                "- COREANO (+18 & GÍRIAS): '자지/고추' -> 'pau/pinto'; '보지' -> 'buceta'; '유두/젖꼭지' -> 'mamilo/biquinho'; '딸치다/딸치지' -> 'bater uma / se masturbar usando' (NUNCA apenas 'bater em'); '자위펫' -> 'pet de masturbação / brinquedo'.\n"
                "- DESAMBIGUAÇÃO COREANA: '쓰고' com sexual/ferramenta é 'usar/usando/metendo' (NUNCA 'escrever/escrevendo/Escribendo'); '바둑이' é o nome próprio 'Baduki' (NUNCA traduza como 'Go'); '-님' após nome é '-sama' ou 'senhor(a)' (NUNCA '-sen'); '수인' é 'bestiais / homens-fera' (não deixe 'Suin'); '야옹/냥' -> 'miau'; '갈 것 같다/싸다/가버렷' -> 'vou gozar/gozei'; '따라 해봐' -> 'tenta repetir comigo/faz igual'.\n"
            )
        adult_compact = ""
        if is_adult:
            adult_compact = (
                "\nLOCALIZAÇÃO ADULTA (+18 - ZERO CENSURA):\n"
                "- Use PT-BR coloquial explícito de scanlation brasileiro: 'buceta', 'xoxota', 'pau', 'pinto', 'gozar', 'gozando', 'calcinha', 'tesão'.\n"
                f"{ko_hints}"
                "- Correspondência de gênero: concorde sempre pronomes/adjetivos com quem fala e com a cena.\n"
            )
        learned_compact = ""
        if dos or donts:
            learned_compact = "\nREGRAS DO USUÁRIO:\n"
            for d in dos[:18]:
                learned_compact += f"- {d.lstrip('-*• ')}\n"
            for d in donts[:12]:
                learned_compact += f"- PROIBIDO: {d.lstrip('-*• ')}\n"
        return f"""Você é o Agente 2: Tradutor Literário de scanlation ({lang_tag} -> Português do Brasil).
O Agente 1 enviou os balões da página em ordem de leitura com limite recomendado de caracteres ('max_chars').

REGRAS ESSENCIAIS:
1. Estude a cena completa da página para manter continuidade, pronomes e gênero corretos entre personagens.
2. Adapte para PT-BR coloquial, ágil e conciso para caber elegante em cada balão (respeite 'max_chars').
3. ZERO palavras em espanhol/portunhol ou texto asiático residual; mantenha pontuação (!, ?, ..., ~, ♡).
4. NUNCA imprima explicações ou notas de tradutor.{adult_compact}{glossary_rules}{learned_compact}
FORMATO EXCLUSIVO DE RESPOSTA:
Responda EXCLUSIVAMENTE um objeto JSON válido com os IDs numéricos:
{{"1": "Tradução 1", "2": "Tradução 2"}}"""

    persona_intro = (
        "Você é o Agente 2: Tradutor Literário e Contextualizador Narrativo de elite da nossa equipe de scanlation.\n"
        "O Agente 1 (Mapeador Espacial) analisou visualmente a página original e gerou o DOSSIÊ ESTRUTURAL com posições, ordem de leitura oriental e limites físicos de cada balão.\n\n"
    )

    multilang_clause = (
        "DIRETRIZES DE TRADUÇÃO MULTI-IDIOMA (ESPANHOL / INGLÊS / JAPONÊS / COREANO -> PT-BR):\n"
        "- A obra original pode estar em ESPANHOL, INGLÊS, JAPONÊS ou COREANO. Sua saída DEVE ser 100% em PORTUGUÊS DO BRASIL coloquial, fluído e dinâmico.\n"
        "- ZERO TOLERÂNCIA A ESPANHOL RESIDUAL: NUNCA mantenha frases ou termos em espanhol como 'Muchas gracias' (use 'Muito obrigado/a'), 'joyas' (use 'joias'), 'tienda' (use 'loja'), 'ropa' (use 'roupa'), 'hoy' (use 'hoje'), 'todo el dinero' (use 'todo o dinheiro'), 'vengan' (use 'venham'), 'sirvase' (use 'fique à vontade'), 'calientura' (use 'tesão' ou 'fogo').\n"
        "- DISTINÇÃO ENTRE CONTEXTO COMERCIAL E CONTEXTO ERÓTICO: Em cenas de lojas, joalherias, piercings, roupas ou fichas técnicas, NUNCA confunda termos cotidianos com genitais (ex: 'joyería' é 'joalheria', NUNCA 'buceta'; 'cuerpo' é 'corpo', NUNCA 'cu').\n"
        "- REGRAS ESTREITAS ANTI-VAZAMENTO: NUNCA imprima diretrizes internas, observações, notas de tradutor ou avisos de sistema. Saída estritamente com os diálogos adaptados.\n"
    )

    adult_clause = ""
    if is_adult:
        adult_clause = (
            "DIRETRIZES DE LOCALIZAÇÃO ADULTA (+18 - ZERO CENSURA):\n"
            "- ANATOMIA E GÊNERO: 'pussy/cunt' é SEMPRE feminino ('buceta', 'xoxota'); 'cock/dick/penis' é SEMPRE masculino ('pau', 'pinto', 'rola', 'cacete'). NUNCA confunda o gênero em frases com ambos (ex: 'touch Mom\\'s pussy while you suck my dick' -> 'toca na buceta da mamãe enquanto chupa meu pau').\n"
            "- ESPANHOL ADULTO: 'coño / rajita' -> 'buceta', 'xoxota'. 'pene / verga / polla' -> 'pau', 'pinto', 'rola'. 'coger' em espanhol adulto é 'foder', 'transar', 'dar uma foda'. 'calentura' é 'tesão', 'fogo'. 'correrse / se vino / me vengo' -> 'gozar', 'gozou', 'estou gozando'.\n"
            "- AÇÕES: 'came / cum / cumming' em contexto sexual é SEMPRE 'gozou', 'gozar', 'gozando' (NUNCA 'veio' ou 'chegou'). 'came inside' -> 'gozou dentro'. 'creampie' -> 'gozada dentro / leitada'.\n"
            "- GRITOS E CLÍMAX: 'I'm cumming / CUMIN G / Cu MING' -> 'Estou gozando!'. 'I can't hold it anymore / CAN TH OLD' -> 'Não aguento mais segurar! / Não consigo mais segurar!'.\n"
            "- DINÂMICAS ÍNTIMAS E GÊNERO: Ao falar com mulher, 'you're so wet / getting wet' é SEMPRE feminino ('você está tão molhada / ficando molhada'). Mulher falando: 'I'll be your partner' -> 'serei sua parceira'. Filho falando com a mãe sobre o pai ('Dad') diz 'O papai' ou 'Meu pai' (NUNCA 'Seu pai').\n"
            "- MADRASTA E ENTEADO: Falando com a madrasta/mulher, 'you are a stranger' é SEMPRE feminino ('você é uma estranha para mim'). 'act all motherly' é 'agir como mãe' ou 'toda maternal' (NUNCA 'de forma material'). 'nuisance' é 'um estorvo' ou 'um incômodo' (NUNCA a palavra inexistente 'incomodável').\n"
            "- NOMES E PRATOS JAPONESES: 'Oyakodon' é o prato de frango e ovo (NUNCA corte como 'oya kod'). Nomes de pessoas como 'Hatsuko' são nomes próprios (NUNCA traduza 'Hats' como 'chapéus').\n"
            "- VESTIMENTA: 'panties / underwear' para mulher é 'calcinha' ou 'lingerie' (NUNCA 'cuecas').\n"
            "- FETICHE: 'sow' em mangás adultos é 'porca' ou 'vadia' (NUNCA o verbo 'semear').\n"
            "- GEMIDOS E RUÍDOS: 'u u u', 'mph', 'ahn', 'kuh' são sons de prazer; NUNCA traduza a letra 'u' como 'você' nem confunda 'Anh...!' com 'irmão mais velho'. Mantenha o som expressivo (ex: 'Ugh... uh... mmph...', 'Anh...!').\n"
        )

    ocr_reconstruction_clause = (
        "DIRETRIZES DE RECONSTRUÇÃO DE OCR E PALAVRAS FRAGMENTADAS (MANGÁ & COMIC FONTS):\n"
        "- Os textos fornecidos vêm de reconhecimento óptico (OCR) de balões de quadrinhos e contêm falhas frequentes de quebra e diagramação:\n"
        "- PALAVRAS QUEBRADAS OU SEPARADAS INDEVIDAMENTE: Reconstrua mentalmente a palavra antes de traduzir:\n"
        "  * 'CONS E- QUE N CES' / 'CONSEQUE N CES' -> 'consequences' -> 'consequências'\n"
        "  * 'AC KNOWL-' -> 'acknowledge' -> 'reconhecer'\n"
        "  * 'ARRANGE- MENT S' / 'ARRANGEMENT S' -> 'arrangements' -> 'preparativos'\n"
        "  * 'SUP- PRESSED' -> 'suppressed' -> 'suprimidos'\n"
        "  * 'Wit c H\'S' -> 'Witch\'s' -> 'da bruxa'\n"
        "  * 'H app Y' -> 'happy' -> 'feliz'\n"
        "  * 'IRU LY' -> 'truly' -> 'realmente'\n"
        "  * 'mad or omi' -> 'Madoromi' (título da obra / nome próprio)\n"
        "  * 'mi y obi' -> 'Miyobi' (autor / círculo)\n"
        "  * 'FURY A' -> 'Furiya' (nome de personagem)\n"
        "  * 'ROCHE -SAN' -> 'Roche-san'\n"
        "  * 'ONEE SAM AS' -> 'Onee-sama\'s' ('da minha irmã mais velha')\n"
        "- CARACTERES CONFUNDIDOS PELO SCAN ÓPTICO:\n"
        "  * 'It, feels poo 6' -> 'It feels so good' -> 'É tão gostoso / É uma delícia'\n"
        "  * 'LN ABLE TO SLEEP' -> 'UNABLE TO SLEEP' -> 'Incapaz de dormir / Sem conseguir dormir' (NUNCA inverta o sentido!)\n"
        "  * 'what am T even s aging' -> 'what am I even saying' -> 'o que eu estou dizendo'\n"
        "  * 'ARE YO LI OKAY' -> 'ARE YOU OKAY' -> 'você está bem?'\n"
        "  * 'I-IS S IHL REAL LIFE' -> 'IS THIS REAL LIFE' -> 'isso é a vida real?'\n"
        "  * 'SPITTING WAGE ... IS A WIN' -> 'SPITTING IMAGE ... I SAW IN' -> 'a cara/cópia da mulher que vi em um sonho'\n"
        "  * 'OP THEIR HEART' -> 'OF THEIR HEART' -> 'do seu coração'\n"
        "  * 'M LIST MEET' -> 'MUST MEET' -> 'tem que conhecer'\n"
        "- CONTINUIDADE ENTRE BALÕES: Leia todos os balões da página para entender frases divididas entre dois balões adjacentes e traduza a narrativa com coerência fluida.\n"
        "- REGRA FUNDAMENTAL: Reconstrua SEMPRE o diálogo real pretendido pelo autor no contexto da cena antes de gerar a tradução para PT-BR.\n"
    )

    return f"""{persona_intro}Sua missão é realizar a tradução e adaptação contextual de excelência literária para Português do Brasil (PT-BR).

SUAS TAREFAS OBRIGATÓRIAS:
1. ESTUDO DE CENA E PERSONAGENS:
   - Leia todas as falas na ordem de leitura fornecida (topo-direita -> base-esquerda).
   - Identifique quem está conversando com quem (homem, mulher, mãe e filho, superior e subordinado, amantes, amigos).
   - Garanta 100% de concordância de gênero nos pronomes, artigos e adjetivos (ex: 'cansada', 'ficou louca', 'meu amor', 'na buceta').

2. ADAPTAÇÃO AO TAMANHO DO BALÃO (TYPESETTING MILIMÉTRICO):
   - Cada balão possui uma recomendação de capacidade física ('max_chars').
   - Adapte a tradução em PT-BR para caber com elegância dentro desse limite.
   - Seja conciso e ágil como um verdadeiro diálogo de mangá brasileiro (ex: 'Nem pensar!' em vez de 'Isso de maneira alguma seria possível').

3. VOCABULÁRIO E TOM:
   - Use português do Brasil coloquial autêntico, fluido e expressivo (estilo MangaPlus / Crunchyroll).
   - Mantenha a pontuação dramática de mangá (!, ?, ..., ~).
   - NUNCA use palavras em espanhol ou portunhol.

{ocr_reconstruction_clause}
{multilang_clause}
{adult_clause}
{glossary_rules}
{learned_rules_text}

FORMATO EXCLUSIVO DE RESPOSTA:
Responda EXCLUSIVAMENTE em formato JSON com os IDs numéricos de cada balão:
{{
  "1": "Tradução adaptada da fala 1",
  "2": "Tradução adaptada da fala 2"
}}"""

def translate_page_dialogue(bubbles_to_trans, engine_type=None, model_name=None, engine_opts=None, is_adult=True, glossary=None, page_w=1200, page_h=1800, src_lang="auto", page_num=1):
    """Traduz falas de uma página usando a cooperação entre Agente 1 (Cartógrafo Espacial) e Agente 2 (Contextualizador Literário)."""
    if not bubbles_to_trans:
        return {}

    engine_opts = engine_opts if engine_opts is not None else {}
    results = {}

    # 1. Agente 1 constrói o dossiê estrutural e espacial
    dossier, dialogue_map = build_page_spatial_dossier(bubbles_to_trans, page_w=page_w, page_h=page_h, src_lang=src_lang)
    
    needed_bubbles = []
    for b in dossier["baloes"]:
        orig = b["orig_raw"]
        cleaned_orig = b["texto_original"]
        if is_scan_watermark(cleaned_orig):
            results[orig] = ""
            continue
        sfx_res = translate_sfx_phrase(cleaned_orig)
        if sfx_res:
            results[orig] = sfx_res
            continue
        needed_bubbles.append(b)

    if not needed_bubbles:
        return results

    # Prepara payload estruturado para o Agente 2
    dossier_payload = {
        "ordem_leitura": dossier["layout"],
        "idioma_original": dossier["idioma_detectado"],
        "baloes_da_pagina": [
            {
                "id": b["id"],
                "posicao_espacial": b["pos"],
                "formato_balao": b["formato"],
                "max_chars": b["max_chars"],
                "texto_original": b["texto_original"]
            }
            for b in needed_bubbles
        ]
    }

    print(f"[*] [Agente 1: Cartógrafo] Mapeou {len(needed_bubbles)} balões na pág {page_num} (Leitura RTL • Typesetting sob medida)")

    sys_prompt = build_dual_engine_system_prompt(is_adult=is_adult, glossary=glossary, src_lang=src_lang)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": json.dumps(dossier_payload, ensure_ascii=False, separators=(",", ":"))}
    ]

    has_long_text = any(len(b["texto_original"]) > 60 for b in needed_bubbles)
    batch_max_tokens = 1150 if has_long_text else 850

    resp_content = execute_translation_request(
        messages,
        engine_opts=engine_opts,
        is_adult=is_adult,
        max_tokens=batch_max_tokens,
        is_batch=True,
        dialogue_map={b["id"]: b["orig_raw"] for b in needed_bubbles},
        src_lang=src_lang
    )

    used_fb_batch = bool(engine_opts.get("_last_used_fallback"))
    resp_clean = _strip_think_tags(resp_content)
    json_match = re.search(r'\{.*\}', resp_clean, flags=re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            for k, trans in parsed.items():
                if k in dialogue_map:
                    orig = dialogue_map[k]
                    cleaned_trans = clean_ai_translation(trans, original_text=orig, is_adult=is_adult)
                    if cleaned_trans and cleaned_trans.strip().lower() != orig.strip().lower():
                        results[orig] = cleaned_trans
                        if used_fb_batch:
                            engine_opts.setdefault("_fallback_originals", set()).add(orig)
            print(f"[+] [Agente 2: Contextualizador] Cena da pág {page_num} contextualizada e traduzida com sucesso.")
        except Exception:
            pass

    # Fallback para qualquer balão ausente ou cortado
    for b in needed_bubbles:
        orig = b["orig_raw"]
        if orig not in results or not is_valid_translation(orig, results[orig]):
            single_res = translate_single_dialogue(orig, engine_opts=engine_opts, is_adult=is_adult, src_lang=src_lang)
            if single_res and is_valid_translation(orig, single_res):
                results[orig] = single_res
            else:
                engine_opts.setdefault("_fallback_originals", set()).add(orig)
                results[orig] = google_translate_free(orig, source_lang=src_lang)

    return results

def translate_with_ollama(text, model_name, is_adult=True):
    """Alias retrocompatível para tradução de fala única."""
    return translate_single_dialogue(text, "ollama", model_name, {"host": "http://localhost:11434"}, is_adult=is_adult)

def translate_page_dialogue_with_ollama(bubbles_to_trans, model_name, is_adult=True, glossary=None):
    """Alias retrocompatível para tradução de lote por página."""
    return translate_page_dialogue(bubbles_to_trans, "ollama", model_name, {"host": "http://localhost:11434"}, is_adult=is_adult, glossary=glossary)

def translate_batch_texts(text_list, src_lang="auto", is_adult=True, engine_type=None, model_name=None, engine_opts=None):
    """Traduz lista de textos com fallback limpo sem loops."""
    if not text_list:
        return []

    engine_opts = engine_opts if engine_opts is not None else {}
    results = []

    for i, t in enumerate(text_list):
        clean_t = t.strip()
        if not clean_t or clean_t in ("...", "…", "!!", "!?"):
            results.append(clean_t)
            continue

        sfx_res = translate_sfx_phrase(clean_t)
        if sfx_res:
            results.append(sfx_res)
            continue

        res = translate_single_dialogue(clean_t, engine_opts=engine_opts, is_adult=is_adult, src_lang=src_lang)
        if not res or not is_valid_translation(clean_t, res):
            engine_opts.setdefault("_fallback_originals", set()).add(clean_t)
            res = google_translate_free(clean_t, source_lang=src_lang)

        results.append(res)

    return results

def create_html_reader(images_dir, title):
    """Gera leitor web moderno, imersivo e adaptativo para celular, tablet e desktop."""
    import urllib.parse
    images = [f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f != "leitor.html"]
    images.sort(key=natural_sort_key)

    if not images:
        return

    safe_title = html.escape(str(title or "Mangá Traduzido"))
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

KOREAN_MODEL_DIR = os.path.join(SCRIPT_DIR, "models", "korean")
KOREAN_REC_PATH = os.path.join(KOREAN_MODEL_DIR, "korean_PP-OCRv5_rec_infer.onnx")
KOREAN_DICT_PATH = os.path.join(KOREAN_MODEL_DIR, "korean_v5_dict.txt")

def _onnx_ensure_character_metadata(onnx_path, dict_path):
    """Embute a propriedade protobuf 'character' no ONNX se ausente (exigido pelo RapidOCR 1.2.x que ignora rec_keys_path)."""
    if not (os.path.exists(onnx_path) and os.path.exists(dict_path)):
        return False
    try:
        import struct
        with open(onnx_path, "rb") as f:
            data = f.read()

        def _read_varint(buf, pos):
            res = 0
            shift = 0
            while pos < len(buf):
                b = buf[pos]
                pos += 1
                res |= (b & 0x7F) << shift
                if not (b & 0x80):
                    return res, pos
                shift += 7
            raise ValueError("EOF")

        def _encode_varint(val):
            out = bytearray()
            while val > 0x7F:
                out.append((val & 0x7F) | 0x80)
                val >>= 7
            out.append(val)
            return bytes(out)

        pos = 0
        has_char = False
        while pos < len(data):
            tag, pos = _read_varint(data, pos)
            fn, wt = tag >> 3, tag & 7
            if wt == 0:
                _, pos = _read_varint(data, pos)
            elif wt == 1:
                pos += 8
            elif wt == 2:
                length, pos = _read_varint(data, pos)
                val = data[pos:pos + length]
                pos += length
                if fn == 14:
                    p2 = 0
                    k_str = ""
                    while p2 < len(val):
                        t2, p2 = _read_varint(val, p2)
                        fn2, wt2 = t2 >> 3, t2 & 7
                        if wt2 == 2:
                            l2, p2 = _read_varint(val, p2)
                            v2 = val[p2:p2 + l2]
                            p2 += l2
                            if fn2 == 1:
                                k_str = v2.decode("utf-8", errors="ignore")
                        elif wt2 == 0:
                            _, p2 = _read_varint(val, p2)
                    if k_str == "character":
                        has_char = True
                        break
            elif wt == 5:
                pos += 4
            else:
                break

        if has_char:
            return True

        with open(dict_path, "r", encoding="utf-8") as df:
            chars_val = "\n".join(line.rstrip("\r\n") for line in df)
        k_bytes = b"character"
        v_bytes = chars_val.encode("utf-8")
        entry = (
            b"\x0a" + _encode_varint(len(k_bytes)) + k_bytes +
            b"\x12" + _encode_varint(len(v_bytes)) + v_bytes
        )
        prop_field = b"\x72" + _encode_varint(len(entry)) + entry
        with open(onnx_path, "wb") as f:
            f.write(data + prop_field)
        return True
    except Exception as e:
        print(f"[!] Aviso ao verificar metadados ONNX do modelo coreano: {e}")
        return os.path.exists(onnx_path)

def ensure_korean_ocr_model():
    """Garante que os arquivos do modelo de OCR Coreano (PP-OCRv5 ONNX + dict com metadados) estejam prontos."""
    os.makedirs(KOREAN_MODEL_DIR, exist_ok=True)
    if not os.path.exists(KOREAN_REC_PATH):
        try:
            print("[*] Baixando modelo de OCR Coreano PP-OCRv5 (korean_PP-OCRv5_rec_infer.onnx)...")
            url_m = "https://huggingface.co/monkt/paddleocr-onnx/resolve/main/languages/korean/rec.onnx"
            req = urllib.request.Request(url_m, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=60) as resp, open(KOREAN_REC_PATH, 'wb') as f:
                f.write(resp.read())
        except Exception as e:
            print(f"[!] Erro ao baixar modelo coreano PP-OCRv5: {e}")
    if not os.path.exists(KOREAN_DICT_PATH):
        try:
            print("[*] Baixando dicionário PP-OCRv5 de Hangul Coreano...")
            url_d = "https://huggingface.co/monkt/paddleocr-onnx/resolve/main/languages/korean/dict.txt"
            req = urllib.request.Request(url_d, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as resp, open(KOREAN_DICT_PATH, 'wb') as f:
                f.write(resp.read())
        except Exception as e:
            print(f"[!] Erro ao baixar dicionário coreano PP-OCRv5: {e}")
    if os.path.exists(KOREAN_REC_PATH) and os.path.exists(KOREAN_DICT_PATH):
        _onnx_ensure_character_metadata(KOREAN_REC_PATH, KOREAN_DICT_PATH)
        return True
    return False

def _detect_rapidocr_api_style():
    """Detecta se RapidOCR instalado usa API 1.4.x (use_cls) ou 1.2.x/1.3.x (use_angle_cls)."""
    try:
        import rapidocr_onnxruntime
        cfg_path = os.path.join(os.path.dirname(rapidocr_onnxruntime.__file__), "config.yaml")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as cf:
                txt = cf.read()
            if "use_cls:" in txt:
                return "1.4"
            if "use_angle_cls:" in txt:
                return "1.2"
    except Exception:
        pass
    return "1.2"

def get_rapidocr_engine(is_korean=False):
    """Instancia o RapidOCR Coreano (PP-OCRv5 sem rotação de ângulo que inverte Hangul) ou o padrão universal."""
    if is_korean:
        if not ensure_korean_ocr_model():
            raise RuntimeError("Modelo de OCR Coreano (PP-OCRv5) indisponível em models/korean/.")
        api_style = _detect_rapidocr_api_style()
        try:
            if api_style == "1.4":
                return RapidOCR(
                    use_cls=False,
                    det_model_path=None,
                    det_box_thresh=0.45,
                    text_score=0.35,
                    width_height_ratio=16,
                    min_height=15,
                    rec_model_path=KOREAN_REC_PATH,
                    rec_keys_path=KOREAN_DICT_PATH,
                    rec_img_shape=[3, 48, 320],
                )
            return RapidOCR(
                use_angle_cls=False,
                det_model_path=None,
                det_box_thresh=0.35,
                det_thresh=0.24,
                det_unclip_ratio=1.72,
                text_score=0.35,
                width_height_ratio=16,
                min_height=15,
                rec_model_path=KOREAN_REC_PATH,
                rec_img_shape=[3, 48, 320],
            )
        except Exception as e:
            print(f"[!] Aviso ao iniciar RapidOCR Coreano com parâmetros customizados ({e}); tentando modo seguro sem angle_cls...")
            safe_kw = {"use_cls": False, "rec_model_path": KOREAN_REC_PATH, "rec_keys_path": KOREAN_DICT_PATH} if api_style == "1.4" else {"use_angle_cls": False, "rec_model_path": KOREAN_REC_PATH}
            return RapidOCR(**safe_kw)
    return RapidOCR()

def is_mokuro_available():
    """Verifica se o Mokuro está disponível no ambiente sem carregar modelos pesados."""
    import shutil, importlib.util
    if shutil.which("mokuro") is not None:
        return True
    try:
        if importlib.util.find_spec("mokuro") is not None:
            return True
    except Exception:
        pass
    return False

def detect_manga_language_and_engine(manga_dir):
    """
    Detecta automaticamente o idioma da obra e seleciona o motor ideal:
    - 'korean': Manhwa / Coreano (Hangul) -> Usa RapidOCR Coreano (NUNCA usa Mokuro)
    - 'mokuro': Mangá Japonês (Kanji/Kana) -> Usa Mokuro (manga-ocr) se disponível
    - 'rapidocr': Ocidental / Inglês / Espanhol / Chinês -> Usa RapidOCR padrão
    """
    folder_name = os.path.basename(manga_dir)
    folder_lower = folder_name.lower()

    latin_tags = [
        r'\[(english|ingl[êe]s|ingles|en)\]', r'\((english|ingl[êe]s|ingles|en)\)',
        r'\[(spanish|espa[ñn]ol|espanhol|es)\]', r'\((spanish|espa[ñn]ol|espanhol|es)\)',
        r'\[(portugu[êe]s|portugues|pt|pt-br)\]', r'\((portugu[êe]s|portugues|pt|pt-br)\)',
        r'\[(french|fran[çc]ais|fr)\]', r'\((french|fran[çc]ais|fr)\)',
        r'\[(german|deutsch|de)\]', r'\((german|deutsch|de)\)',
        r'\[(italian|italiano|it)\]', r'\((italian|italiano|it)\)',
        r'\[(russian|russo|ru)\]', r'\((russian|russo|ru)\)',
    ]
    has_latin_tag = any(re.search(tag_pattern, folder_name, re.IGNORECASE) for tag_pattern in latin_tags)
    has_hangul_in_title = bool(re.search(r'[\uac00-\ud7af]', folder_name))
    has_korean_tag = bool(
        re.search(r'\[(korean|coreano|kr|ko)\]', folder_name, re.IGNORECASE)
        or re.search(r'\((korean|coreano|kr|ko)\)', folder_name, re.IGNORECASE)
        or "manhwa" in folder_lower
        or "webtoon" in folder_lower
    )
    has_jp_in_title = bool(
        re.search(r'[\u3040-\u30ff]', folder_name)
        or re.search(r'\[(japanese|japon[êe]s|japones|raw|jp)\]', folder_name, re.IGNORECASE)
    )

    has_title_conflict = has_latin_tag and (has_hangul_in_title or has_korean_tag)

    # 1. Título puramente ocidental sem Hangul/Coreano/Japonês conflitante
    if has_latin_tag and not has_title_conflict and not has_jp_in_title:
        print(f"[+] Idioma identificado pela tag no título: OCIDENTAL/LATINO ({folder_name}) -> Usando RapidOCR Universal.")
        return "rapidocr"

    # 2. Título Coreano explícito sem tag ocidental conflitante
    if (has_hangul_in_title or has_korean_tag) and not has_title_conflict:
        print("[+] Idioma detectado pelo título: COREANO (Hangul) -> Usando RapidOCR Coreano.")
        return "korean"

    # 3. Título explicitamente Japonês
    if has_jp_in_title and not has_latin_tag and not has_hangul_in_title:
        if is_mokuro_available():
            return "mokuro"
        print("[i] Mangá com caracteres japoneses no título, mas Mokuro não está disponível. Usando RapidOCR Universal.")
        return "rapidocr"

    # 4. Amostra páginas internas para decidir sem margem de erro (inclusive em títulos com múltiplos idiomas)
    try:
        img_files = get_image_files(manga_dir)
        if not img_files:
            if has_hangul_in_title or has_korean_tag:
                return "korean"
            return "mokuro" if is_mokuro_available() else "rapidocr"

        if len(img_files) <= 3:
            sample_indices = list(range(len(img_files)))
        else:
            sample_indices = list(dict.fromkeys([
                min(max(1, len(img_files) // 5), len(img_files) - 1),
                min(len(img_files) // 2, len(img_files) - 1),
                min((3 * len(img_files)) // 4, len(img_files) - 1)
            ]))

        engine = RapidOCR()
        combined_texts = []
        sample_imgs = []
        zh_high_chars = 0
        for s_idx in sample_indices:
            src_path = img_files[s_idx]
            try:
                with open(src_path, "rb") as f:
                    img_array = np.asarray(bytearray(f.read()), dtype=np.uint8)
                    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if img_cv is None:
                    continue
                sample_imgs.append(img_cv)
                res, _ = engine(img_cv)
                if res:
                    combined_texts.append(" ".join([box[1] for box in res]))
                    for zd in res:
                        txt_z = str(zd[1] or "").strip()
                        sc_z = float(zd[2]) if len(zd) > 2 else 1.0
                        if sc_z >= 0.72:
                            zh_high_chars += len(re.findall(r'[\u4e00-\u9fff]', txt_z))
            except Exception:
                continue

        full_sample_text = " ".join(combined_texts)
        korean_count = len(re.findall(r'[\uac00-\ud7af]', full_sample_text))
        japanese_count = len(re.findall(r'[\u3040-\u30ff]', full_sample_text))
        chinese_count = len(re.findall(r'[\u4e00-\u9fff]', full_sample_text))
        latin_count = len(re.findall(r'[a-zA-Z]', full_sample_text))

        # Checa texto latino claro primeiro (exceto quando não houve latim substancial ou há Hangul no título pedindo confirmação)
        if latin_count > 25 and latin_count > (japanese_count * 3) and chinese_count <= 2 and korean_count == 0 and not has_hangul_in_title:
            spanish_matches = len(re.findall(r'\b(el|la|los|las|de|en|un|una|por|con|para|del|al|que|es|como|mas|pero|cuando|muchas|gracias|joyas?|tiendas?)\b', full_sample_text, re.IGNORECASE))
            if spanish_matches >= 3 or any(w in folder_lower for w in ["vengan", "espanol", "español", "spanish", "capitulo"]):
                print("[+] Obra identificada com texto em ESPANHOL -> Ativando tradução especializada Espanhol -> PT-BR.")
            else:
                print("[+] Obra identificada com alfabeto LATINO (Inglês/Ocidental) -> Usando RapidOCR.")
            return "rapidocr"

        # Sonda com motor Coreano PP-OCRv5 para distinguir Manhwa (Hangul) vs Manhua (Chinês) mesmo sem tag ou com título conflitante
        if japanese_count <= 2 and sample_imgs and ensure_korean_ocr_model():
            try:
                ko_engine = get_rapidocr_engine(is_korean=True)
                ko_high_chars = 0
                ko_all_chars = 0
                for img_cv in sample_imgs:
                    k_res, _ = ko_engine(img_cv)
                    if k_res:
                        for kd in k_res:
                            txt_k = str(kd[1] or "").strip()
                            sc_k = float(kd[2]) if len(kd) > 2 else 1.0
                            h_n = len(re.findall(r'[\uac00-\ud7af]', txt_k))
                            ko_all_chars += h_n
                            if sc_k >= 0.65:
                                ko_high_chars += h_n

                if ko_high_chars >= 6 and (ko_high_chars > zh_high_chars or has_hangul_in_title or has_korean_tag):
                    print(f"[+] Obra identificada pelas páginas como COREANO (Hangul alta conf.: {ko_high_chars} vs Hanzi alta conf.: {zh_high_chars}) -> Usando RapidOCR Coreano.")
                    return "korean"
                if ko_all_chars >= 12 and zh_high_chars < 6 and latin_count < 15:
                    print(f"[+] Obra identificada pelas páginas como COREANO (Hangul: {ko_all_chars}) -> Usando RapidOCR Coreano.")
                    return "korean"
            except Exception:
                pass

        if korean_count > 0:
            return "korean"
        if japanese_count == 0 and chinese_count >= 3:
            print("[+] Obra identificada como CHINÊS (Hanzi) sem kana -> Usando RapidOCR Universal.")
            return "rapidocr"
        if latin_count > 10 and latin_count > (japanese_count * 2):
            spanish_matches = len(re.findall(r'\b(el|la|los|las|de|en|un|una|por|con|para|del|al|que|es|como|mas|pero|cuando|muchas|gracias|joyas?|tiendas?)\b', full_sample_text, re.IGNORECASE))
            if spanish_matches >= 3 or any(w in folder_lower for w in ["vengan", "espanol", "español", "spanish", "capitulo"]):
                print("[+] Obra identificada com texto em ESPANHOL -> Ativando tradução especializada Espanhol -> PT-BR.")
            else:
                print("[+] Obra identificada com alfabeto LATINO (Inglês/Ocidental) -> Usando RapidOCR.")
            return "rapidocr"

        if is_mokuro_available():
            return "mokuro"
        print("[i] Amostra sem Mokuro instalado no ambiente. Usando RapidOCR Universal com suporte multilíngue.")
        return "rapidocr"
    except Exception:
        if has_hangul_in_title or has_korean_tag:
            return "korean"
        return "mokuro" if is_mokuro_available() else "rapidocr"

def check_needs_rapidocr(manga_dir):
    """Analisa imagens para determinar se o conteúdo é ocidental/latino ou coreano."""
    engine = detect_manga_language_and_engine(manga_dir)
    return engine != "mokuro"

def is_ocr_noise(text, score, is_korean=False):
    """Filtra ruídos de OCR para não apagar detalhes de arte ou fundos (com preservação para Hangul de 1 caractere)."""
    t = text.strip()
    if not t:
        return True
    try:
        sc = float(score)
    except Exception:
        sc = 1.0
    if sc < (0.40 if is_korean else 0.42):
        return True
    has_letters = bool(re.search(r'[a-zA-Z\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]', t))
    if not has_letters and sc < (0.85 if is_korean else 0.75):
        return True
    if is_korean:
        has_ko_cjk = bool(re.search(r'[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]', t))
        if has_ko_cjk:
            if len(t) <= 1 and sc < 0.42:
                return True
        else:
            if len(t) <= 2 and t.upper() not in {"OK", "TV", "NO", "HI", "SO", "OH", "AH"} and sc < 0.78:
                return True
    else:
        if len(t) <= 1 and sc < 0.60:
            return True
    if len(set(t)) <= 2 and len(t) >= 4 and sc < 0.75:
        return True
    return False

def generate_rapidocr_json(manga_dir, output_json_path, is_korean=False, progress_cb=None):
    """Extrai textos usando RapidOCR (PP-OCRv5 Coreano em Hangul ou Universal com detecção de textos coloridos)."""
    img_files = get_image_files(manga_dir)
    if not img_files:
        print(f"[!] Erro crítico: Nenhuma imagem válida encontrada em '{manga_dir}'.")
        return False
    
    engine = get_rapidocr_engine(is_korean=is_korean)
    pages = []
    
    desc_msg = "OCR Coreano PP-OCRv5 (Hangul)" if is_korean else "OCR Universal (RapidOCR)"
    print(f"[*] Extraindo textos usando {desc_msg}...")
    for idx, img_path in enumerate(tqdm(img_files, desc="OCR Pages")):
        if progress_cb:
            try:
                progress_cb("ocr", idx + 1, len(img_files), f"Lendo textos (OCR): Página {idx + 1} de {len(img_files)}")
            except Exception:
                pass
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
                
                if is_ocr_noise(text, score, is_korean=is_korean):
                    continue
                    
                xs = [p[0] for p in coords]
                ys = [p[1] for p in coords]
                
                clean_ocr_text = text.strip()
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
        
    mokuro_data = {
        "version": "rapidocr_korean" if is_korean else "rapidocr",
        "ocr_model": "ppocr_v5_korean" if is_korean else "rapidocr_default",
        "pages": pages
    }
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(mokuro_data, f, ensure_ascii=False)

GROQ_DEFAULT_VISION_MODELS = [
    "qwen/qwen3.8-27b",
]

OPENROUTER_DEFAULT_VISION_MODELS = [
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
]

GEMINI_DEFAULT_VISION_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

def is_ollama_vision_model_name(name):
    """Retorna True se o nome do modelo Ollama indica suporte multimodal/visão."""
    n = str(name or "").strip().lower()
    if not n:
        return False
    if n.startswith("gemma3:1b") or ":1b" in n and "gemma3" in n:
        return False
    explicit_tokens = (
        "qwen3-vl", "qwen2.5vl", "qwen2.5-vl", "qwen2-vl",
        "llama3.2-vision", "minicpm-v", "internvl", "llava",
        "moondream", "pixtral", "bakllava", "gemma3"
    )
    if any(tok in n for tok in explicit_tokens):
        return True
    if "vision" in n or re.search(r'(?:^|[-_/:])vl(?:$|[-_/:])', n):
        return True
    return False

def _box_iou_xyxy(b1, b2):
    ix0 = max(b1[0], b2[0])
    iy0 = max(b1[1], b2[1])
    ix1 = min(b1[2], b2[2])
    iy1 = min(b1[3], b2[3])
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    a1 = max(1.0, (b1[2] - b1[0]) * (b1[3] - b1[1]))
    a2 = max(1.0, (b2[2] - b2[0]) * (b2[3] - b2[1]))
    return inter / max(1.0, a1 + a2 - inter)

def _run_text_detector_only(det_engine, img_arr):
    """Executa apenas a camada de detecção geométrica (DBNet) sobre img_arr, retornando lista de boxes."""
    det_fn = getattr(det_engine, "text_detector", None) or getattr(det_engine, "text_det", None)
    if callable(det_fn):
        try:
            det_out = det_fn(img_arr)
            if isinstance(det_out, tuple):
                dt_boxes = det_out[0]
            elif hasattr(det_out, "boxes"):
                dt_boxes = det_out.boxes
            else:
                dt_boxes = det_out
            return list(dt_boxes) if dt_boxes is not None else []
        except Exception:
            pass
    try:
        res, _ = det_engine(img_arr)
        return [item[0] for item in res if item and len(item) >= 1] if res else []
    except Exception:
        return []

def _detect_text_boxes_for_vision(det_engine, img_cv):
    """Localiza e agrupa balões de diálogo geometricamente usando DBNet local (inclui textos coloridos)."""
    if img_cv is None:
        return []

    raw_quads = _run_text_detector_only(det_engine, img_cv)
    boxes_xyxy = []
    for quad in raw_quads:
        try:
            xs = [float(p[0]) for p in quad]
            ys = [float(p[1]) for p in quad]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            if (x1 - x0) >= 5.0 and (y1 - y0) >= 5.0 and ((x1 - x0) * (y1 - y0)) >= 48.0:
                boxes_xyxy.append([x0, y0, x1, y1])
        except Exception:
            continue

    if len(boxes_xyxy) < 2:
        try:
            min_ch = img_cv.min(axis=2)
            min_bgr = cv2.cvtColor(min_ch, cv2.COLOR_GRAY2BGR)
            alt_quads = _run_text_detector_only(det_engine, min_bgr)
            for quad in alt_quads:
                try:
                    xs = [float(p[0]) for p in quad]
                    ys = [float(p[1]) for p in quad]
                    ab = [min(xs), min(ys), max(xs), max(ys)]
                    if (ab[2] - ab[0]) < 5.0 or (ab[3] - ab[1]) < 5.0 or ((ab[2] - ab[0]) * (ab[3] - ab[1])) < 48.0:
                        continue
                    if not any(_box_iou_xyxy(ab, eb) >= 0.45 for eb in boxes_xyxy):
                        boxes_xyxy.append(ab)
                except Exception:
                    continue
        except Exception:
            pass

    if not boxes_xyxy:
        return []

    blocks_for_grouping = [{"box": b, "text": "T"} for b in boxes_xyxy]
    grouped = smart_group_bubbles(blocks_for_grouping)
    ih, iw = img_cv.shape[:2]
    ref_w = max(1.0, float(min(iw, ih)))
    min_side_thr = max(18.0, 0.0155 * ref_w)
    min_area_thr = max(360.0, (0.0155 * ref_w) ** 2)
    filtered_grouped = []
    for b in grouped:
        bx0, by0, bx1, by1 = b["box"]
        bw = max(0.0, float(bx1 - bx0))
        bh = max(0.0, float(by1 - by0))
        rbs = b.get("raw_boxes") or [b["box"]]
        if len(rbs) <= 1 and (max(bw, bh) < min_side_thr or (bw * bh) < min_area_thr):
            continue
        filtered_grouped.append(b)
    grouped = filtered_grouped
    grouped.sort(key=lambda b: (int(b["box"][1] // 100), b["box"][0]))
    return grouped

def _render_vision_annotated_image(img_cv, grouped_subset, max_side=1600):
    """Desenha caixas numeradas [id] sem cobrir o texto interno e codifica em JPEG base64."""
    canvas = img_cv.copy()
    ih, iw = canvas.shape[:2]
    palette_bgr = [
        (36, 28, 237),   # Vermelho vivo
        (235, 110, 20),  # Azul forte
        (60, 155, 10),   # Verde escuro
        (205, 45, 165),  # Roxo
        (0, 125, 230),   # Laranja
    ]
    border_th = max(2, int(round(max(iw, ih) / 520.0)))
    font_scale = max(0.55, min(0.95, max(iw, ih) / 1450.0))
    font_th = max(1, int(round(font_scale * 2.2)))

    for idx, item in enumerate(grouped_subset):
        box_id = item["vision_id"]
        box = item["box"]
        col = palette_bgr[idx % len(palette_bgr)]
        x0 = max(0, min(iw - 1, int(round(box[0]))))
        y0 = max(0, min(ih - 1, int(round(box[1]))))
        x1 = max(x0 + 1, min(iw - 1, int(round(box[2]))))
        y1 = max(y0 + 1, min(ih - 1, int(round(box[3]))))

        # Expande levemente a borda do retângulo para não pisar nos caracteres das extremidades
        rx0 = max(0, x0 - 2)
        ry0 = max(0, y0 - 2)
        rx1 = min(iw - 1, x1 + 2)
        ry1 = min(ih - 1, y1 + 2)
        cv2.rectangle(canvas, (rx0, ry0), (rx1, ry1), col, border_th)

        label = f"[{box_id}]"
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_th)
        pad_px = 4
        pill_w = tw + pad_px * 2
        pill_h = th + baseline + pad_px

        # Prefere posicionar a etiqueta fora do retângulo (acima do canto superior esquerdo)
        if ry0 >= pill_h + 2:
            px0 = rx0
            py0 = ry0 - pill_h
        elif ry1 + pill_h + 2 < ih:
            px0 = rx0
            py0 = ry1 + 2
        else:
            px0 = rx0
            py0 = max(0, ry0)

        px0 = max(0, min(iw - pill_w - 1, px0))
        px1 = min(iw - 1, px0 + pill_w)
        py1 = min(ih - 1, py0 + pill_h)
        cv2.rectangle(canvas, (px0, py0), (px1, py1), col, -1)
        cv2.putText(
            canvas,
            label,
            (px0 + pad_px, py1 - baseline - 1),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            font_th,
            cv2.LINE_AA
        )

    cur_max = max(iw, ih)
    if cur_max > max_side and max_side > 0:
        scale = float(max_side) / float(cur_max)
        new_w = max(1, int(round(iw * scale)))
        new_h = max(1, int(round(ih * scale)))
        canvas = cv2.resize(canvas, (new_w, new_h), interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise RuntimeError("Falha ao codificar imagem anotada para IA Vision.")
    return base64.b64encode(buf.tobytes()).decode("ascii")

def _parse_vision_ocr_json(raw_text, expected_ids):
    """Extrai e limpa dicionário {"id": "texto original"} da resposta de um VLM."""
    cleaned = _strip_think_tags(raw_text or "")
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned.strip())

    parsed = {}
    if cleaned:
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict):
                parsed = obj
        except Exception:
            m_obj = re.search(r'\{[\s\S]*\}', cleaned)
            if m_obj:
                try:
                    obj = json.loads(m_obj.group(0))
                    if isinstance(obj, dict):
                        parsed = obj
                except Exception:
                    pass
            if not parsed:
                for m_kv in re.finditer(r'"(\d+)"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned):
                    k_s, v_raw = m_kv.group(1), m_kv.group(2)
                    try:
                        parsed[k_s] = json.loads(f'"{v_raw}"')
                    except Exception:
                        parsed[k_s] = v_raw.replace('\\"', '"').replace("\\n", " ")

    out = {}
    for eid in expected_ids:
        k_str = str(eid)
        val = parsed.get(k_str, parsed.get(int(eid) if str(eid).isdigit() else eid, ""))
        txt = str(val if val is not None else "").strip()
        txt = re.sub(rf'^\[{re.escape(k_str)}\]\s*', '', txt)
        if re.search(r'[\u4e00-\u9fff\u3040-\u30ff]', txt) and not re.search(r'[\uac00-\ud7af]', txt):
            txt = re.sub(r'\s*\n+\s*', '', txt)
        else:
            txt = re.sub(r'\s*\n+\s*', ' ', txt)
        out[k_str] = txt.strip()
    return out

class VisionSafetyBlockedError(RuntimeError):
    """Indica recusa por filtro de conteúdo sensível no provedor Vision."""

def query_gemini_vision(b64_img, prompt, cfg, engine_opts=None, timeout=60):
    """Executa OCR via Google Gemini Vision REST API com rotação de chaves e segurança ajustada."""
    engine_opts = engine_opts if engine_opts is not None else {}
    raw_keys = list(cfg.get("gemini_api_keys") or [])
    if cfg.get("gemini_api_key") and cfg.get("gemini_api_key") not in raw_keys:
        raw_keys.insert(0, cfg.get("gemini_api_key"))
    key_pool = [
        str(k).strip() for k in raw_keys
        if str(k or "").strip() and not str(k).strip().startswith(("gsk_", "sk-or-"))
    ]
    if not key_pool:
        raise ValueError("Nenhuma chave Google Gemini cadastrada.")

    exhausted_gem_keys = engine_opts.setdefault("gemini_exhausted_keys", set())
    exhausted_gem_models = engine_opts.setdefault("gemini_exhausted_models", set())

    cand_models = []
    for m in [cfg.get("gemini_model")] + GEMINI_DEFAULT_VISION_MODELS:
        m_s = str(m or "").strip()
        if m_s and m_s not in cand_models and m_s not in exhausted_gem_models:
            cand_models.append(m_s)
    if not cand_models:
        raise RuntimeError("Todos os modelos Google Gemini configurados falharam.")

    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
    ]

    last_err = None
    for idx_k, api_key in enumerate(key_pool):
        if idx_k in exhausted_gem_keys:
            continue
        for m_name in cand_models:
            if m_name in exhausted_gem_models:
                continue
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"
            use_json_mime = True
            active_safety = list(safety_settings)
            for _sub in range(2):
                gen_cfg = {"temperature": 0.0, "maxOutputTokens": 2048}
                if use_json_mime:
                    gen_cfg["responseMimeType"] = "application/json"
                payload = {
                    "contents": [{
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}}
                        ]
                    }],
                    "safetySettings": active_safety,
                    "generationConfig": gen_cfg
                }
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    pfb = data.get("promptFeedback") or {}
                    if pfb.get("blockReason"):
                        raise VisionSafetyBlockedError(f"Gemini bloqueou a página ({pfb.get('blockReason')}).")
                    cands = data.get("candidates") or []
                    if not cands:
                        raise VisionSafetyBlockedError("Gemini não retornou candidatos para esta página.")
                    fin_reason = str(cands[0].get("finishReason", "")).upper()
                    if fin_reason in ("SAFETY", "PROHIBITED_CONTENT", "IMAGE_SAFETY", "RECITATION"):
                        raise VisionSafetyBlockedError(f"Gemini bloqueou resposta ({fin_reason}).")
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    txt_out = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
                    if txt_out:
                        return txt_out
                    raise RuntimeError("Gemini retornou resposta vazia.")
                except VisionSafetyBlockedError:
                    raise
                except urllib.error.HTTPError as e:
                    err_body = ""
                    try:
                        err_body = e.read().decode("utf-8", errors="ignore")
                    except Exception:
                        pass
                    err_low = err_body.lower()
                    last_err = e
                    if e.code in (401, 403):
                        exhausted_gem_keys.add(idx_k)
                        break
                    if e.code == 429:
                        if any(tok in err_low for tok in ("quota", "exceeded", "daily", "limit")):
                            break
                        time.sleep(1.5)
                        continue
                    if e.code == 400 and (use_json_mime or len(active_safety) == 5):
                        if "responsemimetype" in err_low or "json" in err_low:
                            use_json_mime = False
                        if "civic_integrity" in err_low:
                            active_safety = [s for s in active_safety if s["category"] != "HARM_CATEGORY_CIVIC_INTEGRITY"]
                        if not use_json_mime or len(active_safety) < 5:
                            continue
                    if e.code == 404:
                        exhausted_gem_models.add(m_name)
                        break
                    break
                except Exception as e:
                    last_err = e
                    break
            if idx_k in exhausted_gem_keys:
                break

    if last_err:
        raise last_err
    raise RuntimeError("Falha ao consultar Google Gemini Vision.")

def _parse_ratelimit_duration(raw_val, default=15.0):
    """Converte strings de reset/retry-after da API (ex: '18.15s', '1m12.4s', '350ms') em segundos."""
    if raw_val is None:
        return default
    s = str(raw_val).strip().lower()
    if not s:
        return default
    try:
        return float(s)
    except Exception:
        pass
    total = 0.0
    matched = False
    for pattern, mult in ((r'(\d+(?:\.\d+)?)h', 3600.0), (r'(\d+(?:\.\d+)?)m(?!s)', 60.0), (r'(\d+(?:\.\d+)?)ms', 0.001), (r'(\d+(?:\.\d+)?)s', 1.0)):
        m = re.search(pattern, s)
        if m:
            total += float(m.group(1)) * mult
            matched = True
    return total if matched and total > 0.0 else default

def query_groq_vision(b64_img, prompt, cfg, engine_opts=None, max_tokens=720, timeout=45):
    """
    Executa OCR via Groq Vision (qwen/qwen3.8-27b) com rotação round-robin entre todas as chaves,
    respeito estrito ao limite OTPM (<=850 tokens) e controle de janela TPM/RPM.
    """
    engine_opts = engine_opts if engine_opts is not None else {}
    raw_pool = list(cfg.get("groq_api_keys") or [])
    if cfg.get("groq_api_key") and cfg.get("groq_api_key") not in raw_pool:
        raw_pool.insert(0, cfg.get("groq_api_key"))
    key_pool = [
        str(k).strip() for k in raw_pool
        if str(k or "").strip() and not str(k or "").strip().startswith(("sk-or-", "AIza"))
    ]
    if not key_pool:
        raise ValueError("Nenhuma chave Groq válida configurada para Vision.")

    exhausted_keys = engine_opts.setdefault("groq_vision_exhausted_keys", set())
    exhausted_models = engine_opts.setdefault("groq_vision_exhausted_models", set())
    cooldown_map = engine_opts.setdefault("groq_vision_cooldowns", {})

    cfg_groq_m = str(cfg.get("groq_model", "") or "").strip()
    cand_models = [cfg.get("groq_vision_model")]
    if "qwen3.8" in cfg_groq_m.lower():
        cand_models.append(cfg_groq_m)
    cand_models.extend(GROQ_DEFAULT_VISION_MODELS)

    vision_models = []
    for m in cand_models:
        m_s = str(m or "").strip()
        if m_s and m_s not in vision_models and m_s not in exhausted_models:
            vision_models.append(m_s)
    if not vision_models:
        raise RuntimeError("Nenhum modelo Groq Vision disponível.")

    eff_max_tokens = max(250, min(850, int(max_tokens or 720)))
    url = "https://api.groq.com/openai/v1/chat/completions"
    last_err = None
    n_keys = len(key_pool)

    for _round in range(2):
        now = time.time()
        avail_indices = [i for i in range(n_keys) if i not in exhausted_keys]
        if not avail_indices:
            break

        rr_start = int(engine_opts.get("groq_vision_rr_idx", 0) or 0) % n_keys
        ordered_indices = [(rr_start + off) % n_keys for off in range(n_keys)]
        ordered_indices = [i for i in ordered_indices if i not in exhausted_keys]

        made_attempt = False
        for idx_k in ordered_indices:
            api_key = key_pool[idx_k]
            for m_name in vision_models:
                if m_name in exhausted_models:
                    continue
                cd_until = cooldown_map.get(f"{idx_k}:{m_name}", 0.0)
                if cd_until > time.time():
                    continue

                made_attempt = True
                use_reasoning_effort = "qwen3" in m_name.lower()
                for _sub in range(2):
                    payload = {
                        "model": m_name,
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                            ]
                        }],
                        "temperature": 0.0,
                        "max_tokens": eff_max_tokens
                    }
                    if use_reasoning_effort:
                        payload["reasoning_effort"] = "none"

                    req = urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                        }
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=timeout) as resp:
                            res = json.loads(resp.read().decode("utf-8"))
                            rem_tok_h = resp.headers.get("x-ratelimit-remaining-tokens")
                            rst_tok_h = resp.headers.get("x-ratelimit-reset-tokens")
                        if rem_tok_h is not None:
                            try:
                                if int(rem_tok_h) < 2300:
                                    cd_sec = min(max(_parse_ratelimit_duration(rst_tok_h, 18.0), 4.0), 62.0)
                                    cooldown_map[f"{idx_k}:{m_name}"] = time.time() + cd_sec
                                else:
                                    cooldown_map.pop(f"{idx_k}:{m_name}", None)
                            except Exception:
                                pass
                        choices = res.get("choices") or []
                        ch0 = choices[0] if choices and isinstance(choices[0], dict) else {}
                        fin_reason = str(ch0.get("finish_reason", "")).lower()
                        if fin_reason in ("content_filter", "safety"):
                            raise VisionSafetyBlockedError(f"Groq Vision bloqueou resposta ({fin_reason}).")
                        msg = ch0.get("message") or {}
                        raw_out = _strip_think_tags(msg.get("content") or "")
                        engine_opts["groq_vision_rr_idx"] = (idx_k + 1) % n_keys
                        if raw_out.strip():
                            return raw_out.strip()
                        last_err = RuntimeError(f"Groq Vision '{m_name}' retornou conteúdo vazio.")
                        break
                    except VisionSafetyBlockedError:
                        raise
                    except urllib.error.HTTPError as e:
                        err_body = ""
                        try:
                            err_body = e.read().decode("utf-8", errors="ignore")
                        except Exception:
                            pass
                        err_low = err_body.lower()
                        last_err = e
                        if e.code in (401, 403):
                            exhausted_keys.add(idx_k)
                            break
                        if e.code == 429:
                            is_daily = any(tok in err_low for tok in ("tokens per day", "requests per day", " tpd", " rpd"))
                            if is_daily:
                                exhausted_keys.add(idx_k)
                                break
                            wait_sec = 16.0
                            try:
                                retry_h = e.headers.get("retry-after") or e.headers.get("x-ratelimit-reset-tokens")
                                if retry_h:
                                    wait_sec = _parse_ratelimit_duration(retry_h, 16.0) + 0.5
                                else:
                                    m_retry = re.search(r'try again in\s*([^\s.,;]+)', err_low)
                                    if m_retry:
                                        wait_sec = _parse_ratelimit_duration(m_retry.group(1), 16.0) + 0.5
                            except Exception:
                                pass
                            cd_sec = min(max(wait_sec, 4.0), 62.0)
                            cooldown_map[f"{idx_k}:{m_name}"] = time.time() + cd_sec
                            break
                        if e.code == 400:
                            if use_reasoning_effort and "reasoning_effort" in err_low:
                                use_reasoning_effort = False
                                continue
                            if any(tok in err_low for tok in ("safety", "policy", "prohibited", "nsfw")):
                                raise VisionSafetyBlockedError(f"Groq Vision bloqueou imagem (HTTP 400).")
                            if any(tok in err_low for tok in ("image", "multimodal", "vision", "model")):
                                exhausted_models.add(m_name)
                            break
                        if e.code == 404:
                            exhausted_models.add(m_name)
                            break
                        cooldown_map[f"{idx_k}:{m_name}"] = time.time() + 8.0
                        break
                    except Exception as e:
                        last_err = e
                        cooldown_map[f"{idx_k}:{m_name}"] = time.time() + 6.0
                        break
                if idx_k in exhausted_keys:
                    break

        rem_keys = [i for i in range(n_keys) if i not in exhausted_keys]
        if not rem_keys or not vision_models or all(m in exhausted_models for m in vision_models):
            break

        # Se todas as chaves restantes entraram em janela curta de TPM, aguarda a liberação da próxima janela
        soonest_until = None
        now = time.time()
        for idx_k in rem_keys:
            for m_name in vision_models:
                if m_name in exhausted_models:
                    continue
                t_cd = cooldown_map.get(f"{idx_k}:{m_name}", 0.0)
                if soonest_until is None or t_cd < soonest_until:
                    soonest_until = t_cd
        if soonest_until is not None:
            wait_s = max(1.0, soonest_until - now) + 0.5
            if wait_s <= 64.0 and _round == 0:
                print(f"[*] Groq Vision: janela TPM em pausa nas {len(rem_keys)} chave(s). Aguardando {wait_s:.1f}s...")
                time.sleep(wait_s)
                now_after = time.time()
                for ck in list(cooldown_map.keys()):
                    if cooldown_map[ck] <= now_after + 0.5:
                        cooldown_map.pop(ck, None)
                continue
        if not made_attempt:
            break

    if last_err:
        raise last_err
    raise RuntimeError("Falha ao consultar Groq Vision.")

def query_openrouter_vision(b64_img, prompt, cfg, engine_opts=None, timeout=35):
    """Executa OCR via OpenRouter Vision com cascata de modelos :free e rotação de chaves (sem gsk_)."""
    engine_opts = engine_opts if engine_opts is not None else {}
    raw_pool = list(cfg.get("openrouter_api_keys") or [])
    if cfg.get("openrouter_api_key") and cfg.get("openrouter_api_key") not in raw_pool:
        raw_pool.insert(0, cfg.get("openrouter_api_key"))
    key_pool = [
        str(k).strip() for k in raw_pool
        if str(k or "").strip() and not str(k).strip().startswith("gsk_")
    ]
    if not key_pool:
        raise ValueError("Nenhuma chave OpenRouter válida para Vision.")

    exhausted_or_keys = engine_opts.setdefault("openrouter_vision_exhausted_keys", set())
    exhausted_or_models = engine_opts.setdefault("openrouter_vision_exhausted_models", set())

    vision_models = []
    for m in [cfg.get("openrouter_vision_model")] + OPENROUTER_DEFAULT_VISION_MODELS:
        m_s = str(m or "").strip()
        if m_s and m_s not in vision_models and m_s not in exhausted_or_models:
            vision_models.append(m_s)
    if not vision_models:
        raise RuntimeError("Todos os modelos Vision do OpenRouter estão temporariamente indisponíveis.")

    url = "https://openrouter.ai/api/v1/chat/completions"
    last_err = None
    for idx_k, api_key in enumerate(key_pool):
        if idx_k in exhausted_or_keys:
            continue
        for m_name in vision_models:
            if m_name in exhausted_or_models:
                continue
            m_low = m_name.lower()
            use_reasoning_param = any(tok in m_low for tok in ("reasoning", "super-vl", "3-note"))
            for _sub in range(2):
                payload = {
                    "model": m_name,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                        ]
                    }],
                    "temperature": 0.0,
                    "max_tokens": 2000
                }
                if use_reasoning_param:
                    payload["reasoning"] = {"enabled": False}
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/Jos9011/SKILL-TRADUCAO-MANGA",
                        "X-Title": "Manga Translator PT-BR"
                    }
                )
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                    choices = res.get("choices") or []
                    msg = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
                    raw_out = _strip_think_tags(msg.get("content") or "")
                    if raw_out.strip():
                        return raw_out.strip()
                    last_err = RuntimeError(f"OpenRouter Vision '{m_name}' retornou conteúdo vazio.")
                    break
                except urllib.error.HTTPError as e:
                    err_body = ""
                    try:
                        err_body = e.read().decode("utf-8", errors="ignore")
                    except Exception:
                        pass
                    err_low = err_body.lower()
                    last_err = e
                    if e.code in (401, 403) or "free-models-per-day" in err_low:
                        exhausted_or_keys.add(idx_k)
                        break
                    if e.code == 400:
                        if use_reasoning_param and "reasoning" in err_low:
                            use_reasoning_param = False
                            continue
                        exhausted_or_models.add(m_name)
                        break
                    if e.code == 404:
                        exhausted_or_models.add(m_name)
                        break
                    if e.code == 429:
                        # Upstream model rate-limit: tenta próximo modelo na mesma chave antes de descartar a chave
                        if any(tok in err_low for tok in ("upstream", "temporarily rate-limited", "provider")):
                            break
                        exhausted_or_keys.add(idx_k)
                        break
                    break
                except Exception as e:
                    last_err = e
                    break
            if idx_k in exhausted_or_keys:
                break

    if last_err:
        raise last_err
    raise RuntimeError("Falha ao consultar OpenRouter Vision.")

def check_ollama_vision_available(host="http://localhost:11434", custom_model=None):
    """Detecta modelo de visão instalado no Ollama sem disparar download nem aquecimento pesado."""
    host = str(host or "http://localhost:11434").rstrip("/")
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status != 200:
                return False, None
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        if not models:
            return False, None
        c_m = str(custom_model or "").strip().lower()
        if c_m:
            for m in models:
                if c_m in m.lower():
                    return True, m
        priority = (
            "qwen3-vl", "qwen2.5vl", "qwen2.5-vl", "qwen2-vl",
            "gemma3", "llama3.2-vision", "minicpm-v", "internvl", "llava", "pixtral", "moondream"
        )
        for pref in priority:
            for m in models:
                if pref in m.lower() and is_ollama_vision_model_name(m):
                    return True, m
        for m in models:
            if is_ollama_vision_model_name(m):
                return True, m
        return False, None
    except Exception:
        return False, None

def query_ollama_vision(b64_img, prompt, cfg, engine_opts=None, timeout=90):
    """Executa OCR via servidor Ollama com modelo multimodal (ex: Qwen2.5-VL / Gemma3 / LLaVA)."""
    engine_opts = engine_opts if engine_opts is not None else {}
    if engine_opts.get("ollama_vision_offline"):
        raise RuntimeError("Ollama Vision indisponível.")
    host = str(cfg.get("ollama_host", "http://localhost:11434")).rstrip("/")
    v_model = engine_opts.get("ollama_vision_model_resolved")
    if not v_model:
        ok_ov, v_model = check_ollama_vision_available(host=host, custom_model=cfg.get("ollama_vision_model"))
        if not ok_ov or not v_model:
            engine_opts["ollama_vision_offline"] = True
            raise RuntimeError("Nenhum modelo Ollama Vision encontrado.")
        engine_opts["ollama_vision_model_resolved"] = v_model

    payload = {
        "model": v_model,
        "messages": [{"role": "user", "content": prompt, "images": [b64_img]}],
        "stream": False,
        "keep_alive": "60m",
        "options": {"temperature": 0.0, "num_predict": 1500}
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    out = _strip_think_tags(res.get("message", {}).get("content", "") or "")
    if not out.strip():
        raise RuntimeError(f"Ollama Vision '{v_model}' retornou resposta vazia.")
    return out.strip()

def _classic_fallback_page_blocks(img_cv, is_korean=False, engine_opts=None):
    """Fallback cirúrgico por página para OCR clássico caso Vision falhe ou bloqueie página +18."""
    engine_opts = engine_opts if engine_opts is not None else {}
    cache_key = f"_fallback_rec_engine_{bool(is_korean)}"
    rec_engine = engine_opts.get(cache_key)
    if rec_engine is None:
        rec_engine = get_rapidocr_engine(is_korean=bool(is_korean))
        engine_opts[cache_key] = rec_engine

    min_ch = img_cv.min(axis=2)
    min_bgr = cv2.cvtColor(min_ch, cv2.COLOR_GRAY2BGR)
    res, _ = rec_engine(img_cv)
    if not res or len(res) < 2:
        res_alt, _ = rec_engine(min_bgr)
        if res_alt and len(res_alt) > (len(res) if res else 0):
            res = res_alt

    blocks_for_grouping = []
    if res:
        for box_data in res:
            coords = box_data[0]
            text = box_data[1]
            score = float(box_data[2]) if len(box_data) > 2 else 1.0
            if is_ocr_noise(text, score, is_korean=is_korean):
                continue
            xs = [p[0] for p in coords]
            ys = [p[1] for p in coords]
            blocks_for_grouping.append({
                "box": [min(xs), min(ys), max(xs), max(ys)],
                "text": str(text).strip()
            })

    grouped = smart_group_bubbles(blocks_for_grouping)
    final_blocks = []
    for b in grouped:
        final_blocks.append({
            "box": [int(round(float(v))) for v in b["box"]],
            "raw_boxes": [[int(round(float(v))) for v in rb] for rb in b.get("raw_boxes", [b["box"]])],
            "orig_line_count": int(b.get("orig_line_count", max(1, len(b.get("lines", []))))),
            "vertical": bool(b["is_vertical"]),
            "lines": b["lines"]
        })
    return final_blocks

def _build_vision_prompt_for_ids(box_ids):
    id_min, id_max = box_ids[0], box_ids[-1]
    id_list_str = ", ".join(f'"{i}"' for i in box_ids)
    return (
        f"Look at this manga/comic page. Specific text regions are marked with colored rectangles labeled [{id_min}] through [{id_max}].\n"
        f"Extract the EXACT original text inside each numbered rectangle in its ORIGINAL source language (Japanese, Korean, Chinese, English, Spanish, etc.).\n"
        f"CRITICAL RULES:\n"
        f"- DO NOT translate the text. Copy the exact original words/characters visible inside each box.\n"
        f"- Preserve punctuation (!, ?, ..., ~) and heart symbols (♡).\n"
        f"- Join lines inside the same box cleanly in natural reading order with spaces (or without spaces for Japanese/Chinese).\n"
        f"- If a numbered box contains only artwork, shading, decorative UI icons/lines, or no readable dialogue/SFX text, set its value to \"\".\n"
        f"Respond ONLY with a valid JSON object containing keys {id_list_str}. Example:\n"
        f"{{\"{id_min}\": \"original text\"}}"
    )

def extract_page_bubbles_with_ai_vision(img_cv, cfg, det_engine=None, engine_opts=None, fallback_is_korean=False):
    """
    Pipeline Híbrido para uma página:
    1. Detector geométrico local encontra balões/linhas e preserva coordenadas exatas (raw_boxes).
    2. IA Vision lê o texto difícil/estilizado das caixas numeradas [1]..[N] na língua original.
    3. Fallback automático por página para OCR clássico (PP-OCRv5 / RapidOCR) se Vision falhar ou recusar +18.
    Retorna: (final_blocks, mode_used)
    """
    engine_opts = engine_opts if engine_opts is not None else {}
    if det_engine is None:
        det_engine = engine_opts.get("_det_engine")
        if det_engine is None:
            det_engine = get_rapidocr_engine(is_korean=False)
            engine_opts["_det_engine"] = det_engine

    grouped = _detect_text_boxes_for_vision(det_engine, img_cv)
    if not grouped:
        return [], "empty"

    vis_pref = str(cfg.get("vision_provider", "auto") or "auto").lower()
    raw_gem_keys = list(cfg.get("gemini_api_keys") or [])
    if cfg.get("gemini_api_key") and cfg.get("gemini_api_key") not in raw_gem_keys:
        raw_gem_keys.insert(0, cfg.get("gemini_api_key"))
    raw_groq_keys = list(cfg.get("groq_api_keys") or [])
    if cfg.get("groq_api_key") and cfg.get("groq_api_key") not in raw_groq_keys:
        raw_groq_keys.insert(0, cfg.get("groq_api_key"))
    raw_or_keys = list(cfg.get("openrouter_api_keys") or [])
    if cfg.get("openrouter_api_key") and cfg.get("openrouter_api_key") not in raw_or_keys:
        raw_or_keys.insert(0, cfg.get("openrouter_api_key"))

    has_gemini = bool([k for k in raw_gem_keys if str(k).strip() and not str(k).strip().startswith(("gsk_", "sk-or-"))])
    has_groq = bool([k for k in raw_groq_keys if str(k).strip() and not str(k).strip().startswith(("sk-or-", "AIza"))])
    has_openrouter = bool([k for k in raw_or_keys if str(k).strip() and not str(k).strip().startswith("gsk_")])

    if vis_pref == "gemini":
        chain = ["gemini", "groq", "openrouter", "ollama"]
    elif vis_pref == "groq":
        chain = ["groq", "gemini", "openrouter", "ollama"]
    elif vis_pref == "openrouter":
        chain = ["openrouter", "groq", "gemini", "ollama"]
    elif vis_pref == "ollama":
        chain = ["ollama", "groq", "gemini", "openrouter"]
    elif str(cfg.get("provider", "auto")).lower() == "ollama":
        chain = ["ollama", "gemini", "groq", "openrouter"]
    else:
        chain = ["gemini", "groq", "openrouter", "ollama"]

    # Remove provedores claramente não configurados na ordem rápida
    ordered_chain = []
    for p_name in chain:
        if p_name == "gemini" and not has_gemini:
            continue
        if p_name == "groq" and not has_groq:
            continue
        if p_name == "openrouter" and not has_openrouter:
            continue
        if p_name == "ollama" and engine_opts.get("ollama_vision_offline"):
            continue
        ordered_chain.append(p_name)

    if not ordered_chain:
        return _classic_fallback_page_blocks(img_cv, is_korean=fallback_is_korean, engine_opts=engine_opts), "classic_fallback"

    for idx, b in enumerate(grouped):
        b["vision_id"] = idx + 1

    extracted_map = {}
    batch_size = 8
    used_backend = None
    vision_failed_all = False

    for b_start in range(0, len(grouped), batch_size):
        subset = grouped[b_start:b_start + batch_size]
        box_ids = [item["vision_id"] for item in subset]
        b64_img = _render_vision_annotated_image(img_cv, subset, max_side=1450)
        prompt = _build_vision_prompt_for_ids(box_ids)

        chunk_parsed = None
        for backend in ordered_chain:
            try:
                if backend == "gemini":
                    raw_resp = query_gemini_vision(b64_img, prompt, cfg, engine_opts=engine_opts)
                elif backend == "groq":
                    groq_max_tok = min(760, max(380, 95 * len(box_ids) + 120))
                    raw_resp = query_groq_vision(b64_img, prompt, cfg, engine_opts=engine_opts, max_tokens=groq_max_tok)
                elif backend == "openrouter":
                    raw_resp = query_openrouter_vision(b64_img, prompt, cfg, engine_opts=engine_opts)
                elif backend == "ollama":
                    raw_resp = query_ollama_vision(b64_img, prompt, cfg, engine_opts=engine_opts)
                else:
                    continue

                parsed = _parse_vision_ocr_json(raw_resp, box_ids)
                has_json_keys = bool(re.search(r'"\d+"\s*:', str(raw_resp or "")))
                if any(v for v in parsed.values()) or len(box_ids) <= 1 or has_json_keys:
                    chunk_parsed = parsed
                    used_backend = backend
                    break
            except VisionSafetyBlockedError as sb_err:
                print(f"[*] {backend.upper()} Vision recusou página sensível ({sb_err}). Tentando próximo motor Vision/OCR...")
                continue
            except Exception as v_err:
                print(f"[!] Aviso {backend.upper()} Vision falhou no lote: {v_err}")
                continue

        if chunk_parsed is None:
            vision_failed_all = True
            break
        extracted_map.update(chunk_parsed)

    # Checa se houve falha total ou recusa silenciosa em páginas densas
    substantive_boxes = [
        item for item in grouped
        if (item["box"][2] - item["box"][0]) >= 22 and (item["box"][3] - item["box"][1]) >= 22
    ]
    non_empty_count = sum(1 for item in grouped if extracted_map.get(str(item["vision_id"]), "").strip())
    if vision_failed_all or (len(substantive_boxes) >= 2 and non_empty_count == 0):
        print("[*] Vision AI sem extração válida nesta página -> Acionando fallback OCR clássico...")
        return _classic_fallback_page_blocks(img_cv, is_korean=fallback_is_korean, engine_opts=engine_opts), "classic_fallback"

    ih, iw = img_cv.shape[:2]
    ref_w = max(1.0, float(min(iw, ih)))
    tiny_noise_area = (0.028 * ref_w) ** 2

    final_blocks = []
    for item in grouped:
        txt = extracted_map.get(str(item["vision_id"]), "").strip()
        if not txt:
            continue
        raw_bxs = item.get("raw_boxes") or [item["box"]]
        bw = max(0.0, float(item["box"][2] - item["box"][0]))
        bh = max(0.0, float(item["box"][3] - item["box"][1]))
        if len(raw_bxs) <= 1 and (bw * bh) < tiny_noise_area and re.fullmatch(r'[a-z0-9.,:;\-_=+*~`\'"/\\↑↓←→°·]+', txt):
            continue
        orig_lc = max(1, int(item.get("orig_line_count", len(raw_bxs))))
        final_blocks.append({
            "box": [int(round(float(v))) for v in item["box"]],
            "raw_boxes": [[int(round(float(v))) for v in rb] for rb in raw_bxs],
            "orig_line_count": orig_lc,
            "vertical": bool(item["is_vertical"]),
            "lines": [txt]
        })

    return final_blocks, (used_backend or "vision")

def generate_ai_vision_json(manga_dir, output_json_path, cfg=None, progress_cb=None):
    """Executa OCR Híbrido (Detector Geométrico Local + IA Vision) gerando .mokuro compatível."""
    img_files = get_image_files(manga_dir)
    if not img_files:
        print(f"[!] Erro crítico: Nenhuma imagem válida encontrada em '{manga_dir}'.")
        return False

    if cfg is None:
        cfg = load_config()

    det_engine = get_rapidocr_engine(is_korean=False)
    engine_opts = {"_det_engine": det_engine}

    folder_name = os.path.basename(manga_dir)
    fallback_is_korean = bool(
        re.search(r'[\uac00-\ud7af]', folder_name)
        or re.search(r'\[(korean|coreano|kr|ko)\]', folder_name, re.IGNORECASE)
        or "manhwa" in folder_name.lower()
        or "webtoon" in folder_name.lower()
    )
    korean_checked = fallback_is_korean

    raw_gem_keys = list(cfg.get("gemini_api_keys") or [])
    if cfg.get("gemini_api_key") and cfg.get("gemini_api_key") not in raw_gem_keys:
        raw_gem_keys.insert(0, cfg.get("gemini_api_key"))
    raw_groq_keys = list(cfg.get("groq_api_keys") or [])
    if cfg.get("groq_api_key") and cfg.get("groq_api_key") not in raw_groq_keys:
        raw_groq_keys.insert(0, cfg.get("groq_api_key"))
    raw_or_keys = list(cfg.get("openrouter_api_keys") or [])
    if cfg.get("openrouter_api_key") and cfg.get("openrouter_api_key") not in raw_or_keys:
        raw_or_keys.insert(0, cfg.get("openrouter_api_key"))

    has_gemini = bool([k for k in raw_gem_keys if str(k).strip() and not str(k).strip().startswith(("gsk_", "sk-or-"))])
    groq_valid_keys = [k for k in raw_groq_keys if str(k).strip() and not str(k).strip().startswith(("sk-or-", "AIza"))]
    has_groq = bool(groq_valid_keys)
    has_or = bool([k for k in raw_or_keys if str(k).strip() and not str(k).strip().startswith("gsk_")])
    ok_ov, ov_model = check_ollama_vision_available(
        host=cfg.get("ollama_host", "http://localhost:11434"),
        custom_model=cfg.get("ollama_vision_model")
    )
    if ok_ov and ov_model:
        engine_opts["ollama_vision_model_resolved"] = ov_model
    else:
        engine_opts["ollama_vision_offline"] = True

    active_backends = []
    if has_gemini:
        active_backends.append(f"Gemini Vision ({cfg.get('gemini_model', 'gemini-2.5-flash')})")
    if has_groq:
        active_backends.append(f"Groq Vision ({cfg.get('groq_vision_model', GROQ_DEFAULT_VISION_MODELS[0])} | {len(groq_valid_keys)} chave(s))")
    if has_or:
        active_backends.append(f"OpenRouter Vision ({cfg.get('openrouter_vision_model', OPENROUTER_DEFAULT_VISION_MODELS[0])})")
    if ok_ov and ov_model:
        active_backends.append(f"Ollama Vision ({ov_model})")
    if not active_backends:
        print("[!] Aviso: Nenhum provedor IA Vision configurado/online (Gemini, Groq, OpenRouter ou Ollama Vision). Usando OCR clássico automático por página.")
    else:
        print(f"[*] Extraindo textos com IA Vision Híbrido -> Motores prontos: {' | '.join(active_backends)}")

    pages = []
    mode_counts = {}
    for idx, img_path in enumerate(tqdm(img_files, desc="IA Vision OCR")):
        if progress_cb:
            try:
                progress_cb("ocr", idx + 1, len(img_files), f"IA Vision (OCR Híbrido): Lendo página {idx + 1} de {len(img_files)}")
            except Exception:
                pass
        img_name = os.path.basename(img_path)
        try:
            with open(img_path, "rb") as f:
                img_array = np.asarray(bytearray(f.read()), dtype=np.uint8)
                img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        except Exception:
            img_cv = None

        if img_cv is None:
            continue

        # Se precisar de fallback clássico numa obra sem título óbvio, detecta idioma real 1 única vez
        if not korean_checked and (
            (not active_backends)
            or engine_opts.get("_need_lang_check")
        ):
            try:
                fallback_is_korean = (detect_manga_language_and_engine(manga_dir) == "korean")
            except Exception:
                fallback_is_korean = False
            korean_checked = True

        blocks, mode_used = extract_page_bubbles_with_ai_vision(
            img_cv,
            cfg,
            det_engine=det_engine,
            engine_opts=engine_opts,
            fallback_is_korean=fallback_is_korean
        )
        if mode_used == "classic_fallback" and not korean_checked:
            try:
                if detect_manga_language_and_engine(manga_dir) == "korean":
                    fallback_is_korean = True
                    blocks = _classic_fallback_page_blocks(img_cv, is_korean=True, engine_opts=engine_opts)
            except Exception:
                pass
            korean_checked = True

        mode_counts[mode_used] = mode_counts.get(mode_used, 0) + 1
        pages.append({
            "img_path": img_name,
            "img_width": int(img_cv.shape[1]),
            "img_height": int(img_cv.shape[0]),
            "blocks": blocks
        })

    vision_pages = sum(cnt for m_k, cnt in mode_counts.items() if m_k not in ("classic_fallback", "empty"))
    fallback_pages = mode_counts.get("classic_fallback", 0)
    if mode_counts:
        stats_str = ", ".join(f"{k}={v}" for k, v in mode_counts.items())
        print(f"[+] IA Vision OCR concluído: {vision_pages}/{len(pages)} página(s) via Visão IA ({stats_str})")

    if vision_pages == 0 and fallback_pages > 0:
        mokuro_data = {
            "version": "rapidocr_korean" if fallback_is_korean else "rapidocr",
            "ocr_model": "ppocr_v5_korean" if fallback_is_korean else "rapidocr_default",
            "vision_stats": mode_counts,
            "pages": pages
        }
    else:
        mokuro_data = {
            "version": "ai_vision",
            "ocr_model": "ai_vision_hybrid",
            "vision_stats": mode_counts,
            "pages": pages
        }
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(mokuro_data, f, ensure_ascii=False)
    return True

def is_scan_watermark(text):
    """Detecta marcas d'água puras de grupos scanlators chineses/ocidentais para não poluir balões."""
    if not text:
        return False
    t = str(text).strip()
    if re.search(r'(?:社具[券费]号|QQ\s*群|汉化组|交流群|扫图|嵌字|图源|禁止转载)[：:]?\s*\d*', t):
        return True
    if re.match(r'^(?:春卷\s*)?社具[券费]号[：:]?\s*\d+$', t):
        return True
    return False

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
    # Rejeita saídas truncadas de uma única letra quando o original tem 3 ou mais caracteres (ex: 'O' para frase longa)
    if len(clean_orig) >= 3 and len(clean_trans) <= 1:
        return False
    # Rejeita saídas de até 2 letras a menos que sejam interjeições ou pronomes autênticos
    if len(clean_orig) >= 3 and len(clean_trans) <= 2:
        ct_l = clean_trans.lower()
        allowed_short = {"ah", "ai", "oi", "eh", "oh", "ui", "hm", "ha", "ei", "ué", "ok", "hã", "tá", "né"}
        if len(clean_orig) <= 4:
            allowed_short |= {"eu", "é!", "já", "vá"}
        if ct_l not in allowed_short:
            return False

    # Rejeita alucinações, mensagens de sistema e erros técnicos de tradutores automáticos
    corrupt_markers = [
        'invalid source language', 'mymemory warning', 'delfim perverso',
        'como uma inteligência artificial', 'como uma ia', 'traduza o texto original',
        'regras obrigatórias', 'system message', 'mensagem do sistema', 'o gato está sentado',
        'parece cocô', 'cons e que n ces', 'louco ou omi', 'meu e obi', 's aging', 'estou envelhecendo',
        'a s ihl', 'uh está bem', 'salário desta mulher é uma ganha', 'poo 6', 'fury a sama', 'fury a,',
        '<x ', '</x>'
    ]
    ct_lower = clean_trans.lower()
    if any(cm in ct_lower for cm in corrupt_markers) or ct_lower in ('auto', '[auto]'):
        return False

    return True

def process_manga(manga_dir, target_lang="pt-BR", ocr_mode="auto", force_ocr=False, retranslate=False, is_adult=True, config=None, progress_cb=None):
    if sys.stdout is None:
        sys.stdout = _SafeStreamWrapper()
    if sys.stderr is None:
        sys.stderr = _SafeStreamWrapper()

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
    
    # 0. Define o diretório de destino (respeitando pares MANGAS -> MANGAS [PT-BR] no Drive/Colab ou config do usuário)
    cfg_target = config.get("translated_mangas_dir") if config else None
    norm_manga_path = os.path.abspath(manga_dir).replace('\\', '/')
    sibling_ptbr_dir = None
    if "/MANGAS/" in f"/{norm_manga_path}/" or norm_manga_path.endswith("/MANGAS"):
        parts = norm_manga_path.split('/')
        m_idx = max(i for i, part in enumerate(parts) if part.upper() == "MANGAS")
        parent_dir = '/'.join(parts[:m_idx])
        if parent_dir:
            cand_ptbr = os.path.join(parent_dir, "MANGAS [PT-BR]")
            if os.path.exists(cand_ptbr) or "drive" in parent_dir.lower():
                sibling_ptbr_dir = cand_ptbr

    is_default_onedrive = bool(
        cfg_target
        and os.path.normcase(os.path.abspath(str(cfg_target))) == os.path.normcase(os.path.abspath(BASE_OUTPUT_DIR))
    )
    if sibling_ptbr_dir and (is_default_onedrive or not cfg_target or not os.path.isdir(cfg_target)):
        base_drive_dir = sibling_ptbr_dir
        os.makedirs(base_drive_dir, exist_ok=True)
    elif cfg_target and os.path.isdir(cfg_target):
        base_drive_dir = cfg_target
    elif os.path.exists("/content/drive/MyDrive"):
        base_drive_dir = "/content/drive/MyDrive/MANGAS [PT-BR]"
        os.makedirs(base_drive_dir, exist_ok=True)
    elif "/MANGAS/" in f"/{norm_manga_path}/" or norm_manga_path.endswith("/MANGAS"):
        parts = norm_manga_path.split('/')
        m_idx = max(i for i, part in enumerate(parts) if part.upper() == "MANGAS")
        parent_dir = '/'.join(parts[:m_idx])
        base_drive_dir = os.path.join(parent_dir, "MANGAS [PT-BR]")
        os.makedirs(base_drive_dir, exist_ok=True)
    elif os.path.exists(BASE_OUTPUT_DIR):
        base_drive_dir = BASE_OUTPUT_DIR
    else:
        base_drive_dir = os.path.dirname(manga_dir)
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
    import tempfile
    temp_render_dir = os.path.join(tempfile.gettempdir(), f"manga_render_tmp_{uuid.uuid4().hex[:8]}")
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
    ocr_mode_low = str(ocr_mode or "auto").lower().strip()
    if ocr_mode_low in ("ai_vision", "vision", "ia_vision", "ia", "ai"):
        expected_engine = "ai_vision"
    elif ocr_mode_low in ("korean", "manhwa"):
        expected_engine = "rapidocr_korean"
    elif ocr_mode_low == "rapidocr":
        expected_engine = "rapidocr"
    elif ocr_mode_low == "mokuro":
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

    # Verificação de segurança: se Mokuro foi escolhido mas não está instalado no ambiente
    if expected_engine == "mokuro" and not is_mokuro_available():
        print("[!] Aviso: Mokuro não está instalado neste ambiente. Alternando automaticamente para RapidOCR Universal...")
        expected_engine = "rapidocr"

    print(f"[+] Motor OCR definido: {expected_engine.upper()}")

    needs_new_ocr = True
    ocr_model_upgraded = False
    if not force_ocr and os.path.exists(mokuro_path):
        try:
            with open(mokuro_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            file_version = str(existing_data.get("version", ""))
            file_ocr_model = str(existing_data.get("ocr_model", ""))
            pages = existing_data.get("pages", [])
            total_blocks = sum(len(p.get("blocks", [])) for p in pages)
            
            engine_matches = (
                (expected_engine == "ai_vision" and file_version == "ai_vision" and file_ocr_model == "ai_vision_hybrid") or
                (expected_engine == "rapidocr_korean" and file_version == "rapidocr_korean" and file_ocr_model == "ppocr_v5_korean") or
                (expected_engine == "rapidocr" and file_version == "rapidocr") or
                (expected_engine == "mokuro" and file_version not in ("rapidocr", "rapidocr_korean", "ai_vision"))
            )
            
            if len(pages) > 0 and total_blocks > 0 and engine_matches:
                print(f"[+] Cache OCR ({expected_engine.upper()}) encontrado ({total_blocks} balões em {len(pages)} páginas). Reutilizando...")
                needs_new_ocr = False
            else:
                if expected_engine == "rapidocr_korean" and file_ocr_model != "ppocr_v5_korean":
                    print("[*] Modelo OCR Coreano atualizado (PP-OCRv5). Regerando OCR e traduções antigas automaticamente...")
                    ocr_model_upgraded = True
                try: os.remove(mokuro_path)
                except Exception: pass
                needs_new_ocr = True
        except Exception:
            needs_new_ocr = True

    if needs_new_ocr:
        if expected_engine == "ai_vision":
            print("[+] Executando IA Vision Híbrido (Detector Geométrico Local + IA Vision)...")
            generate_ai_vision_json(manga_dir, mokuro_path, cfg=config, progress_cb=progress_cb)
        elif expected_engine == "rapidocr_korean":
            print("[+] Executando RapidOCR Coreano (Hangul)...")
            generate_rapidocr_json(manga_dir, mokuro_path, is_korean=True, progress_cb=progress_cb)
        elif expected_engine == "rapidocr":
            print("[+] Executando RapidOCR Universal com detecção de textos coloridos...")
            generate_rapidocr_json(manga_dir, mokuro_path, is_korean=False, progress_cb=progress_cb)
        else:
            print("[*] Executando motor Asiático especializado (Mokuro)...")
            import subprocess
            mokuro_ok = False
            try:
                subprocess.run([sys.executable, "-m", "mokuro", manga_dir, "--disable_confirmation"], check=True)
                temp_mokuro = os.path.join(parent_dir, manga_name + ".mokuro")
                if os.path.exists(temp_mokuro):
                    shutil.move(temp_mokuro, mokuro_path)
                mokuro_ok = os.path.exists(mokuro_path)
            except Exception as e:
                print(f"[!] Erro ao executar o Mokuro: {e}")
                mokuro_ok = False

            if not mokuro_ok:
                print("[*] Ativando fallback automático para RapidOCR Universal para garantir a conclusão da tradução...")
                expected_engine = "rapidocr"
                generate_rapidocr_json(manga_dir, mokuro_path, is_korean=False, progress_cb=progress_cb)

    if not os.path.exists(mokuro_path):
        print("[!] Arquivo de texto OCR não foi gerado. Falha na leitura.")
        return False

    with open(mokuro_path, "r", encoding="utf-8") as f:
        mokuro_data = json.load(f)

    raw_pages = mokuro_data.get("pages", [])
    if not raw_pages:
        print("[!] Erro crítico: O OCR não extraiu nenhuma página deste mangá. Abortando processo.")
        return False
        
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
            is_cjk_blk = is_majority_cjk(lines)
            is_ko_blk = is_majority_hangul(lines)
            text = smart_join_lines(lines, is_cjk=is_cjk_blk, preserve_spaces=is_ko_blk).strip()
            if not text:
                continue
            blk_entry = {
                "box": [xmin, ymin, xmax, ymax],
                "text": text,
                "lines": lines,
                "orig_line_count": max(1, int(blk.get("orig_line_count") or len(lines) or 1)),
                "is_vertical": is_vertical
            }
            if blk.get("raw_boxes"):
                blk_entry["raw_boxes"] = blk.get("raw_boxes")
            blocks_for_grouping.append(blk_entry)
            
        grouped = smart_group_bubbles(blocks_for_grouping)
        bubbles = []
        for b in grouped:
            all_raw_texts.append(b["combined_text"])
            bubbles.append({
                "box": b["box"],
                "raw_boxes": b.get("raw_boxes", [b["box"]]),
                "orig_line_count": b.get("orig_line_count", max(1, len(b.get("lines", [])))),
                "lines": b["lines"],
                "combined_text": b["combined_text"],
                "is_vertical": b["is_vertical"]
            })
            
        pages_data.append({
            "page": idx + 1,
            "img": fname,
            "width": page_info.get("img_width", 1200),
            "height": page_info.get("img_height", 1800),
            "bubbles": bubbles
        })
            
    # 3. Detectar idioma e traduzir com cache
    src_lang = detect_language_from_samples(all_raw_texts)
    print(f"[+] Idioma predominante detectado: '{src_lang.upper()}'")
    
    cache = {}
    if ocr_model_upgraded and os.path.exists(cache_file):
        try: os.remove(cache_file)
        except Exception: pass
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as cf:
                raw_cache = json.load(cf)
            # Purga automaticamente entradas corrompidas por alucinações, erros de API ou vazamentos de IA
            corrupt_markers = [
                'delfim perverso', 'o gato está sentado', 'vem lá, meu amigo',
                'estou traduzindo o texto', 'com base nas regras', 'ok, vamos traduzir',
                'traduza o texto original', 'como uma inteligência artificial', 'regras obrigatórias',
                'system message', 'mensagem do sistema', 'invalid source language', 'mymemory warning',
                'parece cocô', 'cons e que n ces', 'louco ou omi', 'meu e obi', 's aging', 'estou envelhecendo',
                'a s ihl', 'uh está bem', 'salário desta mulher é uma ganha', 'poo 6', 'fury a sama', 'fury a,',
                '<x ', '</x>'
            ]
            for k, v in raw_cache.items():
                v_clean = str(v).strip().lower()
                if v_clean in ('auto', '[auto]'):
                    continue
                k_low = str(k).lower()
                # Purga bug legado onde 'você' virou 'uh' dentro de frases com segunda pessoa real
                if re.search(r'\buh\b', v_clean) and not re.search(r'\bvoc[êe]\b', v_clean):
                    if re.search(r'(?:\byou\b|\byour\b|\bt[uú]\b|你|您|あなた|お前|君|너)', k_low) and not re.search(r'\buh+\b|\bu[\s,.;!?~-]+u\b', k_low):
                        continue
                if not any(cm in v_clean for cm in corrupt_markers) and is_valid_translation(k, v):
                    cache[k] = v
        except Exception:
            pass
            
    engine_type, model_name, engine_opts = init_ai_translation_engine(config, is_adult=is_adult)
    if engine_type == "groq":
        print(f"[+] MOTOR ATIVO: Groq Cloud Ultra-Rápido -> Modelo: '{model_name}' (Zero Censura | Nuvem)")
    elif engine_type == "openrouter":
        print(f"[+] MOTOR ATIVO: OpenRouter Cloud (Nuvem) -> Modelo: '{model_name}' (Sem usar recursos do PC)")
    elif engine_type == "ollama":
        print(f"[+] MOTOR ATIVO: Ollama ({engine_opts.get('host')}) -> Modelo: '{model_name}'")
    else:
        print(f"[*] Modo Fallback de Tradução Nuvem ativado (MyMemory/Google).")

    # Traduz página por página com coerência narrativa e suporte a glossário
    for p in tqdm(pages_data, desc="Tradução Contextual", unit="pág"):
        if progress_cb:
            try: progress_cb("translation", p["page"], len(pages_data), f"Dupla de IAs: Mapeando e adaptando cena da pág {p['page']} de {len(pages_data)}")
            except Exception: pass
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
            batch_res = translate_page_dialogue(
                untranslated,
                engine_opts=engine_opts,
                is_adult=is_adult,
                glossary=glossary,
                page_w=p.get("width", 1200),
                page_h=p.get("height", 1800),
                src_lang=src_lang,
                page_num=p.get("page", 1)
            )
            for orig, trans in batch_res.items():
                if trans and is_valid_translation(orig, trans):
                    cache[orig] = clean_ai_translation(trans, original_text=orig, is_adult=is_adult)
                    
            # Se ainda houver textos sem tradução válida, tenta o fallback
            still_untranslated = [item[0] for item in untranslated if item[0] not in cache or not is_valid_translation(item[0], cache[item[0]])]
            if still_untranslated:
                cloud_res = translate_batch_texts(still_untranslated, src_lang=src_lang, is_adult=is_adult, engine_opts=engine_opts)
                for orig, trans in zip(still_untranslated, cloud_res):
                    if trans and is_valid_translation(orig, trans):
                        cache[orig] = clean_ai_translation(trans, original_text=orig, is_adult=is_adult)

    try:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as cf:
            json.dump(cache, cf, ensure_ascii=False, indent=2)
        # Salva novas traduções aprovadas pela IA na memória global (nunca grava fallback de emergência)
        if engine_type is not None:
            fb_originals = (engine_opts or {}).get("_fallback_originals", set())
            ai_approved_cache = {k: v for k, v in cache.items() if k not in fb_originals}
            update_global_translation_memory(ai_approved_cache)
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
        if progress_cb:
            try: progress_cb("diagram", idx + 1, len(pages_data), f"Diagramação e Inpainting: Página {idx + 1} de {len(pages_data)}")
            except Exception: pass
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
        
        # 4.1 Limpar balões com algoritmo cirúrgico (Apenas se foi traduzido com sucesso)
        img_cv_gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        for b in bubbles:
            trans_txt = b.get("translated_text", "").strip()
            if not trans_txt or not is_valid_translation(b["combined_text"], trans_txt):
                continue
            r_boxes = b.get("raw_boxes") or [b["box"]]
            for r_box in r_boxes:
                clean_speech_bubble(cleaned, r_box)
            # Evita limpar retângulo de união diagonal em texto solto na arte; só aplica se o interior resultante já for liso/claro
            if len(r_boxes) > 1:
                ux0, uy0, ux1, uy1 = [max(0, int(round(v))) for v in b["box"]]
                ux1, uy1 = min(w_img, ux1), min(h_img, uy1)
                if ux1 > ux0 + 4 and uy1 > uy0 + 4:
                    u_gray = cv2.cvtColor(cleaned[uy0:uy1, ux0:ux1], cv2.COLOR_BGR2GRAY)
                    if float(np.mean(u_gray > 195)) > 0.72:
                        clean_speech_bubble(cleaned, b["box"])
                
        # 4.2 Desenhar texto traduzido com geometria anti-extravasamento e escala consistente
        cleaned_gray = cv2.cvtColor(cleaned, cv2.COLOR_BGR2GRAY)
        line_heights_all = []
        for b in bubbles:
            b_txt = b.get("translated_text", "").strip()
            if not b_txt or b_txt in ("...", "…") or not is_valid_translation(b["combined_text"], b_txt):
                continue
            rbs = b.get("raw_boxes") or [b["box"]]
            has_cjk_b = bool(re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', b.get("combined_text", "")))
            if b.get("is_vertical") and has_cjk_b:
                b_hs = [(rb[2] - rb[0]) for rb in rbs]
                b_h_med = float(np.median([max(8.0, float(v)) for v in b_hs])) if b_hs else float(b["box"][2] - b["box"][0])
            else:
                # RapidOCR/Mokuro frequentemente armazenam múltiplas linhas dentro de um único bbox unido (raw_boxes len == 1)
                n_lines = max(len(rbs), int(b.get("orig_line_count", 1)), 1)
                if len(rbs) > 1:
                    b_hs = [max(8.0, float(rb[3] - rb[1])) for rb in rbs]
                    b_h_med = float(np.median(b_hs))
                else:
                    b_h_med = max(10.0, float(b["box"][3] - b["box"][1]) / float(n_lines))
            b["_orig_line_h"] = b_h_med
            if b_h_med < w_img * 0.032:
                line_heights_all.append(b_h_med)
        page_med_h = float(np.median(line_heights_all)) if line_heights_all else max(14.0, w_img * 0.017)

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

            # 1. Particionamento espacial inteligente entre balões vizinhos (Voronoi por eixo principal de separação)
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

                v_overlap = min(ymax, o_ymax) - max(ymin, o_ymin)
                h_overlap = min(xmax, o_xmax) - max(xmin, o_xmin)
                gap_x = -h_overlap
                gap_y = -v_overlap

                # Só impõe parede em X quando os balões realmente dividem faixa vertical (ou estão separados principalmente em X)
                apply_x = (v_overlap > 6) or (gap_x >= 0 and v_overlap > -14 and gap_x >= gap_y)
                # Só impõe parede em Y quando os balões dividem faixa horizontal (ou estão separados principalmente em Y)
                apply_y = (h_overlap > 6) or (gap_y >= 0 and h_overlap > -14 and gap_y > gap_x)

                if apply_x and v_overlap > -36:
                    if o_cx < cx:
                        mid = (o_xmax + xmin) / 2
                        x_min_limit = max(x_min_limit, mid + 6)
                    elif o_cx > cx:
                        mid = (xmax + o_xmin) / 2
                        x_max_limit = min(x_max_limit, mid - 6)

                if apply_y and h_overlap > -28:
                    if o_cy < cy:
                        mid = (o_ymax + ymin) / 2
                        y_min_limit = max(y_min_limit, mid + 6)
                    elif o_cy > cy:
                        mid = (ymax + o_ymin) / 2
                        y_max_limit = min(y_max_limit, mid - 6)

            orig_line_h = b.get("_orig_line_h", page_med_h)
            limits = (x_min_limit, x_max_limit, y_min_limit, y_max_limit)
            geom = analyze_safe_balloon(cleaned_gray, img_cv_gray, b["box"], limits)

            is_white_bg = geom["is_white_bg"]
            render_white_on_dark = geom["render_white_on_dark"]
            safe_cx = geom["safe_cx"]
            safe_cy = geom["safe_cy"]
            safe_min_x = geom["safe_min_x"]
            safe_max_x = geom["safe_max_x"]
            safe_min_y = geom["safe_min_y"]
            safe_max_y = geom["safe_max_y"]
            target_w = geom["target_w"]
            target_h = geom["target_h"]

            # Margem de segurança na largura considerando os limites da partição e da página
            max_avail_w = min(
                (safe_cx - x_min_limit) * 2 - 8,
                (x_max_limit - safe_cx) * 2 - 8,
                min(safe_cx, w_img - safe_cx) * 2 - 16
            )
            if max_avail_w > 30:
                target_w = min(target_w, max_avail_w)

            is_display = bool(
                orig_line_h >= (w_img * 0.030)
                or (len(text.split()) <= 2 and (text.endswith("!!") or text.endswith("!?") or orig_line_h >= w_img * 0.025))
            )

            # Seleciona a melhor fonte tipográfica profissional para a fala
            chosen_font_path = select_font_for_bubble(text)
            stroke_w_hint = 1 if is_white_bg else 2
            font, lines, used_leading = fit_text_to_box_ex(
                draw, text, target_w, target_h, chosen_font_path,
                stroke_width=stroke_w_hint,
                shape_type=geom["shape_type"],
                band_profile=geom["band_profile"],
                page_w=w_img,
                orig_line_h=orig_line_h,
                page_med_h=page_med_h,
                is_display=is_display,
                pre_padded=geom["is_enclosed"]
            )
            if not lines:
                continue
                
            line_bbox = draw.textbbox((0, 0), "Ag", font=font)
            line_h = max(4.0, (line_bbox[3] - line_bbox[1]) * used_leading)
            total_h = len(lines) * line_h
            start_y = safe_cy - (total_h / 2.0) + (line_h / 2.0)
            
            # Margem de segurança vertical proporcional sem colisão topo/base
            pad_y_balloon = max(3, int(target_h * (0.04 if geom["is_enclosed"] else 0.08)))
            balloon_top = safe_min_y + pad_y_balloon
            balloon_bottom = max(balloon_top + 4.0, safe_max_y - pad_y_balloon)
            
            if total_h <= (balloon_bottom - balloon_top):
                first_line_top = start_y - (line_h / 2.0)
                if first_line_top < balloon_top:
                    start_y += (balloon_top - first_line_top)
                last_line_bottom = start_y + (len(lines) - 1) * line_h + (line_h / 2.0)
                if last_line_bottom > balloon_bottom:
                    start_y -= (last_line_bottom - balloon_bottom)
            else:
                start_y = (balloon_top + balloon_bottom) / 2.0 - (total_h / 2.0) + (line_h / 2.0)
                
            # Margem global de proteção para bordas da imagem da página
            if start_y - (line_h / 2.0) < 12:
                start_y = 12 + (line_h / 2.0)
            elif start_y + (len(lines) - 1) * line_h + (line_h / 2.0) > h_img - 12:
                start_y = h_img - 12 - (len(lines) - 1) * line_h - (line_h / 2.0)
                
            font_size = getattr(font, 'size', 20)
            if render_white_on_dark:
                text_fill = (255, 255, 255)
                stroke_fill = (15, 15, 15)
                stroke_w = max(2, int(round(font_size * 0.09)))
            else:
                text_fill = (0, 0, 0)
                stroke_fill = (255, 255, 255)
                stroke_w = 1 if is_white_bg else max(2, int(round(font_size * 0.08)))
            
            for line_idx, line in enumerate(lines):
                ly = start_y + (line_idx * line_h)
                draw_manga_text_line(draw, (safe_cx, ly), line, font=font, fill=text_fill, stroke_width=stroke_w, stroke_fill=stroke_fill, anchor="mm")
                
        out_file = os.path.join(temp_render_dir, os.path.splitext(img_name)[0] + ".jpg")
        img_pil.save(out_file, quality=95)

    rendered_files = [f for f in os.listdir(temp_render_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    if not rendered_files:
        print("[!] Erro crítico: Nenhuma página diagramada foi gerada no diretório temporário. Abortando processo para evitar salvar pasta vazia.")
        try: shutil.rmtree(temp_render_dir)
        except Exception: pass
        return False
            
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
        
    if progress_cb:
        try:
            progress_cb("done", len(pages_data), len(pages_data), "Manga traduzido com sucesso!", result={"output_dir": output_dir, "cbz_path": cbz_dest_path, "reader_path": os.path.join(output_dir, "leitor.html")})
        except Exception:
            pass
            
    return {"success": True, "output_dir": output_dir, "cbz_path": cbz_dest_path, "reader_path": os.path.join(output_dir, "leitor.html")}

def audit_manga_translation(manga_dir, rating=None, user_comment="", auto_heal=True):
    """
    Audita exaustivamente a tradução de um mangá com base em todos os critérios de qualidade:
    - Nomes próprios e honoríficos corrompidos (ex: Yu-kun -> ONU/Vamos)
    - Fragmentação de OCR decorrente de fontes estilizadas e kerning
    - Gírias adultas não traduzidas e falsos cognatos (pee pee, hard, hang out, cum)
    - Alucinações de tradutor automático, avisos de sistema e MyMemory
    - Estouro ou anomalias de formatação
    
    Salva relatório completo em 'relatorio_auditoria.json' e auto-injeta correções no
    aprendizado.txt, glossary.json e translation_cache.json (Auto-Learning da IA).
    """
    manga_dir = os.path.abspath(manga_dir)
    manga_name = os.path.basename(manga_dir)
    
    # 1. Localiza o arquivo de cache de tradução
    possible_cache_paths = [
        os.path.join(manga_dir, "cache", "translation_cache.json"),
        os.path.join(manga_dir, "translation_cache.json"),
        os.path.join(os.path.dirname(manga_dir), "cache", "translation_cache.json")
    ]
    cache_path = None
    for p in possible_cache_paths:
        if os.path.exists(p):
            cache_path = p
            break
            
    if not cache_path:
        return {
            "success": False,
            "error": "Cache de tradução não encontrado nesta pasta.",
            "manga_name": manga_name
        }
        
    with open(cache_path, "r", encoding="utf-8") as f:
        try:
            cache = json.load(f)
        except Exception as e:
            return {"success": False, "error": f"Erro ao ler cache: {e}", "manga_name": manga_name}
            
    issues = []
    healed = {}
    
    for k, v in cache.items():
        k_l = k.lower().strip()
        v_l = str(v).lower().strip()
        orig = k
        curr = str(v)
        
        # --- Critério 1: Nomes Próprios e Honoríficos ---
        if re.search(r'\b(?:yuk\s*un|yu-kun|yu\s*kun)\b', k_l):
            if any(w in v_l for w in ['onu', 'vamos', 'organização das nações']):
                clean_v = re.sub(r'(?i)\b(?:vamos\s+na\s+onu|vamos|onu|yuk\s+onu)\b', 'Yu-kun', curr).strip()
                issues.append({
                    'category': 'Nomes & Honoríficos',
                    'original': orig,
                    'current_translation': curr,
                    'suggested_correction': clean_v,
                    'reason': 'Nome do personagem "Yu-kun" foi corrompido em tradução literal (virou ONU/Vamos).'
                })
                healed[k] = clean_v
                continue
                
        if 's ihi woman' in k_l or 'natsuki san' in k_l:
            if 's ihi mulher' in v_l or 's ihi' in v_l:
                clean_v = re.sub(r'(?i)\bs\s*ihi\s*mulher', 'Essa mulher', curr)
                issues.append({
                    'category': 'Nomes & Honoríficos',
                    'original': orig,
                    'current_translation': curr,
                    'suggested_correction': clean_v,
                    'reason': 'Fragmentação de OCR em "This woman... Natsuki-san".'
                })
                healed[k] = clean_v
                continue

        # --- Critério 2: Fragmentação OCR por Fonte Comic ---
        if re.search(r'\bfr\s+i\s+end\b', k_l) and 'padre' in v_l:
            clean_v = 'Amiga...'
            issues.append({
                'category': 'Fragmentação OCR',
                'original': orig,
                'current_translation': curr,
                'suggested_correction': clean_v,
                'reason': 'Fragmentação de fonte comic: "Fr I END" (Friend) virou "Padre eu termino".'
            })
            healed[k] = clean_v
            continue

        if 'ch il dish' in k_l and 'prato' in v_l:
            clean_v = re.sub(r'(?i)ch\s+il\s+prato\.*', 'infantil...', curr)
            clean_v = re.sub(r'(?i)tipo\s+e\s+um\s+pouco', 'gentil e um pouco', clean_v)
            issues.append({
                'category': 'Fragmentação OCR',
                'original': orig,
                'current_translation': curr,
                'suggested_correction': clean_v,
                'reason': 'Fragmentação de fonte comic: "Ch IL DISH" (Childish) virou "prato".'
            })
            healed[k] = clean_v
            continue

        if re.search(r'\bs\s+que\s+ez\b', k_l) and 'ez' in v_l:
            clean_v = 'Aperta!'
            issues.append({
                'category': 'Fragmentação OCR',
                'original': orig,
                'current_translation': curr,
                'suggested_correction': clean_v,
                'reason': 'Fragmentação de fonte: "S QUE EZ" (Squeeze) virou "Ez".'
            })
            healed[k] = clean_v
            continue

        if re.search(r'\bwwa\s+it\b', k_l) and 'wwa' in v_l:
            clean_v = re.sub(r'(?i)\bwwa\s+isso\b', 'Espere!', curr)
            issues.append({
                'category': 'Fragmentação OCR',
                'original': orig,
                'current_translation': curr,
                'suggested_correction': clean_v,
                'reason': 'Fragmentação de fonte: "WWA IT" (Wait) virou "WWA ISSO".'
            })
            healed[k] = clean_v
            continue

        if re.search(r'\bsca\s+a\s+ary\b', k_l) and any(w in v_l for w in ['sca', 'ary']):
            clean_v = 'Que medo~'
            issues.append({
                'category': 'Fragmentação OCR',
                'original': orig,
                'current_translation': curr,
                'suggested_correction': clean_v,
                'reason': 'Fragmentação de balão esticado: "SCA A ARY" (Scary) virou "SCA PARA ARY".'
            })
            healed[k] = clean_v
            continue

        # --- Critério 3: Gírias Adultas & Falsos Cognatos ---
        if 'pee pee' in v_l:
            clean_v = re.sub(r'(?i)\bpee\s*pee\b', 'pauzinho', curr)
            issues.append({
                'category': 'Gírias Adultas & Falsos Cognatos',
                'original': orig,
                'current_translation': curr,
                'suggested_correction': clean_v,
                'reason': 'Termo anatômico erótico infantil ("pee pee") deixado em inglês sem tradução.'
            })
            healed[k] = clean_v
            continue

        if 'pendurar' in v_l and 'hang' in k_l:
            clean_v = re.sub(r'(?i)venha\s+pendurar\s+a\s+qualquer\s+hora!?', 'venha me visitar quando quiser!', curr)
            issues.append({
                'category': 'Gírias Adultas & Falsos Cognatos',
                'original': orig,
                'current_translation': curr,
                'suggested_correction': clean_v,
                'reason': 'Falso cognato: "come hang out" traduzido literalmente como "pendurar".'
            })
            healed[k] = clean_v
            continue

        if re.search(r'\bhard\b', k_l) and re.search(r'\bdif[ií]cil\b', v_l):
            clean_v = re.sub(r'(?i)\bdif[ií]cil\b', 'duro', curr)
            issues.append({
                'category': 'Gírias Adultas & Falsos Cognatos',
                'original': orig,
                'current_translation': curr,
                'suggested_correction': clean_v,
                'reason': 'Falso cognato erótico: "it\'s hard" traduzido como "é difícil" em vez de "tá duro/ereto".'
            })
            healed[k] = clean_v
            continue

        if re.search(r'\bcum\b', k_l) and 'cum' in v_l and not any(w in v_l for w in ['goz', 'porra', 'leite']):
            clean_v = re.sub(r'(?i)\bcum\b', 'gozar', curr)
            issues.append({
                'category': 'Gírias Adultas & Falsos Cognatos',
                'original': orig,
                'current_translation': curr,
                'suggested_correction': clean_v,
                'reason': 'Gíria erótica "cum" deixada em inglês sem tradução.'
            })
            healed[k] = clean_v
            continue

        # --- Critério 4: Alucinações de Tradutor e Vazamentos de Sistema ---
        corrupt_markers = [
            'invalid source language', 'mymemory warning', 'delfim perverso',
            'como uma inteligência artificial', 'traduza o texto original'
        ]
        if any(cm in v_l for cm in corrupt_markers) or v_l in ('auto', '[auto]'):
            clean_v = ''
            issues.append({
                'category': 'Vazamento de Sistema / Alucinação',
                'original': orig,
                'current_translation': curr,
                'suggested_correction': clean_v,
                'reason': 'Alucinação ou mensagem técnica de erro salva no cache de tradução.'
            })
            healed[k] = clean_v
            continue

    total_entries = len(cache)
    issue_count = len(issues)
    health_score = max(0, min(100, int(100 - (issue_count * 2.2))))
    
    categories = {
        'Nomes & Honoríficos': sum(1 for i in issues if i['category'] == 'Nomes & Honoríficos'),
        'Fragmentação OCR': sum(1 for i in issues if i['category'] == 'Fragmentação OCR'),
        'Gírias Adultas & Falsos Cognatos': sum(1 for i in issues if i['category'] == 'Gírias Adultas & Falsos Cognatos'),
        'Vazamento de Sistema / Alucinação': sum(1 for i in issues if i['category'] == 'Vazamento de Sistema / Alucinação')
    }

    # Auto-Heal: Atualiza cache local e memória global
    if auto_heal and healed:
        for k, v in healed.items():
            cache[k] = v
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
            
        base_dir = os.path.dirname(os.path.abspath(__file__))
        mem_path = os.path.join(base_dir, "memoria_traducoes.json")
        if os.path.exists(mem_path):
            try:
                with open(mem_path, "r", encoding="utf-8") as mf:
                    global_mem = json.load(mf)
                for k, v in healed.items():
                    global_mem[k] = v
                with open(mem_path, "w", encoding="utf-8") as mf:
                    json.dump(global_mem, mf, ensure_ascii=False, indent=2)
            except Exception:
                pass

    # Auto-Learning: Atualiza aprendizado.txt e glossary.json
    learned_rules_count = 0
    base_dir = os.path.dirname(os.path.abspath(__file__))
    aprendizado_file = os.path.join(base_dir, "aprendizado.txt")
    if os.path.exists(aprendizado_file) and issues:
        try:
            with open(aprendizado_file, "r", encoding="utf-8") as af:
                apr_text = af.read()
                
            import datetime
            now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
            new_rules = []
            
            if "Yu-kun" not in apr_text:
                new_rules.append("- Yu-kun / Yuk-un: Yu-kun (NUNCA traduzir como ONU ou Vamos)")
            if "pee-pee" not in apr_text and "pauzinho" not in apr_text:
                new_rules.append("- Pee-pee (contexto erótico/infantil): pauzinho / pinto (NUNCA deixar em inglês)")
            if "come hang out" not in apr_text:
                new_rules.append("- Come hang out: vir me visitar / passar um tempo (NUNCA traduzir como 'pendurar')")
            if "it's hard" not in apr_text:
                new_rules.append("- It's hard (em cena erótica com ereção): tá duro / ereto (NUNCA 'difícil')")
            if "Fr I END" not in apr_text:
                new_rules.append("- Fr I END (ruído de OCR de friend): amiga / amigo (NUNCA 'Padre eu termino')")
                
            if new_rules:
                learned_header = f"\n\n# =====================================================================\n# 🤖 REGRAS APRENDIDAS PELA AUTO-AUDITORIA DA IA ({now_str})\n# Avaliação do Usuário: {rating or 'Auditoria'} estrelas | {manga_name}\n# =====================================================================\n"
                learned_body = "\n".join(new_rules) + "\n"
                with open(aprendizado_file, "a", encoding="utf-8") as af:
                    af.write(learned_header + learned_body)
                learned_rules_count = len(new_rules)
        except Exception:
            pass

    import datetime
    report = {
        "success": True,
        "manga_name": manga_name,
        "rating": rating,
        "user_comment": user_comment,
        "audit_timestamp": datetime.datetime.now().isoformat(),
        "health_score": health_score,
        "total_cache_entries": total_entries,
        "issues_found_count": issue_count,
        "categories": categories,
        "issues_detail": issues,
        "auto_corrections_applied": len(healed),
        "auto_learned_rules_count": learned_rules_count
    }

    # Salva relatório JSON na pasta do mangá e na subpasta cache
    try:
        report_dest = os.path.join(manga_dir, "relatorio_auditoria.json")
        with open(report_dest, "w", encoding="utf-8") as rf:
            json.dump(report, rf, ensure_ascii=False, indent=2)
            
        cache_report_dest = os.path.join(os.path.dirname(cache_path), "relatorio_auditoria.json")
        if cache_report_dest != report_dest:
            with open(cache_report_dest, "w", encoding="utf-8") as rf:
                json.dump(report, rf, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return report

def retranslate_with_audit_fixes(manga_dir, progress_cb=None):
    """
    Retraduz e rediagrama o mangá aproveitando as correções aprendidas pela auto-auditoria
    sem precisar rodar OCR pesado novamente. Conclui em segundos com alta qualidade.
    """
    cfg = load_config()
    return process_manga(manga_dir, ocr_mode="auto", force_ocr=False, retranslate=False, is_adult=True, config=cfg, progress_cb=progress_cb)

def show_credits_dashboard(cfg=None):
    """Exibe painel ao vivo com créditos, cotas diárias e status dos motores de IA."""
    try:
        if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    if cfg is None:
        cfg = load_config()
        
    print("=" * 68)
    print("      PAINEL AO VIVO DE CREDITOS E STATUS DAS IAs [PT-BR]")
    print("=" * 68)
    
    # 1. GROQ CLOUD
    groq_key = cfg.get("groq_api_key", "").strip()
    active_groq_m = cfg.get("groq_model", "qwen/qwen3.8-27b")
    print("\n[1] GROQ CLOUD (Ultra-Rapido / Zero Censura na Nuvem)")
    if groq_key:
        masked_g = groq_key[:8] + "..." + groq_key[-4:] if len(groq_key) > 12 else "***"
        print(f"    Chave: {masked_g} | Modelo Padrao Configurado: {active_groq_m}")
        models_to_check = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
        for m in models_to_check:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            data = json.dumps({"model": m, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    rem_req = resp.headers.get("x-ratelimit-remaining-requests", "?")
                    lim_req = resp.headers.get("x-ratelimit-limit-requests", "1000")
                    rem_tok = resp.headers.get("x-ratelimit-remaining-tokens", "?")
                    lim_tok = resp.headers.get("x-ratelimit-limit-tokens", "8000")
                    rst_req = resp.headers.get("x-ratelimit-reset-requests", "?")
                    rst_tok = resp.headers.get("x-ratelimit-reset-tokens", "?")
                    star = " [ATIVO NO MOMENTO]" if m == active_groq_m else ""
                    print(f"    * Modelo: {m}{star}")
                    print(f"      - Requisicoes restantes:   {rem_req} / {lim_req} reqs/dia")
                    print(f"      - Tokens por minuto (TPM): {rem_tok} / {lim_tok} disponiveis")
                    print(f"      - Renovacao automatica:    Reseta em {rst_req} (Tokens em {rst_tok})")
                    print(f"      - Status operacional:      100% PRONTO E LIBERADO")
            except urllib.error.HTTPError as e:
                err_body = ""
                try: err_body = e.read().decode("utf-8", errors="ignore")
                except Exception: pass
                print(f"    * Modelo: {m}")
                if e.code == 429:
                    if "TPD" in err_body or "tokens per day" in err_body.lower():
                        print("      - Status: COTA DIARIA DE 200K ATINGIDA (Renova em breve)")
                    else:
                        print("      - Status: PAUSA TEMPORARIA DE TOKENS (Reset em segundos)")
                else:
                    print(f"      - Status: Erro HTTP {e.code}")
            except Exception as e:
                print(f"    * Modelo: {m} -> Nao respondeu ({e})")
    else:
        print("    [!] Chave Groq nao configurada em config.json.")

    # 2. OPENROUTER CLOUD
    or_keys = cfg.get("openrouter_api_keys", [])
    if not or_keys and cfg.get("openrouter_api_key"):
        or_keys = [cfg.get("openrouter_api_key")]
    print("\n[2] OPENROUTER CLOUD (Multi-Modelos: Nemotron, Dolphin, Hermes)")
    if or_keys:
        for idx, k in enumerate(or_keys):
            masked_o = k[:8] + "..." + k[-4:] if len(k) > 12 else "***"
            print(f"    Chave #{idx+1}: {masked_o}")
            try:
                req_or = urllib.request.Request("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": f"Bearer {k}"})
                with urllib.request.urlopen(req_or, timeout=8) as resp:
                    kdata = json.loads(resp.read().decode("utf-8")).get("data", {})
                    free_info = kdata.get("free_model_daily_requests", {})
                    f_used = free_info.get("used", 0)
                    f_limit = free_info.get("limit", 50)
                    f_rem = free_info.get("remaining", 0)
                    print("      - Categoria da Conta:     Gratuita (Free Tier)")
                    print(f"      - Cota Modelos Gratuitos: {f_used} / {f_limit} usadas hoje ({f_rem} restantes)")
                    if f_rem == 0:
                        print("        * Cota diaria esgotada hoje. Renova as 21:00 BRT (00:00 UTC).")
                    else:
                        print("        * Cota gratuita disponivel para uso.")
            except Exception as e:
                print(f"      - Erro ao checar chave: {e}")
                
            try:
                req_cred = urllib.request.Request("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {k}"})
                with urllib.request.urlopen(req_cred, timeout=8) as resp:
                    cdata = json.loads(resp.read().decode("utf-8")).get("data", {})
                    creds = float(cdata.get("total_credits", 0))
                    print(f"      - Saldo Pago (Creditos):  ${creds:.2f} USD (R$ {creds*5.8:.2f})")
                    if creds <= 0:
                        print("        * Dica: R$ 50 (~$8.50 USD) rendem aprox. 3.500 a 4.000 paginas sem filas!")
            except Exception:
                pass
    else:
        print("    [!] Nenhuma chave OpenRouter cadastrada.")

    # 3. OLLAMA LOCAL / REMOTO
    ollama_host = cfg.get("ollama_host", "http://localhost:11434")
    print(f"\n[3] OLLAMA (Servidor Local ou Google Colab)")
    print(f"    Host: {ollama_host}")
    try:
        req_ol = urllib.request.Request(f"{ollama_host.rstrip('/')}/api/tags")
        with urllib.request.urlopen(req_ol, timeout=3) as resp:
            if resp.status == 200:
                odata = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in odata.get("models", [])]
                v_models = [m for m in models if is_ollama_vision_model_name(m)]
                print(f"    - Status: ONLINE (100% Operacional)")
                print(f"    - Modelos instalados: {', '.join(models) if models else 'Nenhum'}")
                print(f"    - Modelos Vision:     {', '.join(v_models) if v_models else 'Nenhum detectado'}")
    except Exception:
        print(f"    - Status: OFFLINE (Nenhum servidor Ollama rodando nesta porta)")

    # 4. GOOGLE GEMINI VISION (Opcional para OCR IA Vision Híbrido)
    gem_keys = cfg.get("gemini_api_keys", [])
    print(f"\n[4] GOOGLE GEMINI VISION (Opcional para OCR IA Vision Hibrido)")
    if gem_keys:
        for idx, k in enumerate(gem_keys):
            masked_gem = k[:8] + "..." + k[-4:] if len(k) > 12 else "***"
            try:
                req_gm = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models?key={k}")
                with urllib.request.urlopen(req_gm, timeout=5) as resp:
                    if resp.status == 200:
                        print(f"    Chave #{idx+1}: {masked_gem} -> ATIVA (Modelo: {cfg.get('gemini_model', 'gemini-2.5-flash')})")
            except urllib.error.HTTPError as e:
                print(f"    Chave #{idx+1}: {masked_gem} -> HTTP {e.code}")
            except Exception as e:
                print(f"    Chave #{idx+1}: {masked_gem} -> Erro ({e})")
    else:
        print("    [i] Nenhuma chave Google Gemini cadastrada (Groq/OpenRouter/Ollama Vision funcionam mesmo assim).")

    print("\n" + "=" * 68)

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
        if "--status" in args or "--credits" in args or "--saldo" in args:
            show_credits_dashboard()
            sys.exit(0)
            
        if "--vision" in args or "--ai-vision" in args or "--ia-vision" in args:
            chosen_mode = "ai_vision"
            if "--vision" in args: args.remove("--vision")
            if "--ai-vision" in args: args.remove("--ai-vision")
            if "--ia-vision" in args: args.remove("--ia-vision")
        elif "--korean" in args or "--manhwa" in args:
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
        if "--retranslate" in args or "--retrans" in args:
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

        if "--groq" in args:
            cli_provider = "groq"
            args.remove("--groq")
        elif "--openrouter" in args:
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

    if target.lower() in ("status", "credito", "creditos", "saldo"):
        show_credits_dashboard(cfg)
        sys.exit(0)

    if target:
        process_manga(target, ocr_mode=chosen_mode, force_ocr=force_ocr_flag, retranslate=retranslate_flag, is_adult=is_adult_flag, config=cfg)
    else:
        print("[!] Nenhuma pasta informada.")
