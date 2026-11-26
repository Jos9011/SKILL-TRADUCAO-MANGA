"""
color_merge.py - Traço e retícula originais por cima da cor do modelo (Manga Studio).
Ajustado comparando com a colorização oficial de uma obra: pele natural com sombra, cores sem exagero,
retícula vira sombra lisa (antes: pele estourada, loiro laranja, manchas de pele molhada como hematoma).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import cv2
import numpy as np

# Ajustados comparando com a colorização oficial de uma obra: o modelo cru satura demais (loiro vira laranja)
PAPER_BLEND = 0.5  # quanto clarear na direção do papel original (0 = cores escuras, 1 = pele estourada)
COLOR_SATURATION = 0.7  # intensidade final das cores (1 = como o modelo entrega)
DESCREEN_SIGMA = 1.5  # suavização da retícula numa página de 1500 px (escala com o tamanho)
# Paleta da página: o modelo deixa a mesma peça em vários tons; puxa cada pixel para a cor principal mais próxima
PALETTE_SIZE = 8  # 6 já manchava a pele de branco; 8 manteve pele e cabelo e uniformizou moletom e saia
PALETTE_PULL = 0.7  # quanto puxar (1 = cor chapada)
PALETTE_SOFTNESS = 10.0  # mistura as cores principais vizinhas: sem isso, a pele virava manchas brancas


def descreen(gray):
    """Retícula (pontinhos) vira sombra lisa; traço de verdade (escuro com vizinhança escura) fica nítido.
    Sem isso, as manchas de pele molhada viravam hematomas e o céu ficava granulado."""
    sigma = max(0.6, DESCREEN_SIGMA * max(gray.shape[:2]) / 1500.0)
    smooth = cv2.GaussianBlur(gray, (0, 0), sigma)
    line = (gray < 110) & (smooth < 150)
    return np.where(line, gray, smooth).astype(np.uint8)


def merge_lineart(color_bgr, gray):
    """Traço e retícula originais por cima da cor, no modo "escurecer" (Lab).
    Antes o brilho era trocado pelo da página P&B: a pele (papel branco) estourava para branco-amarelado."""
    lab = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)
    gray = descreen(gray)
    ink = cv2.cvtColor(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), cv2.COLOR_BGR2Lab)[:, :, 0].astype(np.float32)
    # Clareia na direção do papel original e nunca passa do traço/retícula; cor some junto com o brilho no traço
    new_l = np.minimum(lab[:, :, 0] * (1 - PAPER_BLEND) + ink * PAPER_BLEND, ink)
    keep = (np.minimum(new_l / np.maximum(lab[:, :, 0], 1.0), 1.0) * COLOR_SATURATION)[:, :, None]
    lab[:, :, 1:] = 128.0 + (lab[:, :, 1:] - 128.0) * keep
    lab[:, :, 0] = new_l
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_Lab2BGR)


def consolidate_colors(color_bgr):
    """Uma peça, uma cor: o modelo pinta o mesmo moletom de rosa, roxo e azul, e a saia jeans em manchas.
    Acha as PALETTE_SIZE cores principais da página (k-means em a/b) e puxa cada pixel para elas,
    com transição suave entre cores vizinhas.
    Só a cor muda; o brilho e as sombras do modelo ficam."""
    lab = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)
    ab = lab[:, :, 1:].reshape(-1, 2)
    sample = np.ascontiguousarray(ab[:: max(1, ab.shape[0] // 60000)])
    k = min(PALETTE_SIZE, len(np.unique(sample.astype(np.uint8), axis=0)))
    if k < 2:
        return color_bgr
    cv2.setRNGSeed(0)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, _, centers = cv2.kmeans(sample, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    dist2 = ((ab[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    weights = np.exp(-(dist2 - dist2.min(axis=1, keepdims=True)) / (2 * PALETTE_SOFTNESS ** 2))
    target = ((weights @ centers) / weights.sum(axis=1, keepdims=True)).reshape(lab.shape[0], lab.shape[1], 2)
    lab[:, :, 1:] = lab[:, :, 1:] * (1 - PALETTE_PULL) + target * PALETTE_PULL
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_Lab2BGR)
