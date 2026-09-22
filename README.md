# 📖 Guia de Tradução e Diagramação Automática de Mangás

Este kit de ferramentas foi criado para transformar mangás em japonês em versões diagramadas e traduzidas para português brasileiro (PT-BR).

---

## 📁 Onde estão os arquivos do projeto anterior:
* **Imagens traduzidas prontas:**  
  `C:\Users\ja329\Downloads\[Alice no Takarabako (Mizuryu Kei)] Oideyo! Mizuryu Kei Land - the 10th Day [PT-BR]`
* **Leitor web interativo:**  
  Abra o arquivo `leitor.html` dentro da pasta acima para ler no navegador.
* **Roteiro traduzido completo:**  
  `C:\Users\ja329\Downloads\TRADUCAO_COMPLETA_PTBR.md`

---

## ⚡ Como traduzir novos mangás no futuro:

### Método 1: Pedindo diretamente aqui no chat (Mais fácil)
Basta colocar o novo mangá em uma pasta e me dizer:
> *"Traduza o mangá da pasta `C:\caminho\para\novo_manga` usando o pipeline"*

Eu já possuo a **skill permanente registrada** (`manga-translator-scanlation`) e executarei todas as etapas:
1. Extração do OCR e balões com Mokuro.
2. Tradução natural de todos os diálogos.
3. Limpeza dos balões e inserção do texto em português nas imagens.
4. Criação do leitor web para você abrir e ler imediatamente.

---

### Método 2: Executando o script via terminal (Manual)

#### 1. Fazer o OCR com Mokuro:
```powershell
python -m mokuro "C:\caminho\para\pasta_manga" --disable_confirmation
```

#### 2. Extrair dados das caixas de texto:
```powershell
python "C:\Users\ja329\tools\manga-translator\manga_pipeline.py" ocr "C:\caminho\para\pasta_manga"
```

#### 3. Diagramar com traduções:
```powershell
python "C:\Users\ja329\tools\manga-translator\manga_pipeline.py" typeset "C:\caminho\original" "C:\caminho\extracted.json" "C:\caminho\traducoes.json" "C:\caminho\pasta_destino"
```

#### 4. Gerar leitor web em qualquer pasta de imagens:
```powershell
python "C:\Users\ja329\tools\manga-translator\manga_pipeline.py" reader "C:\caminho\pasta_imagens"
```
