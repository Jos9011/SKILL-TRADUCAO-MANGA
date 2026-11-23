"""
test_dialogue_chunk_mapper.py - Testes unitários para o Mapeador de Lotes e Anti-Deslocamento
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import unittest
from dialogue_chunk_mapper import (
    prepare_chunk_payload,
    extract_json_from_response,
    map_ai_response_to_bubbles,
    tag_connected_balloons
)


class TestDialogueChunkMapper(unittest.TestCase):
    def test_prepare_chunk_payload_reindexing(self):
        """Verifica se os IDs são estritamente 1..N independente de gaps prévios."""
        chunk = [
            {"id": "5", "orig_raw": "Hello", "texto_original": "Hello", "formato": "retangular"},
            {"id": "8", "orig_raw": "World", "texto_original": "World", "formato": "vertical"},
            {"id": "12", "orig_raw": "!", "texto_original": "!", "formato": "oval"}
        ]
        payload, dmap, ordered = prepare_chunk_payload(chunk)
        self.assertEqual(len(payload), 3)
        self.assertEqual([p["id"] for p in payload], ["1", "2", "3"])
        self.assertEqual([p["tipo"] for p in payload], ["H", "V", "O"])
        self.assertEqual(dmap["1"], "Hello")
        self.assertEqual(dmap["2"], "World")
        self.assertEqual(dmap["3"], "!")
        self.assertEqual(ordered, ["Hello", "World", "!"])

    def test_extract_json_from_response(self):
        """Verifica extração de JSON de respostas com <think> e markdown."""
        resp_obj = "<think>Raciocínio aqui...</think>```json\n{\"1\": \"Olá\", \"2\": \"Mundo\"}\n```"
        parsed = extract_json_from_response(resp_obj)
        self.assertEqual(parsed, {"1": "Olá", "2": "Mundo"})

        resp_arr = "Aqui está:\n```json\n[\"Olá\", \"Mundo\"]\n```"
        parsed_arr = extract_json_from_response(resp_arr)
        self.assertEqual(parsed_arr, ["Olá", "Mundo"])

    def test_map_ai_response_prevent_shift(self):
        """
        Simula exatamente o caso do TS Drink Página 10:
        Garante que se a IA retornar 1..N, as falas casem perfeitamente
        sem deslocar para balões adjacentes.
        """
        chunk = [
            {"orig_raw": "Wait, did you hear that?", "texto_original": "Wait, did you hear that?"},
            {"orig_raw": "I don't think so.", "texto_original": "I don't think so."},
            {"orig_raw": "Let's check outside.", "texto_original": "Let's check outside."}
        ]
        _, dmap, ordered = prepare_chunk_payload(chunk)

        ai_response = {
            "1": "Espera, você ouviu isso?",
            "2": "Acho que não.",
            "3": "Vamos verificar lá fora."
        }
        mapped = map_ai_response_to_bubbles(ai_response, ordered, dmap)
        self.assertEqual(mapped["Wait, did you hear that?"], "Espera, você ouviu isso?")
        self.assertEqual(mapped["I don't think so."], "Acho que não.")
        self.assertEqual(mapped["Let's check outside."], "Vamos verificar lá fora.")

    def test_map_ai_response_with_prefixed_keys(self):
        """Verifica suporte a chaves no estilo 'balao 1', 'id_2'."""
        chunk = [
            {"orig_raw": "First", "texto_original": "First"},
            {"orig_raw": "Second", "texto_original": "Second"}
        ]
        _, dmap, ordered = prepare_chunk_payload(chunk)

        ai_response = {
            "balao_1": "Primeiro",
            "balao_2": "Segundo"
        }
        mapped = map_ai_response_to_bubbles(ai_response, ordered, dmap)
        self.assertEqual(mapped["First"], "Primeiro")
        self.assertEqual(mapped["Second"], "Segundo")

    def test_map_ai_response_list_format(self):
        """Verifica suporte a retorno em formato de lista pura."""
        chunk = [
            {"orig_raw": "One", "texto_original": "One"},
            {"orig_raw": "Two", "texto_original": "Two"}
        ]
        _, dmap, ordered = prepare_chunk_payload(chunk)

        ai_response = ["Um", "Dois"]
        mapped = map_ai_response_to_bubbles(ai_response, ordered, dmap)
        self.assertEqual(mapped["One"], "Um")
        self.assertEqual(mapped["Two"], "Dois")

    def test_tag_connected_balloons(self):
        """Verifica detecção de balões conectados que dividem uma fala."""
        bubbles = [
            {"texto_original": "FEELS"},
            {"texto_original": "SOOOOO"},
            {"texto_original": "GOOD!"}
        ]
        tagged = tag_connected_balloons(bubbles)
        self.assertTrue(tagged[0].get("continua_no_proximo"))
        self.assertTrue(tagged[1].get("continua_do_anterior"))
        self.assertTrue(tagged[1].get("continua_no_proximo"))
        self.assertTrue(tagged[2].get("continua_do_anterior"))
        self.assertFalse(tagged[2].get("continua_no_proximo", False))


if __name__ == "__main__":
    unittest.main()
