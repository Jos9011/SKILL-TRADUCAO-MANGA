# -*- coding: utf-8 -*-
"""
SISTEMA DE VERSIONAMENTO OFICIAL DO MANGA STUDIO
Padrão SemVer: GRANDE . MÉDIO . PEQUENO (Major . Minor . Patch)
- GRANDE (Major): Mudanças estruturais, saltos de versão principal ou quebras (ex: 1.0.0).
- MÉDIO (Minor): Novas funcionalidades adicionadas (ex: perfil persistente, lixeira, novos modos) (ex: 0.2.0).
- PEQUENO (Patch): Correções de bugs, ajustes de traduções, ruídos de OCR e polimentos (ex: 0.2.1).
"""

import os
import re
import sys

VERSION_MAJOR = 0
VERSION_MINOR = 6
VERSION_PATCH = 1
VERSION_TAG = "beta"

__version__ = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"
if VERSION_TAG:
    __version__ += f"-{VERSION_TAG}"

__version_name__ = f"v{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"
if VERSION_TAG:
    __version_name__ += f" {VERSION_TAG.capitalize()}"

def get_version_info():
    return {
        "major": VERSION_MAJOR,
        "minor": VERSION_MINOR,
        "patch": VERSION_PATCH,
        "tag": VERSION_TAG,
        "version": __version__,
        "version_name": __version_name__
    }

def bump(kind="pequeno"):
    """
    Incrementa a versão conforme a escala:
    - 'pequeno' / 'patch': incrementa VERSION_PATCH (+1)
    - 'medio' / 'minor': incrementa VERSION_MINOR (+1) e zera VERSION_PATCH (0)
    - 'grande' / 'major': incrementa VERSION_MAJOR (+1) e zera VERSION_MINOR e VERSION_PATCH (0)
    """
    script_path = os.path.abspath(__file__)
    with open(script_path, "r", encoding="utf-8") as f:
        content = f.read()

    major_m = re.search(r"VERSION_MAJOR\s*=\s*(\d+)", content)
    minor_m = re.search(r"VERSION_MINOR\s*=\s*(\d+)", content)
    patch_m = re.search(r"VERSION_PATCH\s*=\s*(\d+)", content)
    tag_m = re.search(r'VERSION_TAG\s*=\s*["\']([^"\']*)["\']', content)

    if not (major_m and minor_m and patch_m):
        raise ValueError("Não foi possível identificar as variáveis de versão em version.py")

    major = int(major_m.group(1))
    minor = int(minor_m.group(1))
    patch = int(patch_m.group(1))
    tag = tag_m.group(1) if tag_m else ""

    kind_clean = kind.lower().strip()
    if kind_clean in ("grande", "major"):
        major += 1
        minor = 0
        patch = 0
    elif kind_clean in ("medio", "médio", "minor"):
        minor += 1
        patch = 0
    elif kind_clean in ("pequeno", "patch"):
        patch += 1
    else:
        raise ValueError(f"Tipo de incremento inválido: '{kind}'. Use 'pequeno', 'medio' ou 'grande'.")

    # Substitui os números mantendo o arquivo limpo
    content = re.sub(r"VERSION_MAJOR\s*=\s*\d+", f"VERSION_MAJOR = {major}", content)
    content = re.sub(r"VERSION_MINOR\s*=\s*\d+", f"VERSION_MINOR = {minor}", content)
    content = re.sub(r"VERSION_PATCH\s*=\s*\d+", f"VERSION_PATCH = {patch}", content)

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(content)

    new_ver = f"{major}.{minor}.{patch}"
    if tag:
        new_ver += f"-{tag}"
    new_ver_name = f"v{major}.{minor}.{patch}"
    if tag:
        new_ver_name += f" {tag.capitalize()}"

    # Atualiza README.md se existir
    base_dir = os.path.dirname(script_path)
    readme_path = os.path.join(base_dir, "README.md")
    if os.path.exists(readme_path):
        try:
            with open(readme_path, "r", encoding="utf-8") as rf:
                r_content = rf.read()
            r_content = re.sub(r"badge/versão-v?[0-9\.]+(?:--[a-zA-Z]+)?", f"badge/versão-v{new_ver.replace('-', '--')}", r_content)
            r_content = re.sub(r"# Manga Studio v[0-9\.]+(?:\s+[a-zA-Z]+)?", f"# Manga Studio {new_ver_name}", r_content)
            with open(readme_path, "w", encoding="utf-8") as rf:
                rf.write(r_content)
        except Exception as e:
            print(f"[!] Aviso ao atualizar README.md: {e}")

    print(f"Versão atualizada com sucesso ({kind_clean}): {new_ver_name} ({new_ver})")
    return new_ver_name

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "bump" and len(sys.argv) > 2:
            bump(sys.argv[2])
        elif cmd in ("pequeno", "medio", "médio", "grande", "patch", "minor", "major"):
            bump(cmd)
        elif cmd in ("current", "version", "show"):
            print(f"Versão Atual: {__version_name__} ({__version__})")
        else:
            print("Uso: python version.py [bump pequeno | bump medio | bump grande | current]")
    else:
        print(f"Manga Studio - {__version_name__} ({__version__})")
