"""
balloon_color.py - Balões COLORIDOS (rosa, azul, amarelo, cinza médio) que o mapa de balões brancos ignora.
Parte da caixa OCR: pega a cor do fundo entre as letras, segue a mancha dessa cor e só aceita se ela
for fechada (não encosta na janela de busca), compacta e com borda diferente do fundo.
A limpeza recompõe por inpainting apenas os "furos" da mancha (letras, inclusive as que o OCR não pegou).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import cv2
import numpy as np

TOL = 24            # diferença máxima por canal (BGR) para contar como "mesma cor do balão"
MIN_LUMA = 135      # balões escuros (texto branco) ficam com a limpeza normal
MAX_HOLES = 0.30    # letras ocupam bem menos que isso; rostos e desenhos ocupam mais
MIN_RECT_FILL = 0.46
MIN_SOLIDITY = 0.76
MIN_RING = 0.72


def _luma(bgr):
    return 0.114 * bgr[0] + 0.587 * bgr[1] + 0.299 * bgr[2]


def _close_holes(comp):
    inv = ((comp == 0).astype(np.uint8) * 255)
    pad = cv2.copyMakeBorder(inv, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=255)
    ff = np.zeros((pad.shape[0] + 2, pad.shape[1] + 2), np.uint8)
    cv2.floodFill(pad, ff, (0, 0), 128)
    holes = (pad[1:-1, 1:-1] == 255).astype(np.uint8)
    return (comp | holes).astype(np.uint8), holes


def background_color(img, box):
    """Cor do fundo entre as letras da caixa OCR, ou None se o fundo não for uniforme."""
    ih, iw = img.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(iw, x1), min(ih, y1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    roi = img[y0:y1, x0:x1].reshape(-1, 3).astype(np.int16)
    gray = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).ravel()
    cand = roi[gray >= np.percentile(gray, 70) - 12]
    if cand.shape[0] < 30:
        return None
    med = np.median(cand, axis=0)
    if np.mean(np.max(np.abs(roi - med), axis=1) <= TOL) < 0.45:
        return None
    return med


def is_plain_white(bgr):
    """Fundo branco/cinza claro: já é tratado por balloon_cavity.build_balloon_map."""
    b, g, r = [float(v) for v in bgr]
    return _luma(bgr) >= 216 and (max(b, g, r) - min(b, g, r)) <= 30


def _closed_component(img, med, box, pad):
    """Mancha da cor `med` que cobre a caixa: (comp, origem, bbox local, janela), "open" se encosta
    na janela de busca (pode ser fundo do quadro) ou None se não há mancha."""
    ih, iw = img.shape[:2]
    x0, y0, x1, y1 = box
    wx0, wy0, wx1, wy1 = max(0, x0 - pad), max(0, y0 - pad), min(iw, x1 + pad), min(ih, y1 + pad)
    win = img[wy0:wy1, wx0:wx1]
    match = (np.max(np.abs(win.astype(np.int16) - med), axis=2) <= TOL).astype(np.uint8)
    n, labels, _, _ = cv2.connectedComponentsWithStats(match, connectivity=4)
    inner = labels[max(0, y0 - wy0):y1 - wy0, max(0, x0 - wx0):x1 - wx0]
    vals, counts = np.unique(inner[inner > 0], return_counts=True)
    if n <= 1 or vals.size == 0:
        return None
    comp = (labels == int(vals[np.argmax(counts)])).astype(np.uint8)
    ys, xs = np.where(comp > 0)
    cx0, cx1, cy0, cy1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    wh, ww = comp.shape
    if (cx0 == 0 and wx0 > 0) or (cy0 == 0 and wy0 > 0) or (cx1 == ww - 1 and wx1 < iw) or (cy1 == wh - 1 and wy1 < ih):
        return "open"
    if sum([cx0 == 0, cy0 == 0, cx1 == ww - 1, cy1 == wh - 1]) >= 2:
        return None  # encosta em dois cantos da página
    return comp, (wx0, wy0), (cx0, cy0, cx1, cy1), win


def detect_color_balloon(img, box, text_boxes=None):
    """Devolve um info no formato de balloon_cavity (bbox, local_origin, local_mask, fill_bgr, area)
    com "kind": "color" e "erase_mask", ou None quando não há um balão colorido fechado seguro."""
    if img is None or img.ndim != 3 or not box or len(box) != 4:
        return None
    med = background_color(img, box)
    if med is None or _luma(med) < MIN_LUMA or is_plain_white(med):
        return None

    x0, y0, x1, y1 = [int(round(v)) for v in box]
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    found = None
    for scale in (1.5, 3.0):  # janela maior antes de concluir que a mancha é aberta
        pad = int(max(60, max(bw, bh) * scale))
        found = _closed_component(img, med, (x0, y0, x1, y1), pad)
        if found != "open":
            break
    if found is None or found == "open":
        return None
    comp, (wx0, wy0), (cx0, cy0, cx1, cy1), win = found

    filled, holes = _close_holes(comp)
    filled_area = int(filled.sum())
    holes_area = int(holes.sum())
    if filled_area < 900 or holes_area / float(max(1, filled_area)) > MAX_HOLES:
        return None
    fbw, fbh = cx1 - cx0 + 1, cy1 - cy0 + 1
    if filled_area / float(fbw * fbh) < MIN_RECT_FILL:
        return None
    cnts, _ = cv2.findContours(filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = float(cv2.contourArea(cv2.convexHull(max(cnts, key=cv2.contourArea))))
    solidity = filled_area / max(1.0, hull)
    if solidity < MIN_SOLIDITY:
        return None

    ring = (cv2.dilate(filled, np.ones((7, 7), np.uint8)) - filled) > 0
    if np.any(ring):
        ring_diff = np.max(np.abs(win.astype(np.int16) - med), axis=2)[ring] > TOL
        if float(np.mean(ring_diff)) < MIN_RING:
            return None

    # Furos longe do texto (olhos, desenhos) indicam que a mancha não é um balão de fala
    near_text = np.zeros_like(filled)
    for tb in (text_boxes or [box]):
        tx0, ty0, tx1, ty1 = [int(round(v)) for v in tb]
        near_text[max(0, ty0 - wy0 - 14):max(0, ty1 - wy0 + 14), max(0, tx0 - wx0 - 14):max(0, tx1 - wx0 + 14)] = 1
    if holes_area > 0 and float(np.sum(holes & (near_text == 0))) / holes_area > 0.35:
        return None

    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    erase = cv2.dilate(holes * 255, k5, iterations=1) & (cv2.erode(filled, np.ones((3, 3), np.uint8)) * 255)
    fill_bgr = tuple(int(round(v)) for v in med)
    return {
        "id": 0, "kind": "color",
        "bbox": (wx0 + cx0, wy0 + cy0, wx0 + cx1 + 1, wy0 + cy1 + 1),
        "local_origin": (wx0, wy0), "local_mask": filled, "erase_mask": erase,
        "fill_bgr": fill_bgr, "area": filled_area, "solidity": solidity,
    }


def contains_point(info, x, y):
    px0, py0 = info["local_origin"]
    mask = info["local_mask"]
    lx, ly = int(round(x)) - px0, int(round(y)) - py0
    return 0 <= ly < mask.shape[0] and 0 <= lx < mask.shape[1] and bool(mask[ly, lx])


def sweep_color_balloon(cleaned_bgr, info):
    """Recompõe as letras do balão colorido com a cor ao redor (preserva degradês suaves)."""
    px0, py0 = info["local_origin"]
    erase = info["erase_mask"]
    lh, lw = erase.shape
    if not np.any(erase):
        return 0
    roi = cleaned_bgr[py0:py0 + lh, px0:px0 + lw]
    roi[:] = cv2.inpaint(roi, erase, inpaintRadius=4, flags=cv2.INPAINT_TELEA)
    return int(np.sum(erase > 0))
