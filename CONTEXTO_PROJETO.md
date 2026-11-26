# 📖 Manga Studio — Documento de Contexto do Projeto (Handoff para IA)

> **Finalidade deste documento:** Permitir que qualquer Inteligência Artificial (Claude, ChatGPT, Gemini, Cursor ou Antigravity em nova sessão) compreenda imediatamente todo o escopo, arquitetura técnica, regras mandatórias do projeto, histórico recente e o estado operacional atual do **Manga Studio**.

---

## 1. Identificação Geral do Projeto

* **Nome do Sistema:** **Manga Studio (PT-BR)**
* **Versão Oficial Atual:** **`v0.8.4 Beta` (`0.8.4-beta`)** / APK Android: **`v1.0.14-mobile` (versionCode 15)**
* **Autor / Proprietário:** **Jos9011**
* **Objetivo:** Plataforma completa de scanlation automatizado de alta fidelidade para mangás (japonês), manhwas (coreano), manhuas (chinês) e quadrinhos em inglês/espanhol com destino em **Português do Brasil (PT-BR)**.
* **Repositórios Oficiais no GitHub:**
  1. **`https://github.com/Jos9011/SKILL-TRADUCAO-MANGA`** (Versão PC Desktop e Google Colab Cloud com WebUI).
  2. **`https://github.com/Jos9011/MANGA-STUDIO-ANDROID`** (Aplicativo Nativo Android APK com backend Python embutido via Chaquopy).

---

## 2. Regras de Ouro do Projeto (MANDATÓRIAS PARA QUALQUER IA)

Qualquer IA que atuar neste projeto **DEVE OBEDECER RIGOROSAMENTE** às seguintes regras:

1. **A Regra das 300 Linhas (300-Line Rule):**
   * Nenhum arquivo de código novo ou refatorado deve ultrapassar **300 linhas**.
   * Módulos devem ser pequenos, coesos e desacoplados. Se um módulo crescer, divida-o (ex: separação entre rotas, limpeza de cavidade, diagramação, checagem de cotas).
2. **Regra de Versionamento SemVer Oficial:**
   * **Toda alteração publicada no sistema DEVE atualizar a versão** (`python version.py bump pequeno | medio | grande`).
   * A versão deve ser sincronizada em: `version.py`, `README.md`, `Colab_Manga_WebUI.ipynb`, `studio/server.py`, `studio/templates/index.html` e, no Android, `app/build.gradle`, `mobile_server.py`, `mobile_routes_translation.py`, `.github/workflows/build-apk.yml`.
3. **Zero Secrets no Git:**
   * **NUNCA** commitar chaves de API, tokens ou caminhos com senhas no GitHub.
   * O arquivo `config.json`, pastas de `uploads/`, caches e logs são estritamente cobertos pelo `.gitignore`.
4. **Isolamento de Repositórios:**
   * Manter `SKILL-TRADUCAO-MANGA` (PC/Colab) e `MANGA-STUDIO-ANDROID` (APK) como projetos independentes, porém com suas lógicas de negócio e versões perfeitamente alinhadas.
5. **Links Clicáveis no Chat:**
   * Sempre referenciar arquivos com formato markdown `[arquivo](file:///caminho/com/barras/normais)`.

---

## 3. Arquitetura e Pilares Técnicos do Sistema

O sistema é dividido em submódulos cooperativos:

### A. Arquitetura Cooperativa de Duas IAs (Dual Engine)
* **Agente 1 — Cartógrafo Espacial:**
  * Detecta a disposição geométrica de todos os balões da página.
  * Define a ordem de leitura correta (RTL - Direita para Esquerda / Cima para Baixo para mangás orientais).
  * Calcula o **orçamento de caracteres** de cada balão para impedir que o texto em português transborde a área útil.
* **Agente 2 — Sintetizador Literário / Contextualizador:**
  * Recebe o dossiê da página inteira de uma vez.
  * Compreende gênero dos personagens, duplo sentido, tom emocional e gírias de scanlation em PT-BR sem censura (+18).
  * Gera a tradução de todas as falas em bloco com coerência de cena.
