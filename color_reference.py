"""
color_reference.py - Módulo de Referência e Ancoragem Cromática de Mangás
Permite transferir o estilo, paleta e tons canônicos de personagens a partir de:
- Outro capítulo colorido da mesma obra (ex: Lesson 6 colorido -> Lesson 9 P&B)
- Capas ou ilustrações coloridas avulsas
Regra de Ouro: Modular, coeso e estritamente < 300 linhas.
"""

import os
import io
import zipfile
import numpy as np
import cv2
from PIL import Image


def _extract_stats_from_bgr(img_bgr):
    """Extrai média e desvio padrão dos canais a* e b* (Lab) ignorando papel branco e nanquim preto."""
    if img_bgr is None or img_bgr.size == 0:
        return None
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)
    # Isola pixels com cor real (descarta nanquim preto puro L<25 e fundo papel branco L>240)
    mask = (lab[:, :, 0] > 25) & (lab[:, :, 0] < 240)
    # Verifica saturação mínima para não incluir cinzas neutros
    chroma = np.sqrt((lab[:, :, 1] - 128.0) ** 2 + (lab[:, :, 2] - 128.0) ** 2)
    valid_mask = mask & (chroma > 3.0)
    if np.count_nonzero(valid_mask) < 200:
        # Se não há pixels saturados suficientes, usa máscara de luminância básica
        valid_mask = mask
    if np.count_nonzero(valid_mask) < 50:
        return None
    return lab[valid_mask]


