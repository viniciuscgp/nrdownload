import os
import io
import fnmatch
import re
import sys
import shutil
import subprocess
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from threading import Thread
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
CHUNK_SIZE = 64 * 1024 * 1024  # 64 MB: bom throughput p/ arquivos grandes

# ---------- Helpers ----------

def rel_join(path_atual: str, nome: str) -> str:
    """Garante path relativo (sem / ou \ no início)."""
    p = os.path.join(path_atual, nome)
    return p.lstrip("/\\")

def fmt_size(num_bytes):
    if not num_bytes:
        return "tamanho desconhecido"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.2f} {units[i]}"

def folder_pattern_from_file_pattern(padrao_arquivo: str) -> str:
    """
    Deriva padrão de PASTA a partir do padrão de arquivo da raiz:
      'a*.zip' -> 'a*'
      '*.mp4'  -> '*'
      'data_*.*' -> 'data_*'
    """
    base = (padrao_arquivo or "").strip()
    if '.' in base:
        return base.split('.', 1)[0] or '*'
    return base or '*'

class PowerInhibitor:
    """Mantém o computador acordado durante o download."""
    def __init__(self, enable: bool, log_fn):
        self.enable = enable
        self.log = log_fn
        self.proc = None

    def __enter__(self):
        if not self.enable:
            return self
        try:
            if sys.platform.startswith("win"):
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                ES_DISPLAY_REQUIRED = 0x00000002
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
                )
                self.log("🛡️ Mantendo Windows acordado (sistema/tela).")
            elif sys.platform == "darwin":
                self.proc = subprocess.Popen(["caffeinate", "-dims"])
                self.log("🛡️ caffeinate ativo (macOS).")
            else:
                if shutil.which("systemd-inhibit"):
                    self.proc = subprocess.Popen([
                        "systemd-inhibit", "--what=sleep:idle",
                        "--why=NRDownloader em execução",
                        "bash", "-c", "while :; do sleep 3600; done"
                    ])
                    self.log("🛡️ systemd-inhibit ativo (Linux).")
                else:
                    self.log("⚠️ systemd-inhibit não encontrado; ajuste a energia manualmente.")
        except Exception as e:
            self.log(f"⚠️ Não foi possível inibir suspensão: {e}")
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.enable:
            return
        try:
            if sys.platform.startswith("win"):
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            if self.proc:
                self.proc.terminate()
        except Exception as e:
            self.log(f"⚠️ Erro ao restaurar energia: {e}")

# ---------- Auth / Drive ----------

def get_drive_service(log_fn):
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log_fn("Atualizando token...")
            creds.refresh(Request())
        else:
            log_fn("Abrindo navegador para autenticação...")
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    log_fn("Autenticado com sucesso.")
    return build('drive', 'v3', credentials=creds)

def extrair_id_da_pasta(texto):
    texto = texto.strip()
    if re.fullmatch(r'[a-zA-Z0-9_-]{20,}', texto):
        return texto
    match = re.search(r'/folders/([a-zA-Z0-9_-]+)', texto)
    if match:
        return match.group(1)
    raise ValueError("ID da pasta inválido (cole o ID ou URL da pasta do Drive).")

# ---------- Listagem (filtro SOMENTE na RAIZ) ----------

def listar_raiz_e_recurse(service, raiz_id, padrao_arquivos, log_fn):
    """
    Regras:
      - Na RAIZ:
         * arquivos: aplica padrao_arquivos (ex.: a*.zip) -> coleta
         * pastas: aplica padrao_pastas (derivado) -> se combinar, entra
      - Dentro da(s) pasta(s) aceitas na raiz:
         * NÃO há filtro: coleta tudo (pastas e arquivos).
    Retorna:
      pastas_rel: [str, ...] (TODAS as pastas a criar, inclusive as raiz aceitas)
      arquivos_rel: [(id, relpath, size), ...]
    """
    padrao_pastas_raiz = folder_pattern_from_file_pattern(padrao_arquivos)
    pastas_rel = []
    arquivos_rel = []

    # 1) listar apenas filhos imediatos da RAIZ
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{raiz_id}' in parents and trashed = false",
            spaces='drive',
            pageSize=1000,
            fields='nextPageToken, files(id, name, mimeType, size)',
            pageToken=page_token
        ).execute()

        for item in resp.get('files', []):
            nome = item['name']
            fid = item['id']
            mime = item['mimeType']

            if mime == 'application/vnd.google-apps.folder':
                # só entra se a PASTA DA RAIZ combinar com o padrão de pastas
                if fnmatch.fnmatch(nome, padrao_pastas_raiz):
                    root_folder_rel = rel_join("", nome)  # vira "NomeDaPasta"
                    pastas_rel.append(root_folder_rel)
                    log_fn(f"📁 (raiz) selecionada: {root_folder_rel}/")
                    # entra e coleta TUDO dentro dessa pasta (sem filtro)
                    listar_tudo_dentro(service, fid, root_folder_rel, pastas_rel, arquivos_rel, log_fn)
                else:
                    log_fn(f"🚫 (raiz) ignorando pasta: {nome}")
            else:
                # arquivos no nível RAIZ: aplicar padrao_arquivos
                if fnmatch.fnmatch(nome, padrao_arquivos):
                    size_val = int(item.get('size', 0)) if item.get('size') is not None else None
                    rel = rel_join("", nome)  # "arquivo_na_raiz.ext"
                    log_fn(f"✔️ (raiz) {rel} ({fmt_size(size_val)})")
                    arquivos_rel.append((fid, rel, size_val))

        page_token = resp.get('nextPageToken')
        if not page_token:
            break

    return pastas_rel, arquivos_rel