* **Líder do Capítulo + Ficha da Obra (Fase 1, `lider_capitulo.py` / `ficha_obra.py`):**
  * Roda uma vez por capítulo, depois do OCR e antes do laço de tradução do `process_manga`.
  * Lê as falas do capítulo inteiro (sem repetição, cortadas e em partes para caber no limite de ~8k tokens por chamada do Groq) e devolve só novidades: personagens (nome PT-BR, gênero, nota) e termos fixos.
  * Onde grava (`ficha_caminho.py`): pastas soltas por capítulo ("Obra Ch.1", "Obra Ch.2") compartilham `.fichas_obra/<obra>.json` na pasta que as contém (nome da obra = nome da pasta sem "Ch.1", "Lesson 10", "Vol. 3", números e tags); com `Obra/Cap 1`, grava em `Obra/ficha_obra.json`; uma `ficha_obra.json` antiga na pasta do capítulo continua valendo. Só acrescenta; nunca sobrescreve; divergências vão para `"conflitos"`.
  * O Líder registra nomes completos ("Manabu Tokito"), põe apelidos na nota de quem os recebe e descarta palpites ("possível", "talvez").
  * Atenção: a lista do WebUI mostra a pasta da obra, não as subpastas de capítulo; por isso o padrão recomendado é pastas soltas por capítulo.
* **Correções de OCR (`ocr_text_fix.py`):** ordem das linhas por sobreposição vertical real (não mais faixas fixas de 22 px), caixa alta ("OTAKu" -> "OTAKU"), filtro de lixo ("h3") e rejeição de inglês residual em `is_valid_translation`. Também: U lido como L ("QLITE"), "2?" -> "...?", parênteses sem par, e proteção de nomes romanizados contra o wordninja ("TOKITO").
* **Texto sobre o desenho (v0.7.10, `is_text_over_art` / `clean_speech_bubble(..., in_balloon=)`):** fora de balão detectado e com menos de 50% de entorno claro, a limpeza recompõe o desenho por inpainting (em vez de pintar de branco) e o texto é desenhado no lugar da caixa OCR com contorno branco. Créditos ocidentais (`ocr_text_fix.is_credit_text`) não são traduzidos nem apagados.
* **Balão de cada fala (v0.7.12, `balloon_assign.py` / `balloon_color.py`):** a Trava 5 compara o balão com a união de todas as falas dele, com limites folgados para balões ovais altos (as Travas 1-4 do mapa continuam). Balão colorido claro (luma >= 135, não branco) é achado a partir da cor entre as letras: mancha fechada, compacta, borda diferente e sem furos longe do texto; a limpeza recompõe os furos por inpainting. Balão com fala mantida no original não é varrido inteiro. Antes da varredura, "..." numa linha só (o OCR não lê) é recolocado no começo/fim do texto. Sombra clara (cinza 200-249) perto do texto em balão branco é limpa.
* **Posição real das linhas (v0.7.12):** `wrap_balanced_ptbr` mede a largura de cada linha na altura onde ela fica (bloco centrado em `band_center`, preso ao topo/base) e respeita degraus internos do perfil; `compute_safe_text_region` mede larguras simétricas em volta do eixo do texto (quadros em "L"); em balão com degrau o texto fica na altura do original; quando o texto é recentrado na caixa OCR, vale a largura livre nas linhas originais (`free_width_around`).
* **Tipografia de quadros estreitos (`typography_ptbr.py`):** `wrap_balanced_ptbr` aceita mais de 8 linhas quando o quadro é alto e estreito (altura útil >= 1,8x a largura); o último recurso usa `wrap_hard_ptbr`, que nunca passa da largura (antes devolvia o texto numa linha só).
  * A ficha entra no prompt de cada lote do Agente 2 (antes do bloco do RAG). A chamada do Líder usa uma cópia do estado do motor, então nunca esgota nem troca o modelo do tradutor.
  * Config: `"ficha_obra"`, `"lider_capitulo"`, `"lider_model"` (padrão `openai/gpt-oss-120b`); variável `MANGA_FICHA=0` desliga tudo.
  * Ainda não portado para o `MANGA-STUDIO-ANDROID`.

