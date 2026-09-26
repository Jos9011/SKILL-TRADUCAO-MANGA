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

### 2. Tradução com IA Local (Ollama Chat API Contextual) e Glossário
* **Tradução em Lote por Página (*Context-Aware*):** Em vez de traduzir balão por balão cegamente, o sistema agrupa os balões da página e os submete em bloco JSON ao Ollama. A IA traduz a cena completa com total consciência de quem fala com quem, mantendo coerência nos pronomes, gênero e fluidez de diálogo.
* **Glossário Personalizado por Obra (`glossary.json` / `termos.txt`):** Suporte a termos e nomes de personagens customizados (ex: Rudy, Roxy, Sylphy, Misha, Lovemea). O glossário é injetado diretamente nas diretrizes da IA e aplicado pós-tradução.
* **Tradução Determinística Anti-Alucinação (`temperature: 0.0`):** Persona estrita de scanlation que proíbe saudações de chatbot, notas explicativas e suposições fora de contexto.
* **Tratador Avançado de SFX e Gemidos:** Decomposição e tradução de onomatopeias e sons repetidos/compostos (ex: `SLAP SLAPI`, `TWITCH TWITCH`, `ZUP ZUP`) via dicionário direto antes da IA, impedindo alucinações.
* **Dicionário Anatômico e Gírias (+18):** Filtro contextual rigoroso para termos adultos de mangá e gírias brasileiras fluidas (`tip` -> ponta/glande; `panties` -> calcinha; `sucking` -> chupando).
* **Fallback Nuvem:** Fallback automático para `MyMemoryTranslator` e `GoogleTranslator` caso o Ollama esteja offline.

### 3. Limpeza Cirúrgica de Balões (Algoritmo Borda-Preservada)
Ao limpar um balão de texto, o sistema nunca destrói a borda do desenho ou arte externa:
* **Detecção de Balões Brancos (`white_ratio > 0.45`):** Identifica a área interna do balão.
* **Suporte a Texto Colorido e Corações:** Detecta tanto texto escuro (`gray < 175`) quanto textos estilizados em rosa/vermelho/azul e corações flutuantes através do espaço HSV (`hsv[:, :, 1] > 25`).
* **Preservação de Bordas:** Utiliza análise de contornos no ROI. Contornos que tocam as margens externas (as paredes pretas do balão) são preservados; elementos flutuantes no interior são limpos cirurgicamente com branco puro.
* **Para Retículas/Cabelos/Arte de Fundo:** Aplica inpainting Telea suave com raio de 4px.

### 4. Extração OCR e Filtro de Páginas Especiais (Créditos, Doações, Colofão)
* **Realce de Cor (RapidOCR):** Pré-processamento por canal mínimo (`img.min(axis=2)`): transforma textos estilizados com tons claros ou coloridos em alto contraste com o fundo branco.
* **Filtro de Páginas de Crédito, Redes Sociais e Doações:** Identifica automaticamente páginas de recrutamento, créditos de scanlators, links sociais (Twitter/X, Pixiv, Discord) e páginas de doação (Ko-fi, Patreon, Comiket, colofão de doujinshi) para preservá-las 100% intactas, sem desenhar caixas de tradução ou estragar a arte.

### 5. Diagramação Profissional de Scanlation (Multi-Font + Diamond Wrap)
A inserção do português (`fit_text_to_box`):
* **Suíte Tipográfica Multi-Fonte Scanlation (`fonts/`):**
  * *Diálogo Padrão:* `dialogue.ttf` (Comic Neue Bold - limpa, moderna e altamente legível).
  * *Gritos e Ação:* `shout.ttf` (Bangers Regular / Impact para exclamações e balões espinhosos).
  * *Pensamentos e Sussurros:* `dialogue_italic.ttf` (Comic Neue Bold Italic para diálogos suaves e monólogos internos).
* **Diagramação em Diamante/Elipse (*Diamond Wrapping*):** Modela a largura das linhas de texto segundo a curvatura elíptica natural dos balões de mangá. As linhas do meio têm maior extensão que as pontas superior e inferior, preenchendo o balão de forma harmônica e estética.
* **Hifenização Silábica Correta (PT-BR via `pyphen`):** Quando uma palavra longa excede a linha, o sistema aplica quebra silábica oficial da língua portuguesa com hífen (`-`), evitando que a fonte inteira seja diminuída ou que ocorram espaços esquisitos.
* **Sondagem de Limites Seguros (*Safe Boundary*):** Antes de renderizar, o sistema varre a máscara limpa para detectar os limites brancos reais do balão e aplica margem de segurança de 10px. O texto nunca vaza a borda preta do balão para invadir a arte.
* **Contorno e Centralização Geométrica:** Texto renderizado com ponto de ancoragem `mm` (centro exato) e contorno branco proporcional de contraste.

### 6. Exportação Automática para `.CBZ` e Leitor Web
* **Arquivo `.CBZ` Automático:** Gera imediatamente um arquivo compactado `<Nome do Manga> [PT-BR].cbz` ao lado da pasta final, pronto para leitura direta em aplicativos móveis e tablets (Tachiyomi, Mihon, Kotatsu, Perfect Viewer, Kuro Reader).
* **Leitor Web Interativo:** Gera `leitor.html` com suporte a navegação por teclado (setas/espaço), modo página única e modo rolagem contínua (*webtoon*).
* **Renderização Segura Temp -> Nuvem:** Processamento em diretório temporário isolado (`%TEMP%`) para total imunidade a bloqueios de sincronização do OneDrive.
