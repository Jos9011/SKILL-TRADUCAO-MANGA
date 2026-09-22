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

### 1. Extração OCR e Agrupamento Inteligente de Leitura Oriental
Para que as traduções façam sentido, as linhas fracionadas de um balão devem ser reagrupadas numa frase única:
* O sistema calcula a proporção da caixa de texto detectada pelo OCR.
* **Leitura Oriental (Mangás JP):** Se as linhas forem verticais (`altura > largura * 1.2`), o sistema as agrupa checando se há sobreposição no eixo Y e proximidade no eixo X. Ele ordena as linhas da Direita para Esquerda, Topo para Baixo, garantindo que frases japonesas sejam montadas corretamente.
* **Leitura Ocidental:** Agrupa checando proximidade no eixo Y e ordena de Cima para Baixo, Esquerda para Direita.

### 2. Tradução com Fallback e Cooldown
* Utiliza o idioma base detectado dinamicamente no OCR (via amostragem Regex de Hangul, Kana/Kanji ou Latino).
* Realiza consultas via `MyMemoryTranslator` (fallback para `GoogleTranslator`).
* **Regra Crítica:** Obrigatório possuir `time.sleep(0.1)` por balão e `time.sleep(1)` para fallbacks para evitar limites de API (TooManyRequests).

### 3. Limpeza Cirúrgica de Balões (Inpainting Inteligente)
Ao limpar um balão de texto, nunca desenhe um simples retângulo branco sobre as coordenadas máximas do OCR, pois isso corta a arte ou borda redonda preta do balão! 
Em vez disso:
* Usa-se o array individual das linhas detectadas (`raw_boxes`).
* Se for texto vertical (JP), expande as caixas 12px horizontalmente (`pad_x=12`) para capturar todo o Furigana (rubys).
* **Para Fundos Brancos (`gray_roi > 210`):** Faz-se uma máscara dilatada APENAS dos pixels escuros (`< 160`) e então pinta especificamente esses traços com branco puro, preservando a arte ao redor!
* **Para Retículas/Cabelos/Arte:** Faz o inpainting normal de 5px.

### 4. Diagramação Responsiva (Typesetting)
A inserção do português (`fit_text_to_box`):
* Fonte dinâmica que encolhe gradualmente de 24px até 10px tentando combinar de 1 até 10 quebras de linha para encontrar a distribuição com o maior preenchimento horizontal e vertical possível no espaço útil do balão.
* Utiliza `stroke_width=3` de branco para sempre garantir leitura impecável mesmo sobre linhas de cenário.

### 5. Renderização Segura Temp -> Nuvem
Devido a problemas de bloqueio por Sincronização no Windows/OneDrive (`PermissionError`), todas as imagens e o `leitor.html` interativo devem ser processados e salvos num diretório `%TEMP%`. Só depois de tudo terminado os arquivos são copiados via `shutil.copy2` para o drive de destino.
