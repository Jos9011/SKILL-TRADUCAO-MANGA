# -*- coding: utf-8 -*-
"""
Manga Studio - Módulo de Exportação de Datasets para Treinamento (Fine-Tuning)
Converte o histórico de traduções aprovadas, memórias e regras do Manga Studio
no formato padrão ShareGPT / Alpaca para treino com Unsloth / LLaMA-Factory.
Regra: Arquivo modular, desacoplado e menor que 300 linhas de código.
"""

import app_paths
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

SYSTEM_PROMPT_DEFAULT = (
    "Você é o tradutor literário oficial de scanlation de mangás, manhwas e quadrinhos para PT-BR. "
    "Adapte com naturalidade, oralidade coloquial autêntica, gírias brasileiras e fidelidade erótica sem censura."
)

def _is_valid_pair(orig: str, trans: str) -> bool:
    """Filtra ruídos brutos, textos idênticos sem tradução ou vazios."""
    o = str(orig or "").strip()
    t = str(trans or "").strip()
    if not o or not t:
        return False
    if len(o) < 2 or len(t) < 2:
        return False
    if o.lower() == t.lower() and not re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', o):
        # Texto latino igual em ambos (ex: pontuação pura, números ou não traduzido)
        return False
    # Filtra ruídos de código puro ou URLs
    if "http://" in o or "https://" in o or "www." in o:
        return False
    return True

def collect_translation_pairs(
    search_dirs: Optional[List[str]] = None,
    include_global_memory: bool = True,
    include_defaults: bool = False
) -> Tuple[Dict[str, str], int]:
    """Varre pastas de mangás traduzidos e extrai todos os pares originais -> traduzidos únicos."""
    pairs: Dict[str, str] = {}
    mangas_count = 0

    candidates = list(search_dirs or [])
    if not candidates or include_defaults:
        default_drive = r"g:\Meu Drive\MANGAS [PT-BR]"
        if os.path.exists(default_drive) and default_drive not in candidates:
            candidates.append(default_drive)

        base_dir = app_paths.DATA_DIR
        local_output = os.path.join(base_dir, "output")
        if os.path.exists(local_output) and local_output not in candidates:
            candidates.append(local_output)

    for c_dir in candidates:
        if not os.path.exists(c_dir):
            continue
        for root, _, files in os.walk(c_dir):
            for fname in files:
                if fname in ("translation_cache.json", "translation_memory.json"):
                    full_p = os.path.join(root, fname)
                    try:
                        with open(full_p, "r", encoding="utf-8") as jf:
                            data = json.load(jf)
                            if isinstance(data, dict):
                                added = 0
                                for orig, trans in data.items():
                                    if _is_valid_pair(orig, trans):
                                        pairs[orig.strip()] = str(trans).strip()
                                        added += 1
                                if added > 0:
                                    mangas_count += 1
                    except Exception:
                        pass

    if include_global_memory:
        for mem_name in ("memoria_global.json", "global_translation_memory.json"):
            mem_path = os.path.join(base_dir, mem_name)
            if os.path.exists(mem_path):
                try:
                    with open(mem_path, "r", encoding="utf-8") as mf:
                        m_data = json.load(mf)
                        if isinstance(m_data, dict):
                            for orig, trans in m_data.items():
                                if _is_valid_pair(orig, trans):
                                    pairs.setdefault(orig.strip(), str(trans).strip())
                except Exception:
                    pass

    return pairs, mangas_count

def build_sharegpt_record(orig: str, trans: str, system_prompt: str = SYSTEM_PROMPT_DEFAULT) -> dict:
    """Formata um par no padrão de conversação ShareGPT (padrão do Unsloth e LLaMA-Factory)."""
    return {
        "conversations": [
            {"from": "system", "value": system_prompt},
            {"from": "human", "value": f"Traduza o diálogo a seguir para português brasileiro natural no estilo scanlation:\n{orig}"},
            {"from": "gpt", "value": trans}
        ]
    }

def export_training_dataset(
    output_path: Optional[str] = None,
    search_dirs: Optional[List[str]] = None,
    system_prompt: str = SYSTEM_PROMPT_DEFAULT,
    format_type: str = "sharegpt"
) -> dict:
    """
    Gera o arquivo .jsonl pronto para fine-tuning.
    Retorna metadados com contagem de pares, tamanho em KB e caminhos gerados.
    """
    pairs, mangas_count = collect_translation_pairs(
        search_dirs=search_dirs,
        include_global_memory=bool(not search_dirs),
        include_defaults=bool(not search_dirs)
    )
    if not pairs:
        return {"ok": False, "error": "Nenhum par de tradução encontrado para exportação.", "total_pairs": 0}

    base_dir = app_paths.DATA_DIR
    if not output_path:
        output_path = os.path.join(base_dir, "dataset_manga_ptbr.jsonl")

    records = []
    for orig, trans in sorted(pairs.items()):
        if format_type.lower() == "alpaca":
            records.append({
                "instruction": "Traduza o diálogo para português brasileiro coloquial estilo scanlation.",
                "input": orig,
                "output": trans
            })
        else:
            records.append(build_sharegpt_record(orig, trans, system_prompt=system_prompt))

    # Grava no destino principal
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out_f:
        for r in records:
            out_f.write(json.dumps(r, ensure_ascii=False) + "\n")

    size_kb = round(os.path.getsize(output_path) / 1024, 2)

    # Cópia de conveniência no Google Drive se disponível
    drive_copy = None
    drive_dir = r"g:\Meu Drive\MANGAS [PT-BR]"
    if os.path.exists(drive_dir):
        try:
            drive_copy = os.path.join(drive_dir, "dataset_manga_ptbr.jsonl")
            with open(drive_copy, "w", encoding="utf-8") as df:
                for r in records:
                    df.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception:
            drive_copy = None

    return {
        "ok": True,
        "total_pairs": len(records),
        "total_mangas": mangas_count,
        "output_path": output_path,
        "drive_copy": drive_copy,
        "size_kb": size_kb,
        "format": format_type
    }

if __name__ == "__main__":
    fmt = "sharegpt"
    if "--alpaca" in sys.argv:
        fmt = "alpaca"
    res = export_training_dataset(format_type=fmt)
    if res.get("ok"):
        print("=" * 60)
        print("  🎉 DATASET DE TREINAMENTO MANGA STUDIO EXPORTADO!")
        print("=" * 60)
        print(f"  • Total de Pares Únicos:  {res['total_pairs']}")
        print(f"  • Obras Mapeadas:          {res['total_mangas']}")
        print(f"  • Formato:                 {res['format']} (Unsloth / LLaMA-Factory)")
        print(f"  • Arquivo Local:           {res['output_path']} ({res['size_kb']} KB)")
        if res.get("drive_copy"):
            print(f"  • Cópia Google Drive:      {res['drive_copy']}")
        print("=" * 60)
    else:
        print(f"[!] Erro ao exportar dataset: {res.get('error')}")