def listar_tudo_dentro(service, pasta_id, base_relpath, pastas_rel, arquivos_rel, log_fn):
    """Coleta TUDO (sem filtro) dentro de 'pasta_id', preenchendo caminhos relativos sob 'base_relpath'."""
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{pasta_id}' in parents and trashed = false",
            spaces='drive',
            pageSize=1000,
            fields='nextPageToken, files(id, name, mimeType, size)',
            pageToken=page_token
        ).execute()

        for item in resp.get('files', []):
            nome = item['name']
            fid = item['id']
            mime = item['mimeType']

            if mime == 'application/vnd.google-apps.folder':
                new_base = rel_join(base_relpath, nome)  # mantém hierarquia: PastaRaiz/Sub/...
                pastas_rel.append(new_base)
                log_fn(f"📁 {new_base}/")
                listar_tudo_dentro(service, fid, new_base, pastas_rel, arquivos_rel, log_fn)
            else:
                size_val = int(item.get('size', 0)) if item.get('size') is not None else None
                rel = rel_join(base_relpath, nome)
                log_fn(f"✔️ {rel} ({fmt_size(size_val)})")
                arquivos_rel.append((fid, rel, size_val))

        page_token = resp.get('nextPageToken')
        if not page_token:
            break

# ---------- Download ----------

def download_with_retries(request, local_path, size_val, log_fn, root, chunk_size, max_retries=5):
    with io.FileIO(local_path, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request, chunksize=chunk_size)
        done = False
        last_bucket = -1
        retries = 0
        while not done:
            try:
                status, done = downloader.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    bucket = pct // 5  # log a cada 5%
                    if bucket != last_bucket:
                        if size_val:
                            cur = int(size_val * (pct/100.0))
                            log_fn(f"   ... {pct}% ({fmt_size(cur)}/{fmt_size(size_val)})")
                        else:
                            log_fn(f"   ... {pct}%")
                        last_bucket = bucket
                        root.update_idletasks()
            except (HttpError, OSError) as e:
                if retries < max_retries:
                    wait = 2 ** retries
                    log_fn(f"   ⚠️ Falha de rede, tentando em {wait}s... ({retries+1}/{max_retries}) [{e}]")
                    time.sleep(wait)
                    retries += 1
                    continue
                raise

