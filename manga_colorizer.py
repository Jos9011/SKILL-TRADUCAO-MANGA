"""
manga_colorizer.py - Módulo de Colorização Neural de Mangás (Manga Studio)
Colorização de mangás P&B com modelo ONNX leve U-Net e preservação cirúrgica de nanquim.
Suporta CPU e GPU (CUDA) com gestão segura de memória VRAM. Foco laser (< 300 linhas).
"""

import os
import sys
import re
import time
import threading
import urllib.request
import numpy as np
import cv2
from PIL import Image

MODEL_SUBDIR = os.path.join("models", "colorizer")
MODEL_FILENAME = "manga-colorize-fp16.onnx"
HF_MODEL_URL = "https://huggingface.co/Faridzar/manga-colorization-v2-onnx/resolve/main/manga-colorize-fp16.onnx"

_CACHED_SESSION = None
_SESSION_LOCK = threading.Lock()


def get_default_model_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), MODEL_SUBDIR, MODEL_FILENAME)


def download_model_if_needed(target_path=None, verbose=True):
    dest = target_path or get_default_model_path()
    if os.path.exists(dest) and os.path.getsize(dest) > 10 * 1024 * 1024:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if verbose:
        print("[*] Baixando modelo neural de colorização (~58MB)...")
    urllib.request.urlretrieve(HF_MODEL_URL, dest)
    if verbose:
        print("[+] Modelo neural baixado com sucesso!")
    return dest


def get_session(model_path=None, use_gpu=True):
    """Inicializa ou retorna a sessão ONNX Runtime em cache com gestão segura de VRAM."""
    global _CACHED_SESSION
    with _SESSION_LOCK:
        if _CACHED_SESSION is not None:
            return _CACHED_SESSION
        import onnxruntime as ort

        m_path = download_model_if_needed(model_path)
        available = ort.get_available_providers()
        providers = []
        if use_gpu and "CUDAExecutionProvider" in available:
            cuda_opts = {
                "arena_extend_strategy": "kSameAsRequested",
                "gpu_mem_limit": 6 * 1024 * 1024 * 1024,
                "cudnn_conv_use_max_workspace": "0",
                "do_copy_in_default_stream": True,
            }
            providers.append(("CUDAExecutionProvider", cuda_opts))
        providers.append("CPUExecutionProvider")

        opts = ort.SessionOptions()
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.enable_cpu_mem_arena = False
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        _CACHED_SESSION = ort.InferenceSession(m_path, sess_options=opts, providers=providers)
        print(f"[+] Motor de Colorização ONNX ativo: [{_CACHED_SESSION.get_providers()[0]}]")
        return _CACHED_SESSION


def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


def colorize_cv2(img_bgr, session=None, max_size=None, preserve_lineart=True, reference=None):
    """Coloriza uma imagem OpenCV BGR com preservação de nanquim e gestão de memória."""
    if session is None:
        session = get_session()

    if len(img_bgr.shape) == 2:
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    elif img_bgr.shape[2] == 4:
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2BGR)

    orig_h, orig_w = img_bgr.shape[:2]
    orig_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    work_img, scale = img_bgr, 1.0
    if max_size and max(orig_h, orig_w) > max_size:
        scale = max_size / float(max(orig_h, orig_w))
        nw, nh = max(32, int(round(orig_w * scale))), max(32, int(round(orig_h * scale)))
        work_img = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_AREA)

    h, w = work_img.shape[:2]
    pad_h = (32 - (h % 32)) % 32
    pad_w = (32 - (w % 32)) % 32
    gray_norm = cv2.cvtColor(work_img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    if pad_h > 0 or pad_w > 0:
        gray_norm = cv2.copyMakeBorder(gray_norm, 0, pad_h, 0, pad_w, cv2.BORDER_REFLECT)

    th, tw = gray_norm.shape
    inp = np.zeros((1, 5, th, tw), dtype=np.float32)
    inp[0, 0, :, :] = gray_norm

    outputs = session.run(["rgb"], {"input": inp})
    out_rgb = outputs[0][0, :, :h, :w]
    del inp, outputs
    out_rgb = np.transpose(out_rgb, (1, 2, 0))
    out_bgr = np.clip(out_rgb * 255.0, 0, 255).astype(np.uint8)
    del out_rgb
    out_bgr = cv2.cvtColor(out_bgr, cv2.COLOR_RGB2BGR)

    if scale != 1.0:
        out_bgr = cv2.resize(out_bgr, (orig_w, orig_h), interpolation=cv2.INTER_CUBIC)

    if reference is not None:
        try:
            import color_reference
            prof = reference if isinstance(reference, dict) else color_reference.extract_reference_profile(reference)
            out_bgr = color_reference.apply_reference_transfer(out_bgr, prof)
        except Exception:
            pass

    if preserve_lineart:
        ycrcb = cv2.cvtColor(out_bgr, cv2.COLOR_BGR2YCrCb)
        ycrcb[:, :, 0] = orig_gray
        out_bgr = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)

    return out_bgr


