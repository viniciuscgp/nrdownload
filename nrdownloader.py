import os
import io
import fnmatch
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from threading import Thread
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

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
    raise ValueError("ID da pasta inválido.")

def listar_arquivos_recursivo(service, pasta_id, filtro, path_atual, todos_arquivos, log_fn):
    query = f"'{pasta_id}' in parents and trashed = false"
    page_token = None
    while True:
        response = service.files().list(
            q=query,
            spaces='drive',
            fields='nextPageToken, files(id, name, mimeType)',
            pageToken=page_token
        ).execute()

        for item in response.get('files', []):
            nome = item['name']
            file_id = item['id']
            mime = item['mimeType']
            full_path = os.path.join(path_atual, nome)

            if mime == 'application/vnd.google-apps.folder':
                log_fn(f"📁 {full_path}/")
                listar_arquivos_recursivo(service, file_id, filtro, full_path, todos_arquivos, log_fn)
            else:
                if fnmatch.fnmatch(nome, filtro):
                    log_fn(f"✔️ {full_path}")
                    todos_arquivos.append((file_id, full_path))

        page_token = response.get('nextPageToken', None)
        if page_token is None:
            break

def baixar_arquivos(pasta_input, filtro, destino, progress_var, progress_bar, log_fn, root):
    try:
        pasta_id = extrair_id_da_pasta(pasta_input)
        service = get_drive_service(log_fn)

        log_fn("🔍 Buscando arquivos...")
        arquivos = []
        listar_arquivos_recursivo(service, pasta_id, filtro, "", arquivos, log_fn)

        total = len(arquivos)
        if total == 0:
            log_fn("⚠️ Nenhum arquivo encontrado.")
            messagebox.showinfo("Aviso", "Nenhum arquivo encontrado com o filtro fornecido.")
            return

        log_fn(f"🎯 Total: {total} arquivos")
        progress_var.set(0)
        progress_bar['maximum'] = total

        for i, (file_id, relative_path) in enumerate(arquivos, start=1):
            local_path = os.path.join(destino, relative_path)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            log_fn(f"⬇️ Baixando: {relative_path}")
            request = service.files().get_media(fileId=file_id)
            with io.FileIO(local_path, 'wb') as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()

            progress_var.set(i)
            root.update_idletasks()

        log_fn("✅ Download completo!")
        messagebox.showinfo("Concluído", f"{total} arquivos baixados com sucesso.")
    except Exception as e:
        log_fn(f"❌ Erro: {str(e)}")
        messagebox.showerror("Erro", str(e))

def criar_interface():
    root = tk.Tk()
    root.title("Google Drive Downloader")
    root.geometry("620x520")

    tk.Label(root, text="ID da Pasta no Drive:").pack()
    pasta_entry = tk.Entry(root, width=80)
    pasta_entry.pack()

    tk.Label(root, text="Filtro (ex: a*.zip):").pack()
    filtro_entry = tk.Entry(root, width=80)
    filtro_entry.insert(0, "a*.zip")
    filtro_entry.pack()

    tk.Label(root, text="Destino local:").pack()
    destino_entry = tk.Entry(root, width=80)
    destino_entry.pack()

    def escolher_destino():
        pasta = filedialog.askdirectory()
        destino_entry.delete(0, tk.END)
        destino_entry.insert(0, pasta)

    tk.Button(root, text="Escolher Pasta", command=escolher_destino).pack(pady=5)

    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(root, variable=progress_var, maximum=100)
    progress_bar.pack(fill='x', padx=20, pady=10)

    log_box = tk.Text(root, height=12, wrap="word")
    log_box.pack(fill='both', padx=10, pady=5, expand=True)

    scrollbar = ttk.Scrollbar(log_box)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    log_box.config(yscrollcommand=scrollbar.set)
    scrollbar.config(command=log_box.yview)

    def log(msg):
        log_box.insert(tk.END, msg + "\n")
        log_box.see(tk.END)

    def iniciar_thread_download():
        pasta = pasta_entry.get()
        filtro = filtro_entry.get()
        destino = destino_entry.get()
        log_box.delete(1.0, tk.END)
        if not pasta or not filtro or not destino:
            messagebox.showwarning("Aviso", "Preencha todos os campos.")
            return
        Thread(target=baixar_arquivos, args=(pasta, filtro, destino, progress_var, progress_bar, log, root), daemon=True).start()

    tk.Button(root, text="Baixar Arquivos", command=iniciar_thread_download).pack(pady=10)
    root.mainloop()

criar_interface()
