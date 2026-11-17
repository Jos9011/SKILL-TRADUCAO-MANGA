# -*- coding: utf-8 -*-
"""
studio/drive_helper.py - Descoberta Inteligente e Escaneamento do Google Drive
Gerencia caminhos de Google Drive (Colab e Windows) resolvendo symlinks e duplicatas.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import re
import zipfile


def real_path_key(path):
    """Retorna chave canônica resolvendo symlinks (ex: 'My Drive' -> 'MyDrive')."""
    if not path:
        return ""
    try:
        return os.path.normcase(os.path.realpath(path))
    except Exception:
        return os.path.normcase(os.path.abspath(path))


def natural_sort_key(s):
    """Ordenação natural para números em nomes de arquivos (ex: 1, 2, 10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", str(s))]


def find_drive_roots():
    """Retorna caminhos raiz únicos do Google Drive (sem duplicar symlinks)."""
    roots = []
    seen_real = set()

    def _add_root(candidate):
        if not candidate or not os.path.exists(candidate):
            return
        norm = os.path.abspath(candidate)
        rk = real_path_key(norm)
        if rk not in seen_real:
            seen_real.add(rk)
            roots.append(norm)

    # 1. Prioriza caminhos canônicos do Colab antes de varrer symlinks
    for fixed in [
        "/content/drive/MyDrive",
        "/content/drive/Meu Drive",
        "/content/drive/My Drive",
        "/content/drive/Shareddrives",
        "/content/drive/Drives compartilhados",
        "G:\\Meu Drive",
        "G:\\My Drive",
        os.path.expanduser("~/Google Drive"),
        os.path.expanduser("~/Meu Drive")
    ]:
        _add_root(fixed)

    # 2. Varre subpastas adicionais de montagem no Colab / Linux
    for colab_base in ["/content/drive", "/content/gdrive"]:
        if os.path.exists(colab_base):
            try:
                for entry in sorted(os.listdir(colab_base)):
                    if entry.startswith("."):
                        continue
                    p = os.path.join(colab_base, entry)
                    if os.path.isdir(p):
                        _add_root(p)
            except Exception:
                pass
            if not roots:
                _add_root(colab_base)

    # 3. Letras de unidade no Windows
    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase:
            _add_root(f"{letter}:\\Meu Drive")
            _add_root(f"{letter}:\\My Drive")
            _add_root(f"{letter}:\\Google Drive")

    return roots


def is_drive_path(p):
    """Verifica se o caminho informado está dentro de um Google Drive montado."""
    if not p:
        return False
    clean = real_path_key(p).replace("\\", "/")
    if "/content/drive" in clean or "/content/gdrive" in clean:
        return True
    for r in find_drive_roots():
        if real_path_key(r).replace("\\", "/") in clean:
            return True
    return False


def find_manga_directories(root):
    """
    Localiza pastas de mangá dentro de uma raiz do Drive, insensível a maiúsculas
    e sem duplicar symlinks. Retorna (raw_dirs, translated_dirs).
    """
    raw_dirs, trans_dirs = [], []
    seen_real = set()
    if not root or not os.path.exists(root):
        return raw_dirs, trans_dirs

    try:
        for item in sorted(os.listdir(root)):
            if item.startswith(".") or item.startswith("_"):
                continue
            full_p = os.path.abspath(os.path.join(root, item))
            if not os.path.isdir(full_p):
                continue
            rk = real_path_key(full_p)
            if rk in seen_real:
                continue
            item_low = item.lower()
            if "manga" in item_low:
                seen_real.add(rk)
                if "[pt-br]" in item_low or "pt-br" in item_low or "traduzid" in item_low:
                    trans_dirs.append(full_p)
                else:
                    raw_dirs.append(full_p)
    except Exception:
        pass

    return raw_dirs, trans_dirs


def deduplicate_entries(entries):
    """Remove duplicatas lógicas (mesma obra em pasta + CBZ ou pastas espelhadas)."""
    best_by_name = {}
    for entry in entries:
        key = (entry.get("clean_name") or entry.get("name") or "").strip().lower()
        if not key:
            continue
        prev = best_by_name.get(key)
        if not prev:
            best_by_name[key] = entry
            continue
        # Prefere pasta descompactada / com leitor / Google Drive / mais recente
        score_new = (
            not entry.get("is_archive", False),
            bool(entry.get("has_reader", False)),
            bool(entry.get("is_drive", False)),
            entry.get("mtime", 0),
        )
        score_old = (
            not prev.get("is_archive", False),
            bool(prev.get("has_reader", False)),
            bool(prev.get("is_drive", False)),
            prev.get("mtime", 0),
        )
        if score_new > score_old:
            best_by_name[key] = entry
    return list(best_by_name.values())


def scan_folder_for_mangas(folder_path, seen_paths, path_cache, get_pymupdf_fn):
    """
    Varre diretório buscando obras (pastas com imagens/capítulos, .zip, .cbz ou .pdf).
    Usa real_path_key em seen_paths para evitar duplicatas via symlinks.
    """
    entries = []
    if not folder_path or not os.path.exists(folder_path):
        return entries

    img_exts = (".jpg", ".jpeg", ".png", ".webp")

    try:
        items = sorted(os.listdir(folder_path))
        # Processa pastas antes de arquivos para que .cbz/.zip reconheçam a pasta já existente
        items.sort(key=lambda name: (not os.path.isdir(os.path.join(folder_path, name)), name.lower()))

        for item in items:
            full_p = os.path.abspath(os.path.join(folder_path, item))
            rk = real_path_key(full_p)
            if rk in seen_paths or item.startswith(".") or item == "_ocr":
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

                seen_paths.add(rk)
                imgs.sort(key=natural_sort_key)
                m_id = str(abs(hash(rk)))
                if path_cache is not None:
                    path_cache[m_id] = full_p

                has_reader = os.path.exists(os.path.join(full_p, "leitor.html"))
                cbz_p = full_p.rstrip("/\\") + ".cbz"
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
                if real_path_key(unpacked) in seen_paths or os.path.isdir(unpacked):
                    continue

                m_id = str(abs(hash(rk)))
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
                                seen_paths.add(rk)
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
                                seen_paths.add(rk)
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
