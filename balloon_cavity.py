# -*- coding: utf-8 -*-
"""
balloon_cavity.py - Detecção Segura de Cavidade de Balão (Mangás P&B e Coloridos)
Aplica 5 travas anti-vazamento (área máxima, solidez convexa, proporção de furos,
contorno escuro fechado e distância proporcional ao OCR) para JAMAIS apagar rostos,
cabelos ou roupas em mangás preto e branco.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import cv2
import numpy as np


def build_balloon_map(img):
    """
    Mapeia apenas balões claros ESTRITAMENTE FECHADOS e compactos da página.
    Rejeita cabelos brancos, fundos abertos e balões sem borda que encostam em personagens.
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
        hsv = None
        bright = (gray >= 216).astype(np.uint8) * 255

    # Não dilata demais para jamais romper linhas finas de cabelo/rosto em mangá P&B
    n_lbl, labels, stats, _ = cv2.connectedComponentsWithStats(bright)
    id_map = np.zeros((ih, iw), dtype=np.int32)
    infos = {}
    next_id = 1
    page_area = float(ih * iw)

    for lbl in range(1, n_lbl):
        bx, by, bw, bh, area = [int(v) for v in stats[lbl]]
        if area < 900 or bw < 28 or bh < 22:
            continue
        # Trava 1: nenhum balão individual ocupa > 14% da página inteira
        if area > page_area * 0.14 or bw > iw * 0.72 or bh > ih * 0.48:
            continue

        px0, py0 = max(0, bx - 4), max(0, by - 4)
        px1, py1 = min(iw, bx + bw + 4), min(ih, by + bh + 4)
        comp_local = (labels[py0:py1, px0:px1] == lbl).astype(np.uint8)

        # Flood-fill externo fecha furos internos (letras)
        inv = ((comp_local == 0).astype(np.uint8) * 255)
        pad_inv = cv2.copyMakeBorder(inv, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=255)
        ff_mask = np.zeros((pad_inv.shape[0] + 2, pad_inv.shape[1] + 2), np.uint8)
        cv2.floodFill(pad_inv, ff_mask, (0, 0), 128)
        holes = (pad_inv[1:-1, 1:-1] == 255).astype(np.uint8)
        filled_local = (comp_local | holes).astype(np.uint8)

        filled_area = int(np.sum(filled_local > 0))
        holes_area = int(np.sum(holes > 0))
        if filled_area > page_area * 0.14:
            continue

        # Trava 2: proporção máxima de furos internos (texto ocupa < 26%; rostos/arte ocupam muito mais)
        if (holes_area / float(max(1, filled_area))) > 0.26:
            continue

        # Trava 3: solidez convexa e compactação (rejeita mechas de cabelo branco e vazamentos irregulares)
        rect_fill = filled_area / float(max(1, bw * bh))
        if rect_fill < 0.46:
            continue

        cnts, _ = cv2.findContours(filled_local, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        main_cnt = max(cnts, key=cv2.contourArea)
        hull_area = float(cv2.contourArea(cv2.convexHull(main_cnt)))
        solidity = filled_area / max(1.0, hull_area)
        if solidity < 0.76:
            continue

        touches_page = sum([
            1 if bx <= 2 else 0,
            1 if by <= 2 else 0,
            1 if (bx + bw) >= iw - 2 else 0,
            1 if (by + bh) >= ih - 2 else 0,
        ])
        if touches_page >= 3:
            continue

        # Trava 4: verifica perímetro escuro/colorido fechado ao redor do balão
        ring = cv2.dilate(filled_local, np.ones((7, 7), np.uint8), iterations=1) - filled_local
        ring_mask = ring > 0
        if np.any(ring_mask):
            g_roi = gray[py0:py1, px0:px1]
            dark_ring = (g_roi < 195)
            if hsv is not None:
                h_roi = hsv[py0:py1, px0:px1]
                dark_ring = dark_ring | (h_roi[:, :, 1] > 38)
            border_dark_ratio = float(np.mean(dark_ring[ring_mask]))
            if border_dark_ratio < 0.72:
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
            "solidity": solidity,
        }
        next_id += 1

    return id_map, infos


def is_balloon_safe_for_box(balloon_info, box):
    """
    Trava 5: valida que o balão detectado tem proporção e centro coerentes com a caixa OCR.
    Impede qualquer varredura caso o balão seja desproporcionalmente maior que o texto.
    """
    if not balloon_info or not box or len(box) != 4:
        return False
    bx0, by0, bx1, by1 = balloon_info["bbox"]
    ox0, oy0, ox1, oy1 = [float(v) for v in box]
    bw_bal, bh_bal = max(1.0, float(bx1 - bx0)), max(1.0, float(by1 - by0))
    bw_ocr, bh_ocr = max(1.0, ox1 - ox0), max(1.0, oy1 - oy0)

    if bw_bal > max(bw_ocr * 2.5, bw_ocr + 180.0):
        return False
    if bh_bal > max(bh_ocr * 2.5, bh_ocr + 160.0):
        return False

    ocr_area = bw_ocr * bh_ocr
    if balloon_info.get("area", bw_bal * bh_bal) > max(ocr_area * 5.0, 65000.0):
        return False

    bal_cx, bal_cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
    ocr_cx, ocr_cy = (ox0 + ox1) / 2.0, (oy0 + oy1) / 2.0
    if abs(bal_cx - ocr_cx) > max(bw_ocr * 0.90, 110.0):
        return False
    if abs(bal_cy - ocr_cy) > max(bh_ocr * 0.90, 110.0):
        return False
    return True


def find_box_balloon_id(box, id_map, min_overlap=0.35, infos=None):
    """Identifica o balão fechado válido (ID > 0) de uma caixa OCR, ou 0 se inseguro/externo."""
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
    if ratio < min_overlap:
        return 0
    bid = int(vals[best_idx])
    if infos is not None and bid in infos and not is_balloon_safe_for_box(infos[bid], box):
        return 0
    return bid


def sweep_balloon_interior(cleaned_bgr, balloon_info, erode_px=2):
    """
    Varre a cavidade interna de um balão fechado VALIDADO preservando o contorno preto.
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
    """Calcula retângulo seguro e perfil de largura cortando rabichos do balão."""
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
            "safe_cx": (bx0 + bx1) / 2.0, "safe_cy": (by0 + by1) / 2.0,
            "target_w": max(32.0, float(bx1 - bx0 - 2 * pad_x)),
            "target_h": max(24.0, float(by1 - by0 - 2 * pad_y)),
            "band_profile": None, "safe_min_y": float(by0 + pad_y), "safe_max_y": float(by1 - pad_y),
        }

    min_y, max_y = int(ys.min()), int(ys.max())
    min_x, max_x = int(xs.min()), int(xs.max())
    body_h, body_w = max(1, max_y - min_y + 1), max(1, max_x - min_x + 1)

    eff_pad_y = min(pad_y, max(4, int(body_h * 0.08))) if body_h < 110 else min(pad_y, max(6, int(body_h * 0.10)))
    eff_pad_x = min(pad_x, max(6, int(body_w * 0.06)))
    sy0, sy1 = min_y + eff_pad_y, max(min_y + eff_pad_y + 12, max_y - eff_pad_y)

    profile, cx_samples = [], []
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
        "safe_cx": safe_cx, "safe_cy": safe_cy,
        "target_w": max_w, "target_h": max_h,
        "band_profile": profile if len(profile) >= 3 else None,
        "safe_min_y": float(py0 + sy0), "safe_max_y": float(py0 + sy1),
    }