### A2. Interface (v0.8.0) e versão Windows (.exe)
* **Interface:** `studio/templates/index.html` só monta a página; as telas ficam em `studio/templates/partials/*.html`, o estilo em `studio/static/css/*.css` (cores em `base.css`, modo escuro por `data-theme`/sistema) e a lógica em `studio/static/js/*.js` (scripts clássicos, funções globais, carregados em ordem no fim do `<body>`). Todo ID usado pelo JS precisa existir no HTML (`tests/test_library_search.py` confere). Fonte dos títulos: `studio/static/fonts/animeace2_reg.ttf` (sem Google Fonts: o .exe roda sem internet).
* **Pastas (`app_paths.py`):** `CODE_DIR` (código e recursos) e `DATA_DIR` (config, memória, regras, glossário, envios, caches, `models/`). Pelo código as duas são a pasta do projeto; no .exe, `DATA_DIR = %APPDATA%\MangaStudio` (ou `MANGA_STUDIO_DATA`) e a 1ª execução copia os dados de uma instalação antiga ("SISTEMA DE TRADUÇÃO"/"SKILL-TRADUCAO-MANGA" em Documentos) sem sobrescrever nada.
* **.exe:** `manga_studio_app.py` (entrada; `--pick-folder` abre o seletor de pastas, `--self-test` confere o pacote), `manga_studio.spec` (PyInstaller, pasta com o .exe), `requirements-desktop.txt` (RapidOCR fixo em 1.2.3) e `.github/workflows/build-exe.yml` (windows-latest: monta, roda o autoteste e publica `MangaStudio-vX.Y.Z-windows.zip` em Releases a cada push no `main`). `POST /api/shutdown` encerra o servidor (só local, sem tradução rodando).

### A3. Tradução sem depender das cotas (v0.8.1)
* **`quota_wait.py`:** com `"quota_fallback": "wait"` (padrão), quando todas as IAs ficam sem cota o roteador (`execute_translation_request`) espera 10 min e tenta de novo, até 12 h. O aviso passa pelo `progress_cb`, então Parar e Pausar continuam valendo. Com `"google"`, mantém o comportamento antigo (Google literal).
* **`chapter_context.py`:** cada lote do Agente 2 recebe as últimas falas traduzidas (original => tradução) das `context_pages` páginas anteriores (padrão 2) e dos lotes anteriores da mesma página, com no máximo 1.400 caracteres.
* **`gemini_text.py` e `chapter_translator.py`:**
  * O Gemini virou provedor de texto no roteador, depois do OpenRouter e antes do Ollama. Uma recusa por conteúdo não queima a chave.
  * Com `gemini_chapter` (padrão ligado) e uma chave Gemini, o capítulo inteiro vai em lotes de até 120 balões (sem cortar página), cada balão com o campo `pag`, e o resultado preenche o cache antes do laço por página.
* **`ollama_client.py`:**
  * Os pedidos levam `num_ctx` (`ollama_num_ctx`, padrão 16384), `think: false` e espera `ollama_timeout` (padrão 240 s).
  * O estado do servidor fica em cache por 5 min.
  * Escolha de modelo: qwen3 > translategemma > gemma3 > qwen2.5 > … O `dolphin-llama3:latest` antigo vale como automático.
  * `POST /api/test_ollama` mede tokens/s.
* **Provedor `auto`** (padrão na tela Traduzir): o Ollama vem primeiro se o servidor já responder, sem iniciar o servidor sozinho.
* **Notebook `Colab_IA_Local.ipynb`:** roda no Colab e no Kaggle, com `OLLAMA_CONTEXT_LENGTH`, teste PT-BR e URL do túnel em destaque.

### A4. Instalador da IA local no PC (v0.8.2)
* **Arquivos:** `Instalar_IA_Local.bat` chama `instalar_ia_local.ps1` (PowerShell 5.1, UTF-8 com BOM, CRLF).
* **O que o script faz:**
  * detecta a placa de vídeo dedicada e a VRAM (pelo registro);
  * escolhe o plano: 14 GB ou mais = qwen3:14b/16k/first; 10 GB = qwen3:8b/16k/first; 6 GB com 12 GB ou mais de RAM = qwen3:8b/8k/fallback; abaixo disso = gemma3:4b/8k/fallback (reserva dos planos 8b também é gemma3:4b; v0.8.3);
  * instala o Ollama (winget ou OllamaSetup.exe);
  * em AMD, liga `OLLAMA_VULKAN=1` e `GGML_VK_VISIBLE_DEVICES` com a GPU dedicada (via vulkaninfo);
  * baixa o modelo, mede tokens/s e troca para o modelo reserva abaixo de 6 tok/s;
  * grava `ollama_host`, `ollama_model`, `ollama_num_ctx`, `ollama_priority` e `ollama_timeout` no config.json, sem BOM.
