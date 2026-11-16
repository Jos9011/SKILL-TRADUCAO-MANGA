# -*- coding: utf-8 -*-
"""
studio/drive_helper.py - Descoberta Inteligente e Escaneamento do Google Drive
Gerencia caminhos de Google Drive (Colab e Windows) de forma tolerante a maiúsculas/minúsculas.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import re
import zipfile


def natural_sort_key(s):
    """Ordenação natural para números em nomes de arquivos (ex: 1, 2, 10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", str(s))]


def find_drive_roots():
    """Retorna lista de caminhos raiz do Google Drive encontrados (Linux/Colab e Windows)."""
    roots = []

    # 1. Google Colab / Linux (/content/drive e subpastas)
    for colab_base in ["/content/drive", "/content/gdrive"]:
        if os.path.exists(colab_base):
            try:
                for entry in sorted(os.listdir(colab_base)):
                    if entry.startswith("."):
                        continue
                    p = os.path.abspath(os.path.join(colab_base, entry))
                    if os.path.isdir(p) and p not in roots:
                        roots.append(p)
            except Exception:
                pass
            colab_base_norm = os.path.abspath(colab_base)
            if colab_base_norm not in roots:
                roots.append(colab_base_norm)

    # 2. Candidatos fixos comuns em Colab e Linux/Windows
    fixed_candidates = [
        "/content/drive/MyDrive",
        "/content/drive/Meu Drive",
        "/content/drive/My Drive",
        "/content/drive/Shareddrives",
        "/content/drive/Drives compartilhados",
        "G:\\Meu Drive",
        "G:\\My Drive",
        os.path.expanduser("~/Google Drive"),
        os.path.expanduser("~/Meu Drive")
    ]

    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase:
            fixed_candidates.append(f"{letter}:\\Meu Drive")
            fixed_candidates.append(f"{letter}:\\My Drive")
            fixed_candidates.append(f"{letter}:\\Google Drive")

    for c in fixed_candidates:
        if os.path.exists(c):
            norm = os.path.abspath(c)
            if norm not in roots:
                roots.append(norm)

    return roots


def is_drive_path(p):
    """Verifica se o caminho informado está dentro de um Google Drive montado."""
    if not p:
        return False
    clean = os.path.abspath(p).replace("\\", "/").lower()
    if "/content/drive" in clean or "/content/gdrive" in clean:
        return True
    for r in find_drive_roots():
        if os.path.abspath(r).replace("\\", "/").lower() in clean:
            return True
    return False


def find_manga_directories(root):
    """
    Localiza pastas de mangá dentro de uma raiz do Drive, de forma insensível
    a maiúsculas/minúsculas e tolerante a variações (MANGAS, Mangas, etc.).
    Retorna (raw_dirs, translated_dirs).
    """
    raw_dirs = []
    trans_dirs = []
    if not root or not os.path.exists(root):
        return raw_dirs, trans_dirs

    try:
        for item in sorted(os.listdir(root)):
            if item.startswith(".") or item.startswith("_"):
                continue
            full_p = os.path.abspath(os.path.join(root, item))
            if not os.path.isdir(full_p):
                continue
            item_low = item.lower()
            if "manga" in item_low or "mangas" in item_low:
                if "[pt-br]" in item_low or "pt-br" in item_low or "traduzid" in item_low:
                    if full_p not in trans_dirs:
                        trans_dirs.append(full_p)
                else:
                    if full_p not in raw_dirs:
                        raw_dirs.append(full_p)
    except Exception:
        pass

    return raw_dirs, trans_dirs


def scan_folder_for_mangas(folder_path, seen_paths, path_cache, get_pymupdf_fn):
    """
    Varre um diretório buscando obras (pastas com imagens/capítulos, .zip, .cbz ou .pdf).
    Popula path_cache e seen_paths para garantir integridade e agilidade.
    """
    entries = []
    if not folder_path or not os.path.exists(folder_path):
        return entries

    img_exts = (".jpg", ".jpeg", ".png", ".webp")

    try:
        for item in sorted(os.listdir(folder_path)):
            full_p = os.path.abspath(os.path.join(folder_path, item))
            if full_p in seen_paths or item.startswith(".") or item == "_ocr":
                continue

            # 1. Pastas com imagens diretas ou subpastas de capítulos
            if os.path.isdir(full_p):
                imgs = [f for f in os.listdir(full_p) if f.lower().endswith(img_exts)]
                if not imgs:
                    subdirs = [
                        os.path.join(full_p, d) for d in os.listdir(full_p)
                        if os.path.isdir(os.path.join(full_p, d)) and not d.startswith(".")
                    ]
                    for sub in sorted(subdirs, key=natural_sort_key):
                        sub_imgs = [f for f in os.listdir(sub) if f.lower().endswith(img_exts)]
                        if sub_imgs:
                            imgs = sub_imgs
                            break
                if not imgs:
                    continue

                seen_paths.add(full_p)
                imgs.sort(key=natural_sort_key)
                m_id = str(abs(hash(full_p)))
                if path_cache is not None:
                    path_cache[m_id] = full_p

                has_reader = os.path.exists(os.path.join(full_p, "leitor.html"))
                clean_full = full_p.rstrip("/\\")
                cbz_p = clean_full + ".cbz"
                has_cbz = os.path.exists(cbz_p)

                entries.append({
                    "id": m_id,
                    "name": item,
                    "clean_name": item.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip(),
                    "path": full_p,
                    "pages": len(imgs),
                    "has_reader": has_reader,
                    "has_cbz": has_cbz,
                    "cbz_path": cbz_p if has_cbz else None,
                    "reader_path": os.path.join(full_p, "leitor.html") if has_reader else None,
                    "reader_url": f"/read/{m_id}/",
                    "mtime": os.path.getmtime(full_p),
                    "first_img": os.path.join(full_p, imgs[0]),
                    "is_drive": is_drive_path(full_p),
                    "is_archive": False
                })

            # 2. Arquivos compactados (.zip, .cbz) ou .pdf
            elif os.path.isfile(full_p) and item.lower().endswith((".zip", ".cbz", ".pdf")):
                unpacked = os.path.splitext(full_p)[0]
                if unpacked in seen_paths and os.path.isdir(unpacked):
                    continue

                m_id = str(abs(hash(full_p)))
                if path_cache is not None:
                    path_cache[m_id] = full_p
                clean_n = os.path.splitext(item)[0]

                if item.lower().endswith(".pdf"):
                    fitz = get_pymupdf_fn()
                    if fitz is not None:
                        try:
                            doc = fitz.open(full_p)
                            num_pages = len(doc)
                            doc.close()
                            if num_pages > 0:
                                seen_paths.add(full_p)
                                entries.append({
                                    "id": m_id,
                                    "name": clean_n,
                                    "clean_name": clean_n.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip(),
                                    "path": full_p,
                                    "pages": num_pages,
                                    "has_reader": False,
                                    "has_cbz": False,
                                    "cbz_path": None,
                                    "reader_path": None,
                                    "reader_url": None,
                                    "mtime": os.path.getmtime(full_p),
                                    "first_img": f"{full_p}::page0",
                                    "is_drive": is_drive_path(full_p),
                                    "is_archive": True,
                                    "archive_type": "PDF"
                                })
                        except Exception:
                            pass
                else:
                    try:
                        with zipfile.ZipFile(full_p, "r") as z:
                            zip_imgs = [
                                inf.filename for inf in z.infolist()
                                if not inf.is_dir() and inf.filename.lower().endswith(img_exts)
                            ]
                            if zip_imgs:
                                zip_imgs.sort(key=natural_sort_key)
                                seen_paths.add(full_p)
                                arc_type = "CBZ" if item.lower().endswith(".cbz") else "ZIP"
                                entries.append({
                                    "id": m_id,
                                    "name": clean_n,
                                    "clean_name": clean_n.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip(),
                                    "path": full_p,
                                    "pages": len(zip_imgs),
                                    "has_reader": False,
                                    "has_cbz": False,
                                    "cbz_path": None,
                                    "reader_path": None,
                                    "reader_url": None,
                                    "mtime": os.path.getmtime(full_p),
                                    "first_img": f"{full_p}::{zip_imgs[0]}",
                                    "is_drive": is_drive_path(full_p),
                                    "is_archive": True,
                                    "archive_type": arc_type
                                })
                    except Exception:
                        pass
    except Exception:
        pass

    return entries
