"""
ocr_recover.py - Resgata colunas de texto que o detector do OCR não achou, dentro de balões que já têm fala.

Caso real (pág 15): no balão "どーしても見たいの!!" o detector PP-OCRv6 achou só "見たいの!!". A coluna
"どーしても", grande e nítida, ficou sem caixa: não era traduzida e, sem a varredura do balão, continuava
em japonês ao lado da tradução. Aqui, em cada balão fechado com pelo menos uma fala, a tinta que nenhuma caixa
cobre vira um recorte que vai só para o reconhecedor (a detecção é que falhou, não a leitura).
Desenhos dentro do balão (lâmpada, coração, gotas) quase nunca passam: exige tamanho de letra, 2+ caracteres
japoneses e confiança alta.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import re

import cv2
import numpy as np

import balloon_cavity

_JA = re.compile(r"[぀-ヿ一-鿿]")
MIN_SCORE = 0.80


def _ink_mask(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    colored = (hsv[:, :, 1] > 90) & (hsv[:, :, 2] < 235)  # texto azul/rosa das falas
    return ((gray < 150) | colored).astype(np.uint8)


def find_uncovered_columns(img_bgr, boxes, id_map=None, infos=None):
    """Caixas [x0, y0, x1, y1] de tinta sem caixa OCR dentro de balões que já têm fala (forma de coluna)."""
    if img_bgr is None or img_bgr.size == 0 or not boxes:
        return []
    if id_map is None or infos is None:
        id_map, infos = balloon_cavity.build_balloon_map(img_bgr)
    ih, iw = img_bgr.shape[:2]
    ink = _ink_mask(img_bgr)
    covered = np.zeros((ih, iw), np.uint8)
    char_hs = []
    for b in boxes:
        x0, y0, x1, y1 = [int(round(v)) for v in b]
        covered[max(0, y0 - 8):min(ih, y1 + 8), max(0, x0 - 8):min(iw, x1 + 8)] = 1
        char_hs.append(min(x1 - x0, y1 - y0))
    char = float(np.median(char_hs)) if char_hs else 30.0
    used_bids = set()
    for b in boxes:
        cx, cy = int((b[0] + b[2]) / 2), int((b[1] + b[3]) / 2)
        if 0 <= cy < ih and 0 <= cx < iw and id_map[cy, cx] > 0:
            used_bids.add(int(id_map[cy, cx]))
    out = []
    for bid in used_bids:
        info = infos.get(bid)
        if not info:
            continue
        px0, py0 = info["local_origin"]
        lmask = info["local_mask"]
        lh, lw = lmask.shape
        inner = cv2.erode(lmask, np.ones((9, 9), np.uint8))  # longe do contorno do balão
        roi_ink = ink[py0:py0 + lh, px0:px0 + lw] & inner & (1 - covered[py0:py0 + lh, px0:px0 + lw])
        if int(roi_ink.sum()) < 120:
            continue
        k = max(5, int(char * 0.6)) | 1
        joined = cv2.dilate(roi_ink, cv2.getStructuringElement(cv2.MORPH_RECT, (3, k)))  # junta letras da coluna
        n, _, stats, _ = cv2.connectedComponentsWithStats(joined)
        for i in range(1, n):
            x, y, w, h, area = [int(v) for v in stats[i]]
            if h < max(40, char * 1.5) or w < max(14, char * 0.45) or w > char * 2.2 or h < w * 1.4:
                continue
            out.append([px0 + x, py0 + y, px0 + x + w, py0 + y + h])
    return out


def recover_blocks(img_bgr, blocks, recognize_crop):
    """Blocos novos {"box", "text"} para as colunas resgatadas. recognize_crop(crop) -> (texto, confiança)."""
    try:
        cols = find_uncovered_columns(img_bgr, [b["box"] for b in blocks])
    except Exception:
        return []
    found = []
    for x0, y0, x1, y1 in cols:
        crop = img_bgr[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4]
        try:
            text, score = recognize_crop(crop)
        except Exception:
            continue
        text = str(text or "").strip()
        if score >= MIN_SCORE and len(_JA.findall(text)) >= 2:
            found.append({"box": [float(x0), float(y0), float(x1), float(y1)], "text": text})
    return found
