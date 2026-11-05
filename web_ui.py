import os
import sys
import glob
import shutil
import zipfile
import tempfile

try:
    import gradio as gr
except ImportError:
    gr = None

from auto_translate import process_manga, load_config, BASE_OUTPUT_DIR

def translate_manga_ui(files, ocr_choice, adult_choice, provider_choice, openrouter_key):
    if not files:
        return None, None, "### ⚠️ Nenhum arquivo enviado\nEnvie fotos ou um arquivo ZIP/CBZ."
        
    temp_work_dir = tempfile.mkdtemp(prefix="manga_web_")
    input_dir = os.path.join(temp_work_dir, "Capitulo")
    os.makedirs(input_dir, exist_ok=True)
    
    # 1. Trata os arquivos recebidos
    file_list = files if isinstance(files, list) else [files]
    
    chapter_name = "Capitulo"
    for f in file_list:
        file_path = f if isinstance(f, str) else getattr(f, 'name', str(f))
        fname = os.path.basename(file_path)
        ext = os.path.splitext(fname)[1].lower()
        
        if ext in ('.zip', '.cbz'):
            chapter_name = os.path.splitext(fname)[0]
            with zipfile.ZipFile(file_path, 'r') as z:
                z.extractall(input_dir)
        elif ext in ('.jpg', '.jpeg', '.png', '.webp'):
            shutil.copy2(file_path, os.path.join(input_dir, fname))
            
    # Procura se há subpastas descompactadas dentro do zip
    extracted_imgs = []
    for root, _, fs in os.walk(input_dir):
        for f in fs:
            if os.path.splitext(f)[1].lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                extracted_imgs.append(os.path.join(root, f))
                
    if not extracted_imgs:
        return None, None, "### ❌ Nenhuma imagem válida encontrada\nEnvie imagens em formato JPG, PNG ou WEBP."
        
    # Se as imagens estiverem aninhadas em subpastas, move tudo para a raiz
    for img_p in extracted_imgs:
        dest_p = os.path.join(input_dir, os.path.basename(img_p))
        if img_p != dest_p:
            shutil.move(img_p, dest_p)
            
    # 2. Configurações de execução
    cfg = load_config()
    if provider_choice == "OpenRouter":
        cfg["provider"] = "openrouter"
        if openrouter_key and openrouter_key.strip():
            cfg["openrouter_api_key"] = openrouter_key.strip()
    elif provider_choice == "Ollama (Colab GPU)":
        cfg["provider"] = "ollama"
        cfg["ollama_host"] = "http://localhost:11434"
        cfg["ollama_model"] = "qwen2.5:latest"
        
    ocr_mode_map = {
        "Automático": "auto",
        "Japonês (Mangá)": "japanese",
        "Coreano (Manhwa)": "korean"
    }
    ocr_mode = ocr_mode_map.get(ocr_choice, "auto")
    is_adult = (adult_choice == "Sim (+18 Adulto / Sem Censura)")
    
    # 3. Executa o pipeline de tradução
    try:
        res = process_manga(
            manga_dir=input_dir,
            target_lang="pt-BR",
            ocr_mode=ocr_mode,
            force_ocr=False,
            is_adult=is_adult,
            config=cfg
        )
    except Exception as e:
        return None, None, f"### ❌ Erro durante o processamento:\n`{str(e)}`"
        
    output_dir = None
    cbz_path = None
    if isinstance(res, dict):
        output_dir = res.get("output_dir")
        cbz_path = res.get("cbz_path")
        
    if not output_dir or not os.path.exists(output_dir):
        cand_dir = os.path.join(BASE_OUTPUT_DIR, f"{os.path.basename(input_dir)} [PT-BR]")
        if os.path.exists(cand_dir):
            output_dir = cand_dir
            
    if not output_dir or not os.path.exists(output_dir):
        return None, None, "### ❌ Falha ao localizar a pasta com os resultados traduzidos."
        
    # Coleta todas as imagens traduzidas geradas para a galeria
    rendered_images = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        rendered_images.extend(glob.glob(os.path.join(output_dir, ext)))
    rendered_images.sort()
    
    # Se cbz_path não foi retornado diretamente, localiza o .cbz
    if not cbz_path or not os.path.exists(cbz_path):
        cand_cbz = os.path.join(BASE_OUTPUT_DIR, f"{os.path.basename(input_dir)} [PT-BR].cbz")
        if os.path.exists(cand_cbz):
            cbz_path = cand_cbz
            
    status_msg = f"### ✅ Tradução concluída com sucesso!\nForam traduzidas **{len(rendered_images)}** páginas."
    return rendered_images, cbz_path, status_msg

def create_ui():
    custom_css = """
    .gradio-container { max-width: 900px !important; margin: auto !important; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    #translate_btn { background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%) !important; color: white !important; font-weight: bold !important; font-size: 1.15rem !important; padding: 12px !important; border-radius: 8px !important; }
    """
    with gr.Blocks(title="Tradutor de Mangás Mobile", css=custom_css, theme=gr.themes.Soft()) as demo:
        gr.Markdown("""
        # 📱 Tradutor de Mangás & Manhwas (PT-BR)
        ### Tradução sem censura com IA, inpainting automático e tipografia profissional de scanlation.
        """)
        
        with gr.Row():
            with gr.Column(scale=1):
                files_input = gr.File(
                    label="📂 Envie as Imagens ou Arquivo ZIP / CBZ",
                    file_count="multiple",
                    type="filepath"
                )
                
                with gr.Row():
                    ocr_choice = gr.Dropdown(
                        label="Idioma da Obra / OCR",
                        choices=["Automático", "Coreano (Manhwa)", "Japonês (Mangá)"],
                        value="Automático"
                    )
                    adult_choice = gr.Dropdown(
                        label="Modo Adulto (+18)",
                        choices=["Sim (+18 Adulto / Sem Censura)", "Não (Geral)"],
                        value="Sim (+18 Adulto / Sem Censura)"
                    )
                    
                with gr.Accordion("⚙️ Configurações de IA", open=False):
                    provider_choice = gr.Radio(
                        label="Motor de IA",
                        choices=["Ollama (Colab GPU)", "OpenRouter"],
                        value="Ollama (Colab GPU)"
                    )
                    openrouter_key = gr.Textbox(
                        label="Chave API OpenRouter (se usar OpenRouter)",
                        placeholder="sk-or-v1-...",
                        type="password"
                    )
                    
                btn_translate = gr.Button("🚀 Iniciar Tradução", elem_id="translate_btn", variant="primary")
                
            with gr.Column(scale=1):
                status_box = gr.Markdown("⏳ **Status:** Aguardando envio...")
                cbz_output = gr.File(label="📥 Baixar Capítulo Traduzido (.CBZ)")
                
        with gr.Row():
            gallery_output = gr.Gallery(
                label="📖 Leitor das Páginas Traduzidas",
                columns=1,
                rows=1,
                height=720,
                object_fit="contain",
                preview=True
            )
            
        btn_translate.click(
            fn=translate_manga_ui,
            inputs=[files_input, ocr_choice, adult_choice, provider_choice, openrouter_key],
            outputs=[gallery_output, cbz_output, status_box]
        )
        
    return demo

if __name__ == "__main__":
    if gr is None:
        print("[!] Gradio não está instalado. Execute: pip install gradio")
        sys.exit(1)
    demo = create_ui()
    demo.queue().launch(share=True)
