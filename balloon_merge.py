"""
balloon_merge.py - Junta numa fala só os pedaços de texto que estão no MESMO balão, antes da tradução.

Problema real (até a v0.8.6): o japonês vem em colunas verticais estreitas. Cada coluna era comparada sozinha com
o balão, a Trava 5 recusava (balão bem mais largo que a coluna) e a fala virava pedaços traduzidos
separados: "KAEDE" / "ESSA AQUI É", "MAS" fora da frase, um "I" solto, e cada pedaço escrito miúdo no
lugar da sua coluna. O agrupamento do OCR fica no cache do capítulo, então esta etapa roda na hora de
traduzir e também corrige capítulos já lidos. Usa a mesma regra da limpeza (balloon_assign: o balão é
comparado com a união de todas as falas dele).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import re

import cv2
import numpy as np

import balloon_assign
import balloon_cavity

_JA_ZH = re.compile(r"[぀-ヿ一-鿿]")  # japonês/chinês juntam sem espaço; coreano usa espaço


def read_page(path):
    try:
        with open(path, "rb") as f:
            return cv2.imdecode(np.asarray(bytearray(f.read()), dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


def _reading_order(group):
    """Colunas verticais: da direita para a esquerda. Linhas horizontais: de cima para baixo."""
    if all(b.get("is_vertical") for b in group):
        return sorted(group, key=lambda b: (-float(b["box"][2]), float(b["box"][1])))
    return sorted(group, key=lambda b: (float(b["box"][1]), float(b["box"][0])))


def merge_group(group):
    parts = _reading_order(group)
    texts = [str(b.get("combined_text", "")).strip() for b in parts]
    sep = "" if any(_JA_ZH.search(t) for t in texts) else " "
    xs0, ys0, xs1, ys1 = zip(*[[float(v) for v in b["box"]] for b in parts])
    box = [int(min(xs0)), int(min(ys0)), int(max(xs1)), int(max(ys1))]
    merged = dict(parts[0])
    merged.update({
        "box": box,
        "raw_boxes": [r for b in parts for r in (b.get("raw_boxes") or [b["box"]])],
        "lines": [ln for b in parts for ln in (b.get("lines") or [])],
        "orig_line_count": sum(int(b.get("orig_line_count") or 1) for b in parts),
        "combined_text": sep.join(t for t in texts if t),
        "is_vertical": all(b.get("is_vertical") for b in parts),
    })
    return merged


def lobe_clusters(info, boxes):
    """Balão duplo ligado (dois "lobos" num contorno só, como "NÓS" + "TALVEZ A GENTE..."): cada lobo tem a
    sua fala e não pode virar um texto só. Afina a forma aos poucos: um oval nunca se parte, um balão em "8"
    se parte no pescoço. Devolve um rótulo por caixa; caixas com o mesmo rótulo ficam no mesmo lobo."""
    n = len(boxes)
    labels = list(range(n))
    if n < 2 or not info or info.get("local_mask") is None:
        return [0] * n
    mask = (info["local_mask"] > 0).astype(np.uint8)
    px0, py0 = info["local_origin"]
    pts = [(int(round((b[0] + b[2]) / 2.0)) - px0, int(round((b[1] + b[3]) / 2.0)) - py0) for b in boxes]
    lh, lw = mask.shape
    separated = set()
    step = max(3, int(min(lh, lw) * 0.04))
    for r in range(step, int(min(lh, lw) * 0.45), step):
        er = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
        n_c, comp = cv2.connectedComponents(er)
        if n_c <= 2:
            if n_c <= 1:
                break
            continue
        lab = [int(comp[y, x]) if 0 <= y < lh and 0 <= x < lw else 0 for x, y in pts]
        for i in range(n):
            for j in range(i + 1, n):
                if lab[i] and lab[j] and lab[i] != lab[j]:
                    separated.add((i, j))

    def find(i):
        while labels[i] != i:
            labels[i] = labels[labels[i]]
            i = labels[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) not in separated:
                labels[find(i)] = find(j)
    return [find(i) for i in range(n)]


def merge_same_balloon(bubbles, img):
    """Devolve (bolhas, quantas falas foram juntadas). Nada muda se a página não tiver balão fechado."""
    if not bubbles or len(bubbles) < 2 or img is None or getattr(img, "size", 0) == 0:
        return bubbles, 0
    try:
        id_map, infos = balloon_cavity.build_balloon_map(img)
        bids = balloon_assign.assign_balloon_ids([b["box"] for b in bubbles], id_map, infos)
    except Exception:
        return bubbles, 0
    groups = {}
    for i, bid in enumerate(bids):
        if bid > 0:
            groups.setdefault(bid, []).append(i)
    # Balão duplo ligado: cada lobo fica com a sua fala
    for bid, idxs in list(groups.items()):
        if len(idxs) > 1 and bid in infos:
            lobes = lobe_clusters(infos[bid], [bubbles[i]["box"] for i in idxs])
            if len(set(lobes)) > 1:
                del groups[bid]
                for k, lb in enumerate(lobes):
                    groups.setdefault((bid, lb), []).append(idxs[k])
    first_of = {idxs[0]: bid for bid, idxs in groups.items() if len(idxs) > 1}
    absorbed = {i for idxs in groups.values() if len(idxs) > 1 for i in idxs[1:]}
    out, joined = [], 0
    for i, b in enumerate(bubbles):
        if i in absorbed:
            continue
        if i in first_of:
            idxs = groups[first_of[i]]
            out.append(merge_group([bubbles[j] for j in idxs]))
            joined += len(idxs) - 1
        else:
            out.append(b)
    return out, joined