* **Onde grava:** no config da pasta do projeto, se houver. No `%APPDATA%\MangaStudio\config.json` só se ele já existir ou se o script estiver junto do .exe, para não atrapalhar a migração da 1ª execução.
* **`-Simular`:** só detecta e mostra o plano. O GitHub Actions roda esse modo no Windows.
* **`ollama_priority`:** `"first"` (padrão) põe a IA local antes da nuvem no modo Automático. `"fallback"` deixa a nuvem primeiro, e o roteador tenta o Ollama antes de esperar a cota.

### A5. Andamento da IA local (v0.8.3)
* **Sintoma:** com a cota da nuvem esgotada, o registro parava em "Modelo 'qwen3:4b' ativo com sucesso!" e parecia travado.
* **Causa:** o pedido ao Ollama era sem streaming e sem nenhum log até a resposta. Num modelo parcial na CPU, uma página leva minutos.
* **`ollama_client.chat(..., label=modelo)`:**
  * usa streaming; o timeout vale por trecho recebido;
  * escreve "traduzindo...", um aviso a cada `HEARTBEAT_SECS` (30 s) e um resumo no fim (segundos, `prompt_eval_count`, `eval_count`, tokens/s);
  * um `{"error": ...}` no meio do stream vira RuntimeError.
* **`gpu_share()` + `describe_placement()`:** lê `/api/ps` (`size_vram`/`size`) depois do aquecimento e avisa quanto do modelo ficou no processador.
* **Cache de status:** com `ollama_model` fixo, ignora o modo adulto na chave, para não aquecer duas vezes.
* **Lote fora do formato JSON:** `translate_page_dialogue` avisa no registro antes de traduzir balão por balão.
* **Qwen3 pensando em voz alta:** confirmado no PC do usuário (Ollama ignorava `"think": false`). Cada balão batia nos 350 tokens de raciocínio (~64 s a 5,4 tok/s), a tradução saía cortada e era refeita.
  * `_no_think()` acrescenta `/no_think` (chave oficial do Qwen3) à mensagem de sistema, ou à última do usuário, só em modelos qwen3, sem alterar a lista original.
  * `clean_answer()` remove `<think>…</think>` e descarta raciocínio sem fechamento.
  * O `qwen3:4b` atual do Ollama é o Qwen3-4B-Thinking-2507 (context length 262144, `thinking default true`): nem `think: false` nem `/no_think` desligam. O instalador agora usa `gemma3:4b`, e `pick_model` só escolhe `qwen3:4b`/`*-thinking*` se não houver outro modelo (a escolha do usuário em Configurações sempre vence).

### A6. Colorização: mescla do traço (v0.8.4)
* **Antes:** `colorize_cv2` trocava o Y (YCrCb) da cor pelo cinza da página. Papel branco (pele no mangá) = Y 255 e a cor estourava para amarelo pálido com manchas rosa nas retículas.
* **`merge_lineart(color, gray)` (Lab):**
  * `L = min(L_cor * (1 - PAPER_BLEND) + L_original * PAPER_BLEND, L_original)`;
  * a/b escalados por `min(L_novo / L_cor, 1) * COLOR_SATURATION`, para o traço preto não ficar marrom;
  * `PAPER_BLEND = 0.5` e `COLOR_SATURATION = 0.7` foram ajustados comparando com a colorização oficial da personagem loira. Com saturação 1, o loiro sai laranja; com 0.35/1.0, a pele fica forte demais.
* **Saída do modelo ONNX:** já vem em [0,1] (entrada cinza [0,1], 4 canais de dica zerados). Normalizar para [-1,1] deixa tudo cinza.
* **Download:** vai para `.part` e só é renomeado se tiver mais de 10 MB; a falha apaga o `.part`.
* **Pendente:** DirectML para AMD/Intel no Windows (o `onnxruntime-directml` conflita com o `onnxruntime` exigido pelo rapidocr; precisa de teste em máquina real).

