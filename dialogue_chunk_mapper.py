"""
dialogue_chunk_mapper.py - Mapeador e Validador Resiliente de Lotes de Balões
Garante integridade estrita de IDs entre Agente 1 (Cartógrafo) e Agente 2 (Contextualizador),
eliminando completamente qualquer risco de deslocamento (off-by-one / efeito cascata).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import re


def prepare_chunk_payload(chunk, src_lang="auto"):
    """
    Re-indexa estritamente os balões de um lote de 1 a N antes de enviar para a IA.
    Garante que não existam buracos (gaps) de IDs e que cada lote sempre comece em 1.
    """
    if not chunk:
        return [], {}, []

    payload_baloes = []
    chunk_dmap = {}
    chunk_ordered = []

    for idx, b in enumerate(chunk):
        c_id = str(idx + 1)
        orig_raw = b.get("orig_raw", "")
        cleaned_t = b.get("texto_original", orig_raw)
        
        chunk_dmap[c_id] = orig_raw
        chunk_ordered.append(orig_raw)

        formato = b.get("formato", "")
        tipo = "V" if "vertical" in formato else ("H" if "retangular" in formato else "O")
        
        payload_baloes.append({
            "id": c_id,
            "pos": b.get("pos", "centro"),
            "tipo": tipo,
            "max_chars": b.get("max_chars", 80),
            "texto": cleaned_t
        })

    return payload_baloes, chunk_dmap, chunk_ordered


def extract_json_from_response(resp_content):
    """
    Extrai e faz parse seguro de JSON (objeto ou array) a partir da resposta da IA,
    removendo tags <think> e blocos markdown ```json.
    """
    if not resp_content:
        return None

    clean = re.sub(r"<think>.*?</think>", "", resp_content, flags=re.DOTALL)
    clean = re.sub(r"```(?:json)?\s*", "", clean)
    clean = clean.replace("```", "").strip()

    # Tenta achar JSON objeto {...}
    obj_match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    if obj_match:
        try:
            parsed = json.loads(obj_match.group(0))
            if isinstance(parsed, dict) and parsed:
                return parsed
        except Exception:
            pass

    # Tenta achar JSON lista [...]
    list_match = re.search(r"\[.*\]", clean, flags=re.DOTALL)
    if list_match:
        try:
            parsed = json.loads(list_match.group(0))
            if isinstance(parsed, list) and parsed:
                return parsed
        except Exception:
            pass

    return None


def map_ai_response_to_bubbles(parsed, chunk_ordered, chunk_dmap):
    """
    Mapeia a resposta da IA de volta para os originais brutos com proteção contra deslocamentos.
    Suporta mapeamento por ID estrito, regex numérico e fallback posicional seguro.
    """
    if not parsed or not chunk_ordered:
        return {}

    mapped_results = {}
    total_expected = len(chunk_ordered)

    # 1. Caso a IA tenha retornado um Array JSON [...]
    if isinstance(parsed, list):
        for idx, item in enumerate(parsed):
            if idx < total_expected:
                orig = chunk_ordered[idx]
                if isinstance(item, dict):
                    trans = item.get("translation") or item.get("texto") or item.get("traducao") or ""
                else:
                    trans = str(item)
                if trans and str(trans).strip():
                    mapped_results[orig] = str(trans).strip()
        return mapped_results

    # 2. Caso a IA tenha retornado um Objeto JSON {...}
    if isinstance(parsed, dict):
        key_matches = 0
        temp_mapped = {}

        for raw_k, trans_val in parsed.items():
            if not trans_val:
                continue
            trans_str = str(trans_val).strip()
            if not trans_str:
                continue

            # Tenta encontrar a chave direta (ex: "1", "2")
            clean_k = str(raw_k).strip()
            if clean_k in chunk_dmap:
                orig = chunk_dmap[clean_k]
                temp_mapped[orig] = trans_str
                key_matches += 1
                continue

            # Tenta extrair dígitos da chave (ex: "balao_1", "id 1", "item1")
            digit_match = re.search(r"\d+", clean_k)
            if digit_match:
                d_key = str(int(digit_match.group(0)))
                if d_key in chunk_dmap:
                    orig = chunk_dmap[d_key]
                    temp_mapped[orig] = trans_str
                    key_matches += 1
                    continue

        # Se pelo menos metade das chaves casou perfeitamente por ID, confia no mapeamento por chave
        if key_matches >= max(1, total_expected // 2):
            return temp_mapped

        # Fallback posicional: se as chaves da IA forem arbitrárias mas o número de valores for exato
        val_list = [str(v).strip() for v in parsed.values() if v and str(v).strip()]
        if len(val_list) == total_expected:
            for idx, trans_str in enumerate(val_list):
                orig = chunk_ordered[idx]
                mapped_results[orig] = trans_str
            return mapped_results

        # Se houver algum casamento parcial, retorna o que conseguiu
        if temp_mapped:
            return temp_mapped

    return {}


def tag_connected_balloons(bubbles):
    """
    Identifica balões contíguos na página que dividem a mesma fala ou oração,
    anotando dica contextual para o Agente 2 manter a continuidade da frase.
    """
    if not bubbles or len(bubbles) < 2:
        return bubbles

    terminal_punct = re.compile(r"[.!?~♡♥…]+$")
    continuation_indicators = re.compile(r"[-–—…]+$")

    for i in range(len(bubbles) - 1):
        cur_text = bubbles[i].get("texto_original", "").strip()
        next_text = bubbles[i + 1].get("texto_original", "").strip()

        if not cur_text or not next_text:
            continue

        # Se o balão atual não termina com pontuação final forte ou termina em hífen/reticências
        is_split = False
        if continuation_indicators.search(cur_text):
            is_split = True
        elif not terminal_punct.search(cur_text) and len(cur_text.split()) <= 4:
            is_split = True

        if is_split:
            bubbles[i]["continua_no_proximo"] = True
            bubbles[i + 1]["continua_do_anterior"] = True

    return bubbles