def baixar_arquivos(pasta_input, padrao_arquivos, destino, skip_existing, keep_awake,
                    progress_var, progress_bar, log_fn, root):
    try:
        with PowerInhibitor(keep_awake, log_fn):
            raiz_id = extrair_id_da_pasta(pasta_input)
            service = get_drive_service(log_fn)

            log_fn("🔍 Listando raiz (filtro aplicado) e subpastas (sem filtro)...")
            pastas_rel, arquivos_rel = listar_raiz_e_recurse(service, raiz_id, padrao_arquivos, log_fn)

            # 1) cria TODAS as pastas coletadas (mantendo hierarquia correta)
            pastas_unicas = sorted(set(pastas_rel), key=lambda p: (p.count(os.sep), p))
            for p in pastas_unicas:
                full_dir = os.path.join(destino, p.lstrip("/\\"))
                os.makedirs(full_dir, exist_ok=True)

            # 2) baixa arquivos conforme opção
            total = len(arquivos_rel)
            if total == 0:
                log_fn("⚠️ Nenhum arquivo para baixar com esse filtro na raiz.")
                messagebox.showinfo("Aviso", "Nenhum arquivo para baixar com esse filtro na raiz.")
                return

            info_opcao = "pulando existentes" if skip_existing else "sobrescrevendo existentes"
            log_fn(f"🎯 Total: {total} arquivos ({info_opcao})")
            progress_var.set(0)
            progress_bar['maximum'] = total

            for i, (file_id, relpath, size_val) in enumerate(arquivos_rel, start=1):
                relpath = relpath.lstrip("/\\")
                local_path = os.path.join(destino, relpath)

                # pular se existir e (opcionalmente) mesmo tamanho
                if os.path.exists(local_path) and skip_existing:
                    if size_val and os.path.getsize(local_path) == size_val:
                        log_fn(f"⏭️ Pulando (já existe e mesmo tamanho): {relpath}")
                        progress_var.set(i); root.update_idletasks()
                        continue
                    else:
                        log_fn(f"🔁 Existe com tamanho diferente — será rebaixado: {relpath}")

                os.makedirs(os.path.dirname(local_path), exist_ok=True)

                # espaço livre (se souber tamanho)
                dest_dir = os.path.dirname(local_path) or destino
                free = shutil.disk_usage(dest_dir).free
                if size_val and free < size_val + 200*1024*1024:
                    log_fn(f"🛑 Sem espaço p/ {relpath} (precisa ~{fmt_size(size_val)}, livre {fmt_size(free)})")
                    progress_var.set(i); root.update_idletasks()
                    continue

                log_fn(f"⬇️ Baixando: {relpath} ({fmt_size(size_val)})")
                request = service.files().get_media(fileId=file_id)
                download_with_retries(request, local_path, size_val, log_fn, root, CHUNK_SIZE)

                progress_var.set(i)
                root.update_idletasks()

            log_fn("✅ Processamento finalizado!")
            messagebox.showinfo("Concluído", f"{total} arquivos processados ({info_opcao}).")
    except Exception as e:
        log_fn(f"❌ Erro: {str(e)}")
        messagebox.showerror("Erro", str(e))

# ---------- GUI ----------

def criar_interface():
    root = tk.Tk()
    root.title("Google Drive Downloader (filtro na RAIZ)")
    root.geometry("820x680")

    tk.Label(root, text="ID/URL da Pasta no Drive:").pack()
    pasta_entry = tk.Entry(root, width=110)
    pasta_entry.pack()

    tk.Label(root, text="Filtro (aplicado SOMENTE na raiz, ex: a*.zip):").pack()
    filtro_entry = tk.Entry(root, width=110)
    filtro_entry.insert(0, "a*.zip")
    filtro_entry.pack()

    # pular existentes (padrão)
    skip_existing_var = tk.BooleanVar(value=True)
    tk.Checkbutton(root, text="Não baixar arquivo já existente (padrão)", variable=skip_existing_var).pack(pady=4)

    # manter PC acordado (padrão)
    keep_awake_var = tk.BooleanVar(value=True)
    tk.Checkbutton(root, text="Manter PC acordado durante o download (padrão)", variable=keep_awake_var).pack(pady=4)

    tk.Label(root, text="Destino local:").pack()
    destino_entry = tk.Entry(root, width=110)
    destino_entry.pack()

    def escolher_destino():
        pasta = filedialog.askdirectory()
        if pasta:
            destino_entry.delete(0, tk.END)
            destino_entry.insert(0, pasta)

    tk.Button(root, text="Escolher Pasta", command=escolher_destino).pack(pady=6)

    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(root, variable=progress_var, maximum=100)
    progress_bar.pack(fill='x', padx=20, pady=10)

    log_box = tk.Text(root, height=22, wrap="word")
    log_box.pack(fill='both', padx=10, pady=5, expand=True)

    scrollbar = ttk.Scrollbar(log_box)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    log_box.config(yscrollcommand=scrollbar.set)
    scrollbar.config(command=log_box.yview)

    def log(msg):
        log_box.insert(tk.END, msg + "\n")
        log_box.see(tk.END)

    def iniciar_thread_download():
        pasta = pasta_entry.get().strip()
        padrao_arquivos = filtro_entry.get().strip()
        destino = destino_entry.get().strip()
        skip_existing = bool(skip_existing_var.get())
        keep_awake = bool(keep_awake_var.get())

        log_box.delete(1.0, tk.END)
        if not pasta or not padrao_arquivos or not destino:
            messagebox.showwarning("Aviso", "Preencha todos os campos.")
            return

        Thread(
            target=baixar_arquivos,
            args=(pasta, padrao_arquivos, destino, skip_existing, keep_awake,
                  progress_var, progress_bar, log, root),
            daemon=True
        ).start()

    tk.Button(root, text="Baixar", command=iniciar_thread_download).pack(pady=10)
    root.mainloop()

if __name__ == "__main__":
    criar_interface()
