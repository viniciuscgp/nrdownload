# NRDownloader

Aplicativo desktop (Tkinter + Python) para **baixar arquivos do Google Drive direto**, sem “compactar” antes.

> **Por quê existe?** Pelo navegador, o Drive “compactava” pastas grandes e o download falhava por tamanho.  
> O **NRDownloader** baixa os arquivos **direto** (stream) via API do Google Drive — rápido, confiável e sem zip automático.

---

## ✨ Recursos

- 🔍 **Filtro por padrão** (ex.: `a*.zip`, `*.jpg`, `data_*.*`)
- 🔁 **Recursivo**, preservando a **estrutura de pastas**
- 📂 **Modo opcional**: _Somente pastas da raiz (dentro baixa tudo)_
  - Seleciona pastas na **raiz** que combinam com o **prefixo derivado** do filtro (ex.: `a*.zip` → `a*`)
  - Dentro dessas pastas, baixa **todos os arquivos** (sem filtrar extensão)
- 📊 **Barra de progresso** e **log ao vivo**
- 🔐 Escopo **somente leitura** do Drive (`drive.readonly`)
- 🧵 Baixa em **thread separada** (GUI não trava)

> Obs.: Arquivos **nativos do Google** (Docs/Sheets/Slides/Forms etc.) **não são baixados** (não há export neste app).

---

## 🧩 Pré-requisitos

- **Python 3.8+**
- Sistema:
  - **Linux (Ubuntu/Debian)**:
    ```bash
    sudo apt update
    sudo apt install -y python3-venv python3-tk
    ```
  - **Windows**: Python 3 + Tkinter já incluso no instalador oficial.
  - **macOS**: Python 3 via Homebrew (Tkinter costuma vir junto), ou instale `python-tk` apropriado.

---

## 🚀 Instalação rápida

Crie (opcional) um ambiente virtual e instale as libs:

```bash
# 1) (opcional) ambiente virtual
python3 -m venv venv
# Linux/macOS
source venv/bin/activate
# Windows (PowerShell)
# .\venv\Scripts\Activate.ps1

# 2) dependências
pip install google-api-python-client google-auth google-auth-oauthlib


## 🔑 Habilitando a API do Google Drive (passo a passo)

> Você fará isso **uma vez** no Google Cloud e depois usará o `credentials.json` no app.

1. **Acesse o Google Cloud Console**  
   https://console.cloud.google.com/ (entre com sua conta Google).

2. **Crie ou selecione um projeto**  
   No topo, clique no seletor de projetos → *Novo projeto* (ou escolha um existente).

3. **(Somente na 1ª vez) Configure a Tela de Consentimento OAuth**  
   - Menu esquerdo → **APIs e Serviços** → **Tela de consentimento OAuth**  
   - Tipo de usuário: **Externo** (ok para uso próprio)  
   - Preencha **Nome do app** e **Email de suporte**  
   - Em “Escopos”, pode deixar como está e **Continuar**  
   - Em “Usuários de teste”, adicione **seu próprio email**  
   - **Salvar e continuar** até **Resumo** → **Publicar/Teste** (não precisa “produzir” para uso próprio).

4. **Ative a Google Drive API**  
   - **APIs e Serviços** → **Biblioteca**  
   - Procure por **Google Drive API** → **Ativar**

5. **Crie as credenciais OAuth 2.0 (Desktop App)**  
   - **APIs e Serviços** → **Credenciais** → **+ Criar credenciais** → **ID do cliente OAuth**  
   - **Tipo de aplicativo**: **Aplicativo para computador**  
   - Dê um nome (ex.: *NRDownloader Desktop*) → **Criar**  
   - Clique em **Fazer download do JSON** (guarde o arquivo).

6. **Renomeie e coloque no projeto**  
   - Salve o arquivo baixado como **`credentials.json`**  
   - Coloque **na mesma pasta** do `nrdownloader.py`

7. **Primeira execução do app**  
   - Rode o script: `python google_drive_downloader.py`  
   - O navegador abrirá para você **autorizar** o acesso de leitura ao Drive  
   - Após autorizar, o app criará um **`token.json`** ao lado do script (reuso automático nas próximas execuções)

8. **“Deslogar” / revogar acesso**  
   - Apague o arquivo **`token.json`** para forçar novo login  
   - (Opcional) Revogue acessos em **Minha Conta Google → Segurança → Acesso de terceiros**

### Observações
- O app usa **escopo somente leitura**: `https://www.googleapis.com/auth/drive.readonly`
- Tipo **Desktop** não requer configurar URL de redirecionamento manualmente (o fluxo usa `http://localhost`).
- **Não versione** `credentials.json` ou `token.json` no Git (adicione ao `.gitignore`).