### B. OCR IA Vision Híbrido
* Combina um **detector geométrico local (RapidOCR / PP-OCR)** para traçar as caixas com uma **IA Vision Multimodal** para transcrever o texto original direto da imagem (reconhecendo fontes estilizadas e onomatopeias).
* Suporta **Google Gemini**, **Groq Vision**, **OpenRouter Vision** e **Ollama Vision**.
* **Fallback Automático e Silencioso:** Se a visão na nuvem sofrer bloqueio de segurança (+18) ou esgotamento de cota, o sistema recua imediatamente para o OCR clássico sem travar a tradução.

### C. Limpeza de Cavidade do Balão & Proteção Anti-Vazamento P&B
* Módulos: `balloon_cavity.py` (PC) e `mobile_balloon_cleaner.py` (Android).
* Varre 100% da cavidade interna fechada de balões brancos, apagando letras órfãs, "I" solto e ruídos de escaneamento sem danificar o contorno preto.
* **5 Travas Matemáticas Anti-Vazamento:** Impede que balões abertos/nuvem em mangás preto e branco vazem flood-fill branco para pele e cabelo claro dos personagens. Em caso de vazamento detectado (`open_sides >= 2`, `holes_ratio > 0.26`, `fill_ratio > 0.72`), aborta a expansão e aplica limpeza cirúrgica restrita à caixa do texto.

### D. Tipografia PT-BR e Diagramação Responsiva
* Módulos: `typography_ptbr.py` (PC) e `mobile_typesetter.py` (Android).
* Fontes embutidas: `Anime Ace`, `Komika Axis`, `Shout` e `Dialogue`.
* Calibração fina de entrelinha (`1.22` normal, `1.15` apertado), medição real de altura de acentos maiúsculos em português (`ÁÇÃÊÓÚg`) e filtro anti-hifenização em palavras curtas (`min_len=8`).

### E. Colorização Automática por IA (ONNX)
* Módulo: `studio/colorizer_engine.py` (PC/Colab).
* Utiliza modelo leve de rede neural em ONNX para colorir páginas P&B automaticamente em segundos, com suporte a imagem de referência para ancorar as cores dos personagens.

### F. Leitor Web Offline e Exportação CBZ
* Ao término da tradução, gera um leitor interativo HTML standalone (`leitor.html`) e um arquivo compactado `.cbz` com as páginas tratadas e traduzidas.

---

## 4. Onde Ficam as Configurações e Chaves de API

* **Local do Perfil Persistente:** `G:\Meu Drive\.manga_studio\config.json`
  * Este arquivo é compartilhado entre PC, Google Colab e celular via Google Drive.
* **Chaves e Provedores Configurados Atualmente:**
  1. **Google Gemini (Vision & Tradução):**
     * Modelo Ativo: **`gemini-3.1-flash-lite`** (Ultra-rápido, gratuito, sem limites de TPM severos).
     * Chave Configurada: Chave oficial Google AI Studio com prefixo `AQ.` ativa e operacional.
  2. **Groq Cloud:**
     * Modelo Padrão: **`qwen/qwen3.8-27b`** (Fallback: `openai/gpt-oss-120b`).
     * Chaves Cadastradas: 5 chaves (observação: chaves de uma mesma organização compartilham a cota diária de 200k tokens).
  3. **OpenRouter:**
     * Modelo Padrão: **`nvidia/nemotron-3.5-lightning:free`**.
  4. **Ollama (Local / GPU):**
     * Suporte a servidor local (`http://localhost:11434`), ativo no PC e no Colab, desativado no Android.

---

## 5. Como Executar Cada Ambiente

* **No PC Desktop (Windows):**
  * Iniciar via `C:\Users\ja329\Desktop\Manga_Studio.bat` ou rodando `python studio/server.py` no repositório.
* **No Google Colab (Cloud):**
  * Abrir o notebook `Colab_Manga_WebUI.ipynb` no Google Colab, selecionar GPU e executar as células.
  * O servidor sobe via Cloudflare Tunnel com token secreto criptográfico: `https://xxxx.trycloudflare.com/?token=SEU_TOKEN`.
* **No Celular Android:**
  * Instalar o APK gerado no GitHub Actions (`MANGA-STUDIO-ANDROID/releases/download/v1.0.9-mobile/app-debug.apk`).
  * O app roda um servidor Flask em segundo plano via Chaquopy na porta interna `8080` e abre a WebView nativa.
