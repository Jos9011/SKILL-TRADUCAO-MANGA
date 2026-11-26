---
name: manga-translator-scanlation
description: "Pipeline completo para OCR, tradução com Dolphin 2.9 sem censura (Nuvem ou Local), limpeza inteligente de balões, diagramação (typesetting) responsiva, e criação de leitores web para mangás em japonês para português."
risk: low
source: local
date_added: "2026-09-21"
---

# Manga Studio v0.8.3 Beta - Tradutor & Editor de Mangás (PT-BR) 🚀

[![Versão](https://img.shields.io/badge/versão-v0.8.3--beta-brightgreen.svg)](#)
[![Abrir Web App Mobile no Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Jos9011/SKILL-TRADUCAO-MANGA/blob/main/Colab_Manga_WebUI.ipynb)
[![Colorir Mangás com GPU no Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Jos9011/SKILL-TRADUCAO-MANGA/blob/main/Colab_Colorir_Manga.ipynb)
[![Treinar IA Própria (Unsloth) no Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Jos9011/SKILL-TRADUCAO-MANGA/blob/main/Colab_Treinar_Qwen_Manga.ipynb)
[![Abrir Servidor IA no Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Jos9011/SKILL-TRADUCAO-MANGA/blob/main/Colab_Dolphin_Server.ipynb)

Plataforma profissional de scanlation para tradução, OCR e diagramação de mangás, manhwas e doujinshis com **Arquitetura Cooperativa de Duas IAs (v0.2.0 Beta)**:

1. **Agente 1 (Cartógrafo Espacial):** Mapeia a geometria dos balões, aspect ratio, ordem oriental de leitura (Direita para Esquerda, Topo para Baixo) e calcula o orçamento máximo de caracteres (`max_chars`) para evitar vazamento ou sobreposição de arte.
2. **Agente 2 (Sintetizador Literário & Narrativo):** Analisa a cena completa, concordância de gênero estrita, dinâmicas interpessoais e gírias de scanlation brasileira sem censura, respeitando rigorosamente a capacidade calculada pelo Agente 1.
3. **Gerenciador de Biblioteca & Perfil Persistente (Novo no v0.2.0):** Exclusão direta de obras com um clique, e retenção permanente de chaves de API com sincronização híbrida entre Google Drive e navegador.

---

## 🪟 Baixar para Windows (.exe, sem instalar Python)

1. Abra a página [Releases](https://github.com/Jos9011/SKILL-TRADUCAO-MANGA/releases) e baixe o arquivo `MangaStudio-v…-windows.zip` mais recente.
2. Clique com o botão direito no `.zip`, escolha **Extrair tudo** e abra a pasta `MangaStudio`.
3. Clique duas vezes em `MangaStudio.exe`. Ele abre numa janela própria (Chrome ou Edge).
   Na primeira vez o Windows pode avisar "O Windows protegeu o computador": clique em **Mais informações** e **Executar assim mesmo**.
4. Para fechar, use **Encerrar Manga Studio** no rodapé da barra lateral.

Seus dados (chaves, memória de traduções, regras e glossário) ficam em `%APPDATA%\MangaStudio`. Quem já usava o sistema pelo código tem esses arquivos copiados na primeira execução. Cada versão nova publicada no `main` gera um `.zip` novo automaticamente (GitHub Actions, `.github/workflows/build-exe.yml`).

Para montar o `.exe` no seu PC: `pip install -r requirements-desktop.txt pyinstaller` e `pyinstaller manga_studio.spec` (sai em `dist\MangaStudio`).

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

> **v0.8.1:** use o notebook [`Colab_IA_Local.ipynb`](https://colab.research.google.com/github/Jos9011/SKILL-TRADUCAO-MANGA/blob/main/Colab_IA_Local.ipynb) (Qwen3, contexto de 16 mil tokens, também roda no Kaggle) e cole a URL em Configurações > IA local.
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
* **Memória por Semelhança (RAG leve, `rag_memory.py`):** A cada lote, busca em `memoria_traducoes.json` as frases já traduzidas mais *parecidas* (não só idênticas, tolerando ruído de OCR) e envia até 8 como exemplo para a IA. Roda em Python puro no PC, Colab e Android. Desligue com `"rag_memory": false` no `config.json` ou `MANGA_RAG=0`. Teste manual: `python rag_memory.py "早安！"`.
* **Ficha da Obra + Líder do Capítulo (`ficha_obra.py`, `ficha_caminho.py`, `lider_capitulo.py`):** Depois do OCR e antes de traduzir, um Líder (`openai/gpt-oss-120b` por padrão, configurável em `"lider_model"`) lê as falas do capítulo inteiro e registra só as novidades: personagens com nome completo e gênero (apelidos vão na nota de quem os recebe) e termos próprios da obra. Palpites ("possível...", "talvez...") são descartados. A ficha vai no prompt de cada lote, para nomes e gêneros ficarem iguais em todos os capítulos. Não é preciso reorganizar as pastas: capítulos em pastas soltas ("Obra Ch.1", "Obra Ch.2", "Lesson 3"...) compartilham `.fichas_obra/<nome da obra>.json` na pasta que os contém; com subpastas (`Obra/Cap 1`), a ficha fica em `Obra/ficha_obra.json`. O Líder só acrescenta: nunca muda o que já está na ficha (você pode editar o JSON à mão) e anota divergências em `"conflitos"`. Cada capítulo é lido uma vez; para ler de novo, apague o capítulo de `"capitulos_lidos"`. Desligue com `"ficha_obra": false` ou `MANGA_FICHA=0`; para usar a ficha sem gastar a chamada do Líder, `"lider_capitulo": false`.
* **Correções do OCR e anti-inglês (`ocr_text_fix.py`):** linhas de cada balão ordenadas pela sobreposição vertical real (antes, quadros de narração com linhas próximas saíam embaralhados: "MUCH SO HAS CHANGED"); minúsculas soltas corrigidas em balões em CAIXA ALTA ("OTAKu" -> "OTAKU"); blocos de lixo como "h3" (efeito sonoro desenhado lido errado) não são traduzidos nem apagados; traduções com palavras inglesas copiadas do original ("YOU'RE SO inteligente") são rejeitadas e refeitas. Também corrige U lido como L em CAIXA ALTA ("QLITE" -> "QUITE", "YOLR" -> "YOUR"), "...?" lido como "2?", parênteses soltos, e impede que o separador de palavras quebre nomes japoneses ("TOKITO" virava "TOKI TO").
* **Quadros de narração estreitos (`typography_ptbr.py`):** quadros altos e estreitos aceitam mais de 8 linhas, e o último recurso nunca passa da largura do quadro (antes o texto podia sair numa linha só, minúscula, atravessando a página).
* **Busca na Biblioteca:** campo de busca fixo no topo da aba Biblioteca que procura nas obras traduzidas e nas originais, ignorando maiúsculas, acentos e pontuação e aceitando as palavras em qualquer ordem ("gal kuro" ou "toshiue ch1" encontram "Toshiue no Kuro Gal ... Ch.1"). Mostra quantas obras foram encontradas, avisa quando nada foi encontrado e tem botão ✕ (ou ESC) para limpar. A janela de escolher obra do Google Drive usa a mesma busca.
* **Texto solto sobre o desenho e créditos (v0.7.10):** texto fora de balão com contorno branco por cima da arte (ex.: "HERE! PJS!") não vira mais um retângulo branco: as letras são apagadas, o desenho é recomposto (inpainting) e a tradução é escrita no mesmo lugar com contorno branco. Créditos de scan ("TRANSLATED BY DOUJINS.COM", "discord.gg", "Traduzido por ...") ficam intactos, sem tradução. Palavras compostas quebradas na linha ("STATE-OF-" / "THE-ART") mantêm o hífen.
* **IA local mostra o andamento (v0.8.3):** antes ela trabalhava em silêncio e parecia travada.
  * **No registro:** "traduzindo...", um aviso a cada 30 s e, no fim, o tempo, os tokens lidos e escritos e a velocidade.
  * **Placa ou processador:** ao ligar, diz se o modelo está 100% na placa de vídeo ou quanto ficou no processador (o que deixa tudo lento).
  * **Qwen3 sem "pensar em voz alta":** antes ele gastava cerca de 1 min por balão raciocinando antes de traduzir. Agora responde direto.
  * **Aquecimento:** feito uma vez só por modelo, e a resposta chega em partes (o tempo de espera vale por trecho, não pela resposta inteira).
* **IA local no seu PC com um clique (v0.8.2):** `Instalar_IA_Local.bat` (também dentro do `.zip` do `.exe`).
  * **O que faz:** detecta a placa de vídeo, instala o Ollama, baixa o modelo que cabe nela (Qwen3 14B ou 8B, ou Gemma 3 4B nas placas menores), mede a velocidade (troca para um modelo menor se ficar lento) e liga tudo ao Manga Studio.
  * **AMD sem ROCm (ex.: RX 5000):** usa o Vulkan.
  * **Placas de 6 a 8 GB:** a IA local entra quando a nuvem fica sem cota (opção nova em Configurações > IA local).
* **Tradução com contexto e sem depender das cotas (v0.8.1):**
  * **Cotas acabaram:** quando todas as IAs ficam sem cota, o sistema espera a cota renovar e continua, em vez de cair no Google Tradutor literal. Dá para mudar em Configurações > Tradução.
  * **Contexto entre páginas:** cada pedido leva as últimas falas já traduzidas das páginas anteriores.
  * **Capítulo inteiro no Gemini:** com chave Gemini, ele traduz o capítulo inteiro de uma vez, lendo a história toda e gastando poucos pedidos. Páginas recusadas por conteúdo +18 seguem o caminho normal. O Gemini também passou a ser uma IA de tradução, não só de leitura de imagem.
  * **IA local:** contexto de 16 mil tokens (antes o Ollama cortava o texto em silêncio), modelos atuais (Qwen3), teste de velocidade e o notebook `Colab_IA_Local.ipynb`, que funciona no Colab e no Kaggle.
  * **Motor "Automático":** usa a IA local se estiver ligada, depois Gemini, Groq e OpenRouter.
* **Interface nova e versão .exe (v0.8.0):** visual de mesa de desenho (papel, nanquim e lápis azul) com modo escuro; Traduzir em três etapas com atalhos para os capítulos da pasta de originais; Biblioteca com capas e menu "Mais"; Cotas por conta com barras de uso; Configurações com índice lateral e botão Salvar sempre visível; botão "Encerrar Manga Studio". O programa também sai como `MangaStudio.exe` para Windows.
* **Limpeza do balão inteiro e balões coloridos (v0.7.12):** a varredura completa do balão agora roda na maioria dos balões (antes, uma trava recusava balões altos com pouco texto e balões com duas falas; na página de teste, 25 de 37). Balões coloridos (rosa, azul, amarelo, cinza médio) também são reconhecidos e limpos por inteiro, inclusive letras que o OCR não leu. Reticências soltas numa linha ("...") que o OCR não lê voltam para o texto traduzido em vez de sumir. Com a área real do balão, o texto fica maior; quadros em degrau ou com recorte não são mais invadidos.
* **Acabamento dos balões (v0.7.11):** sem "sombra" do texto original em balões brancos (a borda antisserrilhada das letras também é limpa); em quadros pequenos, o texto tenta caber com palavras inteiras antes de hifenizar, e o hífen respeita as sílabas ("MU-DARAM", nunca "MUD-ARAM" ou "ESTÃ-O"); quadros de narração encostados não empurram mais o texto para fora do quadro.
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

---

## 🎨 Colorização Automática de Mangás com IA Neural (Novo!)

O Manga Studio agora conta com um motor completo de colorização neural profunda baseado na arquitetura U-Net otimizada (ONNX FP16 ~58MB):

* **Abordagem B (Integrada na WebUI & CLI):**
  - **Pill Selector:** Ative a opção `🎨 Colorir Mangá` para traduzir e colorir as ilustrações simultaneamente, mantendo o interior dos balões perfeitamente limpos e o texto PT-BR nítido.
  - **Botão "🎨 Colorir Apenas":** Coloriza todas as páginas de uma obra sem traduzir.
  - **Terminal / CLI:** Execute `python manga_colorizer.py "caminho/do/manga"` ou passe `--colorize` no `auto_translate.py`.
  - **Preservação de Nanquim (`preserve_lineart`):** Mescla o traço original no canal de luminância, evitando borrões na tinta preta.

* **Abordagem A (Google Colab com GPU Gratuita/Pro):**
  - **Notebook Dedicado:** Abra o [Colab_Colorir_Manga.ipynb](Colab_Colorir_Manga.ipynb) diretamente no Google Colab.
  - **Aceleração CUDA:** Processa em ~0.5s a 1.5s por página nas GPUs gratuitas T4 ou GPUs Pro (V100/A100).
  - **Direto do Google Drive:** Lê da pasta de entrada (ex: `G:\Meu Drive\MANGAS [PT-BR]`), salva em `[COLORIDO]` e empacota automaticamente em `.cbz`!