def extract_reference_profile(reference_input, max_samples=5):
    """Extrai o perfil cromático a partir de pasta, imagem avulsa, arquivo .zip/.cbz ou array.
    Retorna dicionário com mean_a, std_a, mean_b, std_b e metadados.
    """
    if reference_input is None:
        return None

    if isinstance(reference_input, dict) and "mean_a" in reference_input:
        return reference_input

    collected_pixels = []
    source_label = "memória"

    # Caso 1: Array OpenCV
    if isinstance(reference_input, np.ndarray):
        source_label = "array numpy"
        pix = _extract_stats_from_bgr(reference_input)
        if pix is not None:
            collected_pixels.append(pix)

    # Caso 2: PIL.Image
    elif isinstance(reference_input, Image.Image):
        source_label = "PIL.Image"
        bgr = cv2.cvtColor(np.array(reference_input.convert("RGB")), cv2.COLOR_RGB2BGR)
        pix = _extract_stats_from_bgr(bgr)
        if pix is not None:
            collected_pixels.append(pix)

    # Caso 3: Caminho em disco (arquivo ou pasta)
    elif isinstance(reference_input, str):
        path = os.path.abspath(reference_input.strip("\"'"))
        source_label = os.path.basename(path)
        if not os.path.exists(path):
            return None

        # 3.1: Pasta com páginas coloridas
        if os.path.isdir(path):
            exts = (".webp", ".jpg", ".jpeg", ".png", ".bmp")
            files = [f for f in os.listdir(path) if f.lower().endswith(exts)]
            if not files:
                return None
            # Amostra páginas representativas (início, meio e fim)
            step = max(1, len(files) // max_samples)
            sampled = files[::step][:max_samples]
            for fname in sampled:
                fpath = os.path.join(path, fname)
                with open(fpath, "rb") as f:
                    buf = np.asarray(bytearray(f.read()), dtype=np.uint8)
                    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                pix = _extract_stats_from_bgr(img)
                if pix is not None:
                    collected_pixels.append(pix)

        # 3.2: Arquivo compactado (.zip ou .cbz)
        elif path.lower().endswith((".zip", ".cbz")):
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    exts = (".webp", ".jpg", ".jpeg", ".png", ".bmp")
                    names = [n for n in zf.namelist() if n.lower().endswith(exts)]
                    step = max(1, len(names) // max_samples)
                    sampled = names[::step][:max_samples]
                    for name in sampled:
                        with zf.open(name) as f:
                            buf = np.asarray(bytearray(f.read()), dtype=np.uint8)
                            img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                        pix = _extract_stats_from_bgr(img)
                        if pix is not None:
                            collected_pixels.append(pix)
            except Exception:
                return None

        # 3.3: Imagem avulsa (capa ou character sheet)
        elif os.path.isfile(path):
            with open(path, "rb") as f:
                buf = np.asarray(bytearray(f.read()), dtype=np.uint8)
                img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            pix = _extract_stats_from_bgr(img)
            if pix is not None:
                collected_pixels.append(pix)

    if not collected_pixels:
        return None

    all_lab = np.vstack(collected_pixels)
    profile = {
        "mean_a": float(np.mean(all_lab[:, 1])),
        "std_a": float(np.std(all_lab[:, 1]) + 1e-5),
        "mean_b": float(np.mean(all_lab[:, 2])),
        "std_b": float(np.std(all_lab[:, 2]) + 1e-5),
        "source": source_label,
        "sample_count": len(collected_pixels),
    }
    return profile


def apply_reference_transfer(colored_bgr, profile, strength=0.85):
    """Aplica o mapeamento cromático Lab guiado pelo perfil de referência.
    - colored_bgr: imagem BGR colorizada pela rede neural
    - profile: dicionário gerado por extract_reference_profile
    - strength: intensidade do ajuste (0.0 = sem alteração; 1.0 = transferência total)
    """
    if profile is None or strength <= 0.0:
        return colored_bgr

    strength = min(max(float(strength), 0.0), 1.0)
    c_lab = cv2.cvtColor(colored_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)
    mask = (c_lab[:, :, 0] > 25) & (c_lab[:, :, 0] < 240)

    if np.count_nonzero(mask) < 50:
        return colored_bgr

    c_a_mean = float(np.mean(c_lab[mask, 1]))
    c_a_std = float(np.std(c_lab[mask, 1]) + 1e-5)
    c_b_mean = float(np.mean(c_lab[mask, 2]))
    c_b_std = float(np.std(c_lab[mask, 2]) + 1e-5)

    ref_a_mean = profile["mean_a"]
    ref_a_std = profile["std_a"]
    ref_b_mean = profile["mean_b"]
    ref_b_std = profile["std_b"]

    target_a = ((c_lab[:, :, 1] - c_a_mean) * (ref_a_std / c_a_std)) + ref_a_mean
    target_b = ((c_lab[:, :, 2] - c_b_mean) * (ref_b_std / c_b_std)) + ref_b_mean

    res_lab = c_lab.copy()
    res_lab[:, :, 1] = (1.0 - strength) * c_lab[:, :, 1] + strength * target_a
    res_lab[:, :, 2] = (1.0 - strength) * c_lab[:, :, 2] + strength * target_b

    res_bgr = cv2.cvtColor(np.clip(res_lab, 0, 255).astype(np.uint8), cv2.COLOR_Lab2BGR)
    return res_bgr


def find_automatic_reference(folder_path):
    """Busca automaticamente se existe pasta ou arquivo de referência colorido na mesma obra."""
    if not folder_path or not os.path.exists(folder_path):
        return None
    parent = os.path.dirname(os.path.abspath(folder_path))
    base = os.path.basename(os.path.abspath(folder_path))
    clean = base.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip()

    # 1. Procura por arquivos de capa ou referência explícitos
    cand_files = ["cover_color.jpg", "cover.jpg", "reference.jpg", "ref.png"]
    for cf in cand_files:
        p = os.path.join(folder_path, cf)
        if os.path.exists(p):
            return p

    # 2. Procura por pastas irmãs coloridas no mesmo diretório
    if os.path.isdir(parent):
        for item in os.listdir(parent):
            if item == base:
                continue
            item_p = os.path.join(parent, item)
            if os.path.isdir(item_p) and clean.lower() in item.lower():
                if any(w in item.lower() for w in ("color", "colorido", "colored", "c_")):
                    return item_p
    return None
