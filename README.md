---
name: manga-translator-scanlation
description: "Pipeline completo para OCR, tradução, limpeza inteligente de balões, diagramação (typesetting) responsiva, e criação de leitores web para mangás em japonês para português."
risk: low
source: local
date_added: "2026-09-21"
---

# Manga Translator & Scanlation Pipeline (PT-BR)

Este skill contém todo o conhecimento, ferramentas e procedimentos para processar mangás e doujinshis estrangeiros, extrair textos com OCR (RapidOCR), traduzir, apagar perfeitamente os textos originais e injetar o texto em português (Typesetting).

---

## 🛠️ Ferramentas e Localizações

* **Script Batch de 1-Clique:**
  `C:\Users\ja329\tools\manga-translator\Traduzir_Manga.bat`
  *(Basta arrastar a pasta do mangá para cima do ícone do `.bat` ou executá-lo)*
* **Destino Automático Fixo:**
  `C:\Users\ja329\OneDrive\Documentos\MANGAS\<Nome do Manga> [PT-BR]`
* **Script de Automação Completa:**
  `C:\Users\ja329\tools\manga-translator\auto_translate.py`
* **Python Executável:**
  `C:\Users\ja329\AppData\Local\Python\bin\python.exe`

---

## 🚀 Fluxo de Trabalho e Regras Críticas

O script `auto_translate.py` funciona num loop de processamento autônomo com barra de progresso (`tqdm`) em três etapas vitais:

### 1. Extração OCR e Agrupamento Inteligente de Linhas (Anti-Intercalação)
Para que as traduções façam sentido, as linhas fracionadas de um balão devem ser agrupadas numa frase única sem fundir balões vizinhos:
* **Clustering Rígido Horizontal (`should_merge_lines`):** Exige sobreposição real de caixas horizontais (`overlap_ratio_x >= 0.40`) com tolerância estrita de centros, ou sobreposição quase total (`>= 0.65`). Evita 100% a fusão acidental de balões ou colunas de texto adjacentes que compartilham faixas de altura semelhantes.
* **Leitura Oriental (Mangás JP):** Se as linhas forem verticais (`altura > largura * 1.2`), agrupa por sobreposição no eixo Y e proximidade no eixo X, ordenando da Direita para Esquerda, Topo para Baixo.
* **Leitura Ocidental:** Agrupa por proximidade vertical e alinhamento horizontal, ordenando de Cima para Baixo, Esquerda para Direita.

### 2. Tradução com IA Local (Ollama Chat API) e Fallbacks
* **Motor Local Prioritário (Ollama Chat API):** Utiliza `/api/chat` com mensagens estruturadas (`system` e `user`) priorizando modelos literários de alta fidelidade (ex: `llama3.1:latest`, `dolphin-llama3:latest`) na porta 11434. Totalmente offline e imune a erros de quota ou 401.
* **Tradução Determinística Anti-Alucinação (`temperature: 0.0`):** Persona estrita de scanlation que proíbe saudações de chatbot, notas explicativas e suposições fora de contexto.
* **Tratador Avançado de SFX e Gemidos:** Decomposição e tradução de onomatopeias e sons repetidos/compostos (ex: `SLAP SLAPI`, `TWITCH TWITCH`, `ZUP ZUP`) via dicionário direto antes da IA, impedindo alucinações.
* **Dicionário Anatômico e Gírias (+18):** Filtro contextual rigoroso para termos adultos de mangá e gírias brasileiras fluidas.
* **Fallback Nuvem:** Fallback automático para `MyMemoryTranslator` e `GoogleTranslator` caso o Ollama esteja offline.

### 3. Limpeza Cirúrgica de Balões (Algoritmo Borda-Preservada)
Ao limpar um balão de texto, o sistema nunca destrói a borda do desenho ou arte externa:
* **Detecção de Balões Brancos (`white_ratio > 0.45`):** Identifica a área interna do balão.
* **Suporte a Texto Colorido e Corações:** Detecta tanto texto escuro (`gray < 175`) quanto textos estilizados em rosa/vermelho/azul e corações flutuantes através do espaço HSV (`hsv[:, :, 1] > 25`).
* **Preservação de Bordas:** Utiliza análise de contornos no ROI. Contornos que tocam as margens externas (as paredes pretas do balão) são preservados; elementos flutuantes no interior são limpos cirurgicamente com branco puro.
* **Para Retículas/Cabelos/Arte de Fundo:** Aplica inpainting Telea suave com raio de 4px.

### 4. Extração OCR com Realce de Cor (RapidOCR)
* Pré-processamento por canal mínimo (`img.min(axis=2)`): transforma textos estilizados com tons claros ou coloridos (rosa choque, vermelho, ciano) em alto contraste com o fundo branco, permitindo que o RapidOCR leia títulos e onomatopeias coloridas que seriam ignorados em tons de cinza comuns.
* **Filtro de Páginas de Crédito/Scanlation:** Identifica automaticamente páginas de recrutamento, créditos e links de scanlators (ex: Omega Scans) para preservá-las 100% intactas, sem desenhar caixas de tradução ou estragar a arte.

### 5. Diagramação Responsiva com Limites Seguros (Safe Balloon Boundary)
A inserção do português (`fit_text_to_box`):
* **Sondagem de Limites Seguros (*Safe Boundary*):** Antes de renderizar, o sistema varre a máscara limpa para detectar os limites brancos reais do balão (`b_left`, `b_right`, `b_top`, `b_bottom`) e aplica margem de segurança de 10px. O texto nunca vaza a borda preta do balão para invadir a arte.
* **Fonte dinâmica:** Calculada a partir das dimensões reais do balão (iniciando em até 68px para balões grandes e escalando até 12px para balões estreitos).
* Teste iterativo de quebras de linha para encontrar a melhor distribuição espacial com centralização geométrica (`anchor="mm"`).
* Tipografia profissional com Comic Sans MS Bold e contorno (*stroke*) proporcional para leitura perfeita em qualquer contraste.

### 6. Renderização Segura Temp -> Nuvem
Devido a problemas de bloqueio por sincronização no Windows/OneDrive (`PermissionError`), todas as imagens e o `leitor.html` interativo são processados e salvos num diretório temporário isolado (`%TEMP%`). Ao finalizar com sucesso, os arquivos finais e o leitor são copiados via `shutil.copy2` para o drive de destino.
