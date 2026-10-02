# Instalação

## Pré-requisitos

- **Python 3.10 ou superior**;
- pip (acompanha o Python);
- acesso à internet;
- **Windows**, **Linux** ou **macOS**.

## Dependências

As dependências estão em `requirements.txt`:

```
playwright>=1.52,<2
beautifulsoup4>=4.13,<5
ddddocr>=1.4.0
opencv-python-headless>=4.8.0
pypdf>=5.0
openpyxl>=3.1
```

O processo é o mesmo nos três sistemas: criar o ambiente virtual, instalar os
pacotes e instalar o navegador. Só mudam os comandos de ativação do ambiente
virtual e, no Linux, as bibliotecas de sistema.

### Windows

1. Instale o Python em [python.org](https://www.python.org/downloads/). Durante
   a instalação, marque **"Add Python to PATH"**.

2. Abra o **Prompt de Comando** ou o **PowerShell** na pasta do projeto.

3. Crie e ative um ambiente virtual (recomendado):

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Instale as dependências:

   ```powershell
   pip install -r requirements.txt
   pip install -e .
   ```

5. Instale o navegador Chromium usado pelo Playwright:

   ```powershell
   python -m playwright install chromium
   ```

> Se o comando `python` não funcionar, use `py`. Se o PowerShell bloquear a
> ativação do ambiente virtual ("Running scripts is disabled"), execute uma vez:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`.

### Linux

1. Instale o Python e o `venv` (Ubuntu/Debian):

   ```bash
   sudo apt update
   sudo apt install python3 python3-venv
   ```

   Em Fedora/RHEL:

   ```bash
   sudo dnf install python3 python3-pip
   ```

2. Na pasta do projeto, crie e ative um ambiente virtual:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Instale as dependências:

   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

4. Instale o navegador e as dependências de sistema:

   ```bash
   python -m playwright install chromium --with-deps
   ```

   > O `--with-deps` normalmente exige `sudo`. Para instalar só as dependências
   > depois: `python -m playwright install-deps chromium`.

### macOS

1. Instale o Python (recomendado via Homebrew):

   ```bash
   brew install python
   ```

2. Na pasta do projeto, crie e ative um ambiente virtual:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Instale as dependências:

   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

4. Instale o navegador:

   ```bash
   python -m playwright install chromium
   ```

## Notas sobre o OCR

- O `ddddocr` usa `onnxruntime` e `opencv-python-headless`. Em algumas
  distribuições Linux pode ser necessário instalar `libgomp`:

  ```bash
  sudo apt install libgomp1
  ```

- O OCR é usado apenas para o CAPTCHA **automático**. Se não funcionar no seu
  ambiente, use `--manual-captcha` (resolve o CAPTCHA no navegador; o programa
  detecta quando o campo é preenchido).
