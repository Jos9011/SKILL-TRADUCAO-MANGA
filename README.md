---
name: manga-translator-scanlation
description: "Pipeline completo para OCR, tradução com Dolphin 2.9 sem censura (Nuvem ou Local), limpeza inteligente de balões, diagramação (typesetting) responsiva, e criação de leitores web para mangás em japonês para português."
risk: low
source: local
date_added: "2026-09-21"
---

# Manga Translator & Scanlation Pipeline (PT-BR) 🐬

[![Abrir Web App Mobile no Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Jos9011/SKILL-TRADUCAO-MANGA/blob/main/Colab_Manga_WebUI.ipynb)
[![Abrir Servidor IA no Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Jos9011/SKILL-TRADUCAO-MANGA/blob/main/Colab_Dolphin_Server.ipynb)

Pipeline profissional de scanlation para processar mangás e doujinshis estrangeiros, extrair textos com OCR (RapidOCR ou Mokuro), traduzir com **IA sem censura (Dolphin 2.9)**, limpar cirurgicamente os balões de diálogo e diagramar em português com qualidade editorial.

---

## ⚡ Como rodar a IA Sem Usar o seu Computador (100% Nuvem)

Para traduzir obras adultas (+18), ecchi ou com violência sem censura e **sem exigir nada da CPU/GPU do seu computador**, você tem duas opções em nuvem prontas:

### Opção 1: OpenRouter Cloud (Mais fácil e rápida)
1. Crie uma conta no [OpenRouter](https://openrouter.ai/) e gere uma API Key.
2. Abra o arquivo `config.json` e adicione a sua chave:
   ```json
   {
     "provider": "openrouter",
     "openrouter_api_key": "sk-or-v1-sua-chave-aqui",
     "openrouter_model": "cognitivecomputations/dolphin-mistral-24b-venice-edition"
   }
   ```
3. Pronto! As traduções serão enviadas para a nuvem da OpenRouter com o modelo Dolphin e o seu computador não esquentará nem consumirá memória.

### Opção 2: Google Colab com GPU Gratuita (100% Gratuito)
1. Abra o arquivo incluído `Colab_Dolphin_Server.ipynb` no [Google Colab](https://colab.research.google.com/).
2. Ative a GPU T4 (**Ambiente de execução** > **Alterar tipo de ambiente de execução** > **T4 GPU**).
3. Clique no botão de Play na célula. Ele instalará o Ollama, baixará o `dolphin-llama3:8b` e gerará uma URL pública Cloudflare (ex: `https://xxxx.trycloudflare.com`).
4. Cole essa URL no seu `config.json`:
   ```json
   {
     "provider": "ollama",
     "ollama_host": "https://xxxx.trycloudflare.com",
     "ollama_model": "dolphin-llama3:8b"
   }
   ```
5. Toda a IA rodará na GPU da nuvem do Google enquanto o script no seu PC apenas insere os textos e gera os capítulos!

---

## 🛠️ Ferramentas e Configuração

* **Arquivo de Configurações:** `config.json`
* **Script Batch de 1-Clique:** `Traduzir_Manga.bat`
* **Destino Automático Padrão:** `C:\Users\ja329\OneDrive\Documentos\MANGAS\<Nome do Manga> [PT-BR]`
* **Notebook do Servidor Colab:** `Colab_Dolphin_Server.ipynb`
* **Script Principal:** `auto_translate.py`

---

## 🚀 Fluxo de Trabalho e Regras Críticas

### 1. Extração OCR e Agrupamento Inteligente (Anti-Intercalação)
* **Clustering Rígido Horizontal (`should_merge_lines`):** Evita fusão acidental de balões ou colunas de texto adjacentes.
* **Leitura Oriental (Mangás JP):** Ordena da Direita para Esquerda, Topo para Baixo.
* **Leitura Ocidental:** Ordena de Cima para Baixo, Esquerda para Direita.

### 2. Tradução com IA Sem Censura (Dolphin 2.9) e Glossário
* **Dolphin 2.9 Especializado (+18):** Prompt otimizado para a arquitetura Dolphin da Cognitive Computations com diretrizes estritas contra vazamento de mensagens do sistema e suporte a termos adultos e gírias brasileiras (`panties` -> calcinha, `cock` -> pau/pinto, `came inside` -> gozou dentro).
* **Tradução em Lote por Página (*Context-Aware*):** Submissão em lote JSON para garantir coerência de gênero, tom e nomes entre os personagens que estão dialogando na mesma cena.
* **Glossário Dinâmico (`glossary.json`):** Respeita nomes fixos de personagens e termos configurados.
* **Fallback Triplo:** OpenRouter / Ollama Remoto / Local -> MyMemory / Google Translator.

### 3. Limpeza Cirúrgica de Balões (Borda Preservada)
* **Detecção de Balões Brancos:** Identifica a área interna do balão e preserva as paredes pretas do desenho.
* **Texto Colorido e Símbolos:** Detecta textos estilizados e corações via espaço de cor HSV.
* **Inpainting Telea:** Para retículas, texturas e fundos artísticos.

### 4. Diagramação Profissional (Multi-Fonte + Diamond Wrap)
* **Suíte Tipográfica:**
  * Diálogos: `fonts/dialogue.ttf` (Comic Neue Bold)
  * Gritos e Ação: `fonts/shout.ttf` (Bangers/Impact)
  * Pensamentos/Sussurros: `fonts/dialogue_italic.ttf` (Comic Neue Bold Italic)
* **Diamond Wrapping & Hifenização Silábica:** Modela o texto segundo a curvatura elíptica do balão com quebra silábica oficial PT-BR (`pyphen`).

### 5. Exportação Automática para `.CBZ` e Leitor Web
* **`.CBZ` Automático:** Arquivo pronto para Tachiyomi, Mihon, Kuro Reader, Kotatsu e Perfect Viewer.
* **Leitor Web Interativo:** `leitor.html` com suporte a teclado (setas/espaço), modo página única e rolagem contínua (*webtoon*).