def colorize_image(image_input, output_path=None, session=None, max_size=None, preserve_lineart=True, reference=None):
    """Coloriza imagem a partir de arquivo, PIL.Image ou numpy array."""
    is_path = isinstance(image_input, str)
    if is_path:
        with open(image_input, "rb") as f:
            buf = np.asarray(bytearray(f.read()), dtype=np.uint8)
            img_bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise ValueError(f"Não foi possível abrir a imagem: {image_input}")
    elif isinstance(image_input, Image.Image):
        img_bgr = cv2.cvtColor(np.array(image_input.convert("RGB")), cv2.COLOR_RGB2BGR)
    elif isinstance(image_input, np.ndarray):
        img_bgr = image_input.copy()
    else:
        raise TypeError("Entrada deve ser caminho de arquivo, PIL.Image ou numpy.ndarray")

    colored_bgr = colorize_cv2(
        img_bgr, session=session, max_size=max_size, preserve_lineart=preserve_lineart, reference=reference
    )

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        ok, enc = cv2.imencode(".jpg", colored_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if ok:
            with open(output_path, "wb") as f:
                f.write(enc.tobytes())
        return output_path

    if isinstance(image_input, Image.Image) or is_path:
        return Image.fromarray(cv2.cvtColor(colored_bgr, cv2.COLOR_BGR2RGB))
    return colored_bgr


def colorize_manga_folder(input_dir, output_dir=None, progress_cb=None, max_size=None, preserve_lineart=True, reference=None):
    """Processa em lote todas as imagens de um diretório de mangá com limpeza periódica de VRAM."""
    import gc

    input_dir = os.path.abspath(input_dir.strip("\"'"))
    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"Diretório não encontrado: {input_dir}")

    exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    files = [f for f in os.listdir(input_dir) if f.lower().endswith(exts)]
    files.sort(key=natural_sort_key)
    if not files:
        raise ValueError(f"Nenhuma imagem encontrada em: {input_dir}")

    if not output_dir:
        clean_name = os.path.basename(input_dir).replace(" [COLORIDO]", "").replace("[COLORIDO]", "").strip()
        output_dir = os.path.join(os.path.dirname(input_dir), f"{clean_name} [COLORIDO]")

    os.makedirs(output_dir, exist_ok=True)
    total = len(files)
    t_start = time.time()
    session = get_session()

    ref_profile = None
    if reference is not None:
        try:
            import color_reference
            ref_profile = reference if isinstance(reference, dict) else color_reference.extract_reference_profile(reference)
            if ref_profile:
                print(f"[+] Referência cromática ativa: {ref_profile.get('source')}")
        except Exception:
            pass

    print(f"[*] Iniciando colorização de {total} páginas:\n    Origem: {input_dir}\n    Destino: {output_dir}")

    for idx, fname in enumerate(files):
        in_path = os.path.join(input_dir, fname)
        out_path = os.path.join(output_dir, f"{os.path.splitext(fname)[0]}.jpg")
        msg = f"Colorindo página {idx + 1}/{total} ({fname})..."
        if progress_cb:
            progress_cb("colorize", idx + 1, total, msg)
        else:
            print(f"  [{idx + 1}/{total}] {msg}")

        try:
            colorize_image(
                in_path,
                output_path=out_path,
                session=session,
                max_size=max_size,
                preserve_lineart=preserve_lineart,
                reference=ref_profile,
            )
        except Exception as ex:
            print(f"[!] Erro ao colorir {fname}: {ex}")
        finally:
            gc.collect()
            if "torch" in sys.modules:
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass

    elapsed = time.time() - t_start
    final_msg = f"Colorização concluída com sucesso em {elapsed:.1f}s!"
    print(f"[+] {final_msg}")

    cbz_name = f"{os.path.basename(output_dir)}.cbz"
    cbz_path = os.path.join(os.path.dirname(output_dir), cbz_name)
    try:
        import auto_translate
        auto_translate.create_html_reader(output_dir, os.path.basename(output_dir))
        auto_translate.create_cbz_archive(output_dir, cbz_path)
    except Exception:
        pass

    result_data = {
        "success": True,
        "output_dir": output_dir,
        "cbz_path": cbz_path if os.path.exists(cbz_path) else None,
        "total_pages": total,
        "elapsed_seconds": round(elapsed, 2),
    }
    if progress_cb:
        progress_cb("done", total, total, final_msg, result=result_data)
    return result_data


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Colorizador Neural de Mangás (Manga Studio)")
    parser.add_argument("path", help="Pasta do mangá ou imagem individual para colorir")
    parser.add_argument("-o", "--output", help="Pasta ou arquivo de destino", default=None)
    parser.add_argument("-r", "--reference", help="Pasta, imagem ou arquivo de referência de cores", default=None)
    parser.add_argument("--max-size", type=int, default=None, help="Tamanho máximo para modo rápido")
    parser.add_argument("--no-lineart", action="store_true", help="Desativa preservação do nanquim original")

    args = parser.parse_args()
    target_path = os.path.abspath(args.path)

    if os.path.isdir(target_path):
        colorize_manga_folder(
            target_path,
            output_dir=args.output,
            max_size=args.max_size,
            preserve_lineart=not args.no_lineart,
            reference=args.reference,
        )
    elif os.path.isfile(target_path):
        out = args.output or os.path.splitext(target_path)[0] + "_colorido.jpg"
        colorize_image(
            target_path,
            output_path=out,
            max_size=args.max_size,
            preserve_lineart=not args.no_lineart,
            reference=args.reference,
        )
        print(f"[+] Imagem salva em: {out}")
    else:
        print(f"[!] Caminho não encontrado: {target_path}")
        sys.exit(1)
