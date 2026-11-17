# -*- coding: utf-8 -*-
"""
balloon_cavity.py - Detecção de Cavidade Fechada, Fusão por Balão e Limpeza Completa
Detecta o interior real de balões fechados, une caixas OCR do mesmo balão,
impede fusão com texto fora do balão e apaga 100% dos resquícios originais.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import cv2
import numpy as np


def build_balloon_map(img):
    """
    Mapeia todos os balões claros fechados da página em um mapa de IDs (1..N).
    Aceita imagem BGR (3 canais) ou escala de cinza (2D).
    Retorna (balloon_id_map, balloon_infos).
    """
    if img is None or img.size == 0:
        return np.zeros((1, 1), dtype=np.int32), {}

    is_bgr = (img.ndim == 3 and img.shape[2] >= 3)
    ih, iw = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if is_bgr else img

    if is_bgr:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        bright = ((gray >= 216) & (hsv[:, :, 1] <= 42)).astype(np.uint8) * 255
    else:
        bright = (gray >= 216).astype(np.uint8) * 255

    # Fecha micro-frestas de 3px sem unir balões vizinhos
    bright_closed = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    n_lbl, labels, stats, _ = cv2.connectedComponentsWithStats(bright_closed)
    id_map = np.zeros((ih, iw), dtype=np.int32)
    infos = {}
    next_id = 1
    page_area = float(ih * iw)

    for lbl in range(1, n_lbl):
        bx, by, bw, bh, area = [int(v) for v in stats[lbl]]
        if area < 900 or bw < 28 or bh < 22:
            continue
        if area > page_area * 0.28:
            continue

        px0, py0 = max(0, bx - 2), max(0, by - 2)
        px1, py1 = min(iw, bx + bw + 2), min(ih, by + bh + 2)
        comp_local = (labels[py0:py1, px0:px1] == lbl).astype(np.uint8)

        # Flood-fill externo fecha 100% dos furos internos (letras escuras e coloridas)
        inv = ((comp_local == 0).astype(np.uint8) * 255)
        pad_inv = cv2.copyMakeBorder(inv, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=255)
        ff_mask = np.zeros((pad_inv.shape[0] + 2, pad_inv.shape[1] + 2), np.uint8)
        cv2.floodFill(pad_inv, ff_mask, (0, 0), 128)
        holes = (pad_inv[1:-1, 1:-1] == 255).astype(np.uint8)
        filled_local = (comp_local | holes).astype(np.uint8)

        touches_page = sum([
            1 if bx <= 2 else 0,
            1 if by <= 2 else 0,
            1 if (bx + bw) >= iw - 2 else 0,
            1 if (by + bh) >= ih - 2 else 0,
        ])
        filled_area = int(np.sum(filled_local > 0))
        if touches_page >= 3 or filled_area > page_area * 0.28:
            continue

        fill_bgr = (255, 255, 255)
        if is_bgr:
            roi_bgr = img[py0:py1, px0:px1]
            bg_px = roi_bgr[comp_local > 0]
            if bg_px.size >= 12:
                med = np.median(bg_px, axis=0)
                b_v, g_v, r_v = int(round(med[0])), int(round(med[1])), int(round(med[2]))
                if min(b_v, g_v, r_v) >= 245 and (max(b_v, g_v, r_v) - min(b_v, g_v, r_v)) <= 8:
                    fill_bgr = (255, 255, 255)
                else:
                    fill_bgr = (b_v, g_v, r_v)

        ys, xs = np.where(filled_local > 0)
        if ys.size == 0:
            continue
        fx0, fx1 = px0 + int(xs.min()), px0 + int(xs.max()) + 1
        fy0, fy1 = py0 + int(ys.min()), py0 + int(ys.max()) + 1

        id_map[py0:py1, px0:px1][filled_local > 0] = next_id
        infos[next_id] = {
            "id": next_id,
            "bbox": (fx0, fy0, fx1, fy1),
            "local_origin": (px0, py0),
            "local_mask": filled_local,
            "fill_bgr": fill_bgr,
            "area": filled_area,
        }
        next_id += 1

    return id_map, infos


def find_box_balloon_id(box, id_map, min_overlap=0.35):
    """Identifica a qual balão fechado (ID > 0) uma caixa OCR pertence, ou 0 se fora de balão."""
    if id_map is None or id_map.size <= 1:
        return 0
    ih, iw = id_map.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(iw, x1), min(ih, y1)
    if x1 <= x0 or y1 <= y0:
        return 0

    crop = id_map[y0:y1, x0:x1]
    nonzero = crop[crop > 0]
    if nonzero.size == 0:
        return 0

    vals, counts = np.unique(nonzero, return_counts=True)
    best_idx = int(np.argmax(counts))
    ratio = float(counts[best_idx]) / float(crop.size)
    return int(vals[best_idx]) if ratio >= min_overlap else 0


def sweep_balloon_interior(cleaned_bgr, balloon_info, erode_px=2):
    """
    Varre e limpa 100% da cavidade interna de um balão fechado com margem segura
    da borda preta, apagando letras órfãs ('I', 'UP', 'A', rosa, cinza) sem tocar no contorno.
    """
    px0, py0 = balloon_info["local_origin"]
    local_mask = balloon_info["local_mask"]
    fill_bgr = balloon_info["fill_bgr"]
    lh, lw = local_mask.shape

    k_size = max(3, (erode_px * 2) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_size, k_size))
    safe_inner = cv2.erode(local_mask, kernel, iterations=1)
    if np.sum(safe_inner > 0) < 32:
        safe_inner = local_mask

    roi = cleaned_bgr[py0:py0 + lh, px0:px0 + lw]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    bg_luma = int(round(0.114 * fill_bgr[0] + 0.587 * fill_bgr[1] + 0.299 * fill_bgr[2]))

    luma_diff = bg_luma - gray.astype(np.int16)
    is_residue = (luma_diff > 16) | ((hsv[:, :, 1] > 20) & (gray < min(246, bg_luma - 4)))
    erase_mask = (safe_inner > 0) & is_residue

    erase_u8 = (erase_mask.astype(np.uint8) * 255)
    erase_u8 = cv2.dilate(erase_u8, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)
    erase_u8 &= (safe_inner * 255)

    roi[erase_u8 > 0] = fill_bgr
    return int(np.sum(erase_u8 > 0))


def compute_safe_text_region(balloon_info, pad_x=14, pad_y=12):
    """
    Calcula o retângulo seguro e o perfil de largura por altura (band_profile)
    cortando rabichos estreitos do balão para diagramação centralizada perfeita.
    """
    px0, py0 = balloon_info["local_origin"]
    local_mask = balloon_info["local_mask"]
    lh, lw = local_mask.shape

    k_tail = max(9, min(19, int(min(lh, lw) * 0.22) | 1))
    body = cv2.morphologyEx(
        local_mask, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_tail, k_tail))
    )
    if np.sum(body > 0) < 64:
        body = local_mask

    n_l, lbls, st, _ = cv2.connectedComponentsWithStats(body)
    if n_l > 1:
        best = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        body = (lbls == best).astype(np.uint8)

    ys, xs = np.where(body > 0)
    if ys.size == 0:
        bx0, by0, bx1, by1 = balloon_info["bbox"]
        return {
            "safe_cx": (bx0 + bx1) / 2.0,
            "safe_cy": (by0 + by1) / 2.0,
            "target_w": max(32.0, float(bx1 - bx0 - 2 * pad_x)),
            "target_h": max(24.0, float(by1 - by0 - 2 * pad_y)),
            "band_profile": None,
            "safe_min_y": float(by0 + pad_y),
            "safe_max_y": float(by1 - pad_y),
        }

    min_y, max_y = int(ys.min()), int(ys.max())
    min_x, max_x = int(xs.min()), int(xs.max())
    body_h = max(1, max_y - min_y + 1)
    body_w = max(1, max_x - min_x + 1)

    eff_pad_y = min(pad_y, max(4, int(body_h * 0.08))) if body_h < 110 else min(pad_y, max(6, int(body_h * 0.10)))
    eff_pad_x = min(pad_x, max(6, int(body_w * 0.06)))

    sy0 = min_y + eff_pad_y
    sy1 = max(sy0 + 12, max_y - eff_pad_y)

    profile = []
    cx_samples = []
    for k in range(9):
        frac = k / 8.0
        yy = min(lh - 1, max(0, int(round(sy0 + frac * (sy1 - sy0)))))
        row_xs = np.where(body[yy, :] > 0)[0]
        if row_xs.size >= 4:
            rw = max(24.0, float(row_xs.max() - row_xs.min() + 1) - 2.0 * eff_pad_x)
            profile.append((frac, rw))
            if 0.25 <= frac <= 0.75:
                cx_samples.append(px0 + (float(row_xs.min()) + float(row_xs.max())) / 2.0)

    safe_cx = float(np.median(cx_samples)) if cx_samples else (px0 + (min_x + max_x) / 2.0)
    safe_cy = py0 + (sy0 + sy1) / 2.0
    max_w = max(32.0, max((w for _, w in profile), default=float(body_w - 2 * eff_pad_x)))
    max_h = max(24.0, float(sy1 - sy0 + 1))

    return {
        "safe_cx": safe_cx,
        "safe_cy": safe_cy,
        "target_w": max_w,
        "target_h": max_h,
        "band_profile": profile if len(profile) >= 3 else None,
        "safe_min_y": float(py0 + sy0),
        "safe_max_y": float(py0 + sy1),
    }
