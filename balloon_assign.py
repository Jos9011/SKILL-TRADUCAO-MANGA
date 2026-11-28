"""
balloon_assign.py - Liga cada fala da página ao seu balão para a limpeza completa da cavidade.
A Trava 5 (balloon_cavity.is_balloon_safe_for_box) compara o balão com UMA caixa OCR e rejeitava
balões altos com pouco texto e balões com duas falas (25 de 37 na página de teste). Aqui a
comparação usa a união de todas as falas do mesmo balão e limites mais folgados; as Travas 1-4
do mapa (fechado, compacto, poucos furos, borda escura) continuam valendo.
Balões coloridos entram por balloon_color quando o mapa de balões claros não acha nada.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import cv2
import numpy as np

import balloon_cavity
import balloon_color


def raw_balloon_id(box, id_map, min_overlap=0.35):
    """ID do balão que cobre a maior parte da caixa, sem a Trava 5 (0 se nenhum)."""
    if id_map is None or id_map.size <= 1 or not box:
        return 0
    ih, iw = id_map.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(iw, x1), min(ih, y1)
    if x1 <= x0 or y1 <= y0:
        return 0
    crop = id_map[y0:y1, x0:x1]
    nz = crop[crop > 0]
    if nz.size == 0:
        return 0
    vals, counts = np.unique(nz, return_counts=True)
    best = int(np.argmax(counts))
    return int(vals[best]) if counts[best] / float(crop.size) >= min_overlap else 0


def _union(boxes):
    xs0, ys0, xs1, ys1 = zip(*[[float(v) for v in b] for b in boxes])
    return [min(xs0), min(ys0), max(xs1), max(ys1)]


def balloon_fits_text(info, box):
    """Trava 5 folgada: o balão pode ser bem mais alto que o texto (balões ovais estreitos),
    mas não muito mais largo nem com área desproporcional, e o texto precisa estar perto do centro."""
    if balloon_cavity.is_balloon_safe_for_box(info, box):
        return True
    bx0, by0, bx1, by1 = info["bbox"]
    ox0, oy0, ox1, oy1 = [float(v) for v in box]
    bwb, bhb = max(1.0, bx1 - bx0), max(1.0, by1 - by0)
    bwo, bho = max(1.0, ox1 - ox0), max(1.0, oy1 - oy0)
    if bwb > max(bwo * 2.5, bwo + 180.0) or bhb > max(bho * 4.0, bho + 300.0):
        return False
    if info.get("area", bwb * bhb) > max(bwo * bho * 8.0, 90000.0):
        return False
    if abs((bx0 + bx1) / 2.0 - (ox0 + ox1) / 2.0) > max(bwo * 0.9, 110.0):
        return False
    return abs((by0 + by1) / 2.0 - (oy0 + oy1) / 2.0) <= max(bho * 0.9, 110.0)


def assign_balloon_ids(boxes, id_map, infos, img=None):
    """Lista de IDs de balão (0 = sem balão seguro), um por caixa. Balões coloridos detectados
    recebem IDs novos e entram em `infos` com "kind": "color"."""
    raw = [raw_balloon_id(b, id_map) for b in boxes]
    groups = {}
    for box, bid in zip(boxes, raw):
        if bid > 0 and bid in infos:
            groups.setdefault(bid, []).append(box)
    ok = {bid for bid, bxs in groups.items() if balloon_fits_text(infos[bid], _union(bxs))}
    bids = [bid if bid in ok else 0 for bid in raw]
    if img is None or getattr(img, "ndim", 0) != 3:
        return bids

    next_id = max(list(infos.keys()) + [0]) + 1
    color_ids = []
    for i, box in enumerate(boxes):
        if bids[i] or raw[i]:
            continue  # já em balão claro (ou num balão claro grande demais: não arrisca)
        cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
        hit = next((cid for cid in color_ids if balloon_color.contains_point(infos[cid], cx, cy)), 0)
        if hit:
            bids[i] = hit
            continue
        others = [b for j, b in enumerate(boxes) if not bids[j] and not raw[j]]
        info = balloon_color.detect_color_balloon(img, box, text_boxes=others)
        if info is None or not balloon_fits_text(info, box):
            continue
        info["id"] = next_id
        infos[next_id] = info
        color_ids.append(next_id)
        bids[i] = next_id
        next_id += 1
    return bids


def layout_balloon_ids(boxes, id_map, infos, bids, page_shape):
    """Balão só para ESCREVER (não para varrer): fala pequena num balão grande (sussurro "w", "OI, SUMIRE-SAN").
    A Trava 5 recusa esses balões para a varredura, e o texto saía do tamanho da caixa OCR (9-11 px).
    As Travas 1-4 do mapa (fechado, compacto, poucos furos, borda escura) já valem; aqui só se exige que
    as falas fiquem dentro do balão, perto do centro, e que o balão não seja uma área enorme da página."""
    out = [0] * len(boxes)
    raw = [raw_balloon_id(b, id_map) for b in boxes]
    groups = {}
    for i, (box, rid) in enumerate(zip(boxes, raw)):
        if rid > 0 and rid in infos and not bids[i] and not infos[rid].get("kind"):
            groups.setdefault(rid, []).append(i)
    page_area = float(page_shape[0] * page_shape[1])
    for rid, idxs in groups.items():
        if any(bids[j] == rid for j in range(len(boxes))):
            continue
        info = infos[rid]
        bx0, by0, bx1, by1 = [float(v) for v in info["bbox"]]
        ux0, uy0, ux1, uy1 = _union([boxes[i] for i in idxs])
        tol = 6.0
        inside = ux0 >= bx0 - tol and uy0 >= by0 - tol and ux1 <= bx1 + tol and uy1 <= by1 + tol
        bw, bh = max(1.0, bx1 - bx0), max(1.0, by1 - by0)
        near_center = (abs((ux0 + ux1) / 2.0 - (bx0 + bx1) / 2.0) <= 0.30 * bw
                       and abs((uy0 + uy1) / 2.0 - (by0 + by1) / 2.0) <= 0.30 * bh)
        if inside and near_center and info.get("area", bw * bh) <= 0.06 * page_area:
            for i in idxs:
                out[i] = rid
    return out


def missed_ellipses(img_gray, info, text_boxes, line_h):
    """Reticências soltas ("...") dentro do balão que o OCR não leu (linha só de pontos).
    A varredura completa apagaria esses pontos; devolve [(cx, cy)] para recolocá-los no texto."""
    px0, py0 = info["local_origin"]
    mask = info["local_mask"]
    lh, lw = mask.shape
    roi = img_gray[py0:py0 + lh, px0:px0 + lw]
    if roi.shape != mask.shape or line_h <= 0:
        return []
    dark = ((roi < 140) & (cv2.erode(mask, np.ones((3, 3), np.uint8)) > 0)).astype(np.uint8)
    for tb in text_boxes:
        x0, y0, x1, y1 = [int(round(v)) for v in tb]
        dark[max(0, y0 - py0 - 3):max(0, y1 - py0 + 3), max(0, x0 - px0 - 3):max(0, x1 - px0 + 3)] = 0
    n, _, st, cen = cv2.connectedComponentsWithStats(dark, connectivity=8)
    dot_max = max(3.0, 0.45 * line_h)
    dots, others = [], []
    for i in range(1, n):
        w, h, area = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT], st[i, cv2.CC_STAT_AREA]
        if area < 3:
            continue
        if w <= dot_max and h <= dot_max and 0.4 <= w / float(h) <= 2.5:
            dots.append((float(cen[i][0]), float(cen[i][1]), float(area)))
        else:
            others.append(i)
    dots.sort()
    found, used = [], set()
    for i, (x, y, a) in enumerate(dots):
        if i in used:
            continue
        row = [i]
        for j in range(i + 1, len(dots)):
            xj, yj, aj = dots[j]
            if j in used or abs(yj - y) > max(3.0, 0.2 * line_h):
                continue
            if xj - dots[row[-1]][0] > 0.9 * line_h:
                break
            if 0.4 <= aj / a <= 2.5:
                row.append(j)
        if 2 <= len(row) <= 4:
            used.update(row)
            found.append((px0 + float(np.mean([dots[k][0] for k in row])),
                          py0 + float(np.mean([dots[k][1] for k in row]))))
    return found


def add_ellipsis(text, ell_y, box):
    """Recoloca "..." no começo (pontos acima do texto) ou no fim (pontos abaixo)."""
    t = (text or "").strip()
    if not t:
        return text
    if ell_y >= box[3] - 2 and not t.endswith(("...", "…")):
        return t.rstrip(".") + "..."
    if ell_y <= box[1] + 2 and not t.startswith(("...", "…")):
        return "... " + t
    return text


def free_width_around(gray, cx, y0, y1, thr=200):
    """Menor largura clara contínua, centrada em cx, nas linhas y0..y1 (onde o texto original estava).
    Serve de teto quando o perfil do balão foi medido em outro eixo (quadros em degrau)."""
    ih, iw = gray.shape[:2]
    x = int(round(min(max(cx, 0), iw - 1)))
    best = float(iw)
    for y in range(max(0, int(y0)), min(ih, int(y1) + 1), 2):
        row = gray[y] >= thr
        left = x
        while left > 0 and (row[left - 1] or x - left < 4):
            left -= 1
        right = x
        while right < iw - 1 and (row[right + 1] or right - x < 4):
            right += 1
        best = min(best, 2.0 * min(x - left, right - x))
    return best


def sweep(cleaned_bgr, info, text_boxes=None):
    """Limpa a cavidade inteira do balão (claro: pinta com a cor do papel; colorido: inpainting)."""
    if info.get("kind") == "color":
        return balloon_color.sweep_color_balloon(cleaned_bgr, info)
    n = balloon_cavity.sweep_balloon_interior(cleaned_bgr, info, erode_px=2)
    if min(info["fill_bgr"]) < 250 or not text_boxes:
        return n
    # Papel branco: a sombra clara do texto antigo (cinza 220-249) passa pelo limiar da varredura
    px0, py0 = info["local_origin"]
    mask = info["local_mask"]
    lh, lw = mask.shape
    near = np.zeros_like(mask)
    for tb in text_boxes:
        x0, y0, x1, y1 = [int(round(v)) for v in tb]
        near[max(0, y0 - py0 - 10):max(0, y1 - py0 + 10), max(0, x0 - px0 - 10):max(0, x1 - px0 + 10)] = 1
    roi = cleaned_bgr[py0:py0 + lh, px0:px0 + lw]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    soft = (cv2.erode(mask, np.ones((7, 7), np.uint8)) > 0) & (near > 0) & (gray >= 200) & (gray < 250)
    roi[soft] = (255, 255, 255)
    return n + int(soft.sum())
