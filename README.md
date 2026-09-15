# PBD — Venda de Veículos

Sistema de gestão para revenda de veículos: perfis de usuário (gerente, vendedor, administrativo), cadastro de veículos, reservas, propostas, margem e comissão.

## Pré-requisitos

Antes de começar, tenha instalado na sua máquina:

- **Python 3.12+** — confira rodando `python3 --version`
- **PostgreSQL** (versão 14 ou superior) — confira rodando `psql --version`
- **Git**

Se algum desses não estiver instalado, procure "como instalar [nome] no [seu sistema operacional]" antes de continuar.

---

## Passo 1 — Clonar o repositório

```bash
git clone https://github.com/jonascar1/PBD-Vendadeveiculos.git
cd PBD-Vendadeveiculos
git checkout development
```

## Passo 2 — Criar e ativar o ambiente virtual

O ambiente virtual isola as dependências deste projeto do resto do seu sistema.

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

Você vai saber que funcionou porque o terminal passa a mostrar `(venv)` no começo da linha.

## Passo 3 — Instalar as dependências

Com o ambiente virtual ativo, rode:

```bash
pip install -r requirements.txt
```

Isso instala automaticamente o Django e tudo mais que o projeto precisa, nas versões corretas — sem precisar instalar um por um.

## Passo 4 — Configurar o banco de dados PostgreSQL

Entre no PostgreSQL como superusuário:

```bash
sudo -u postgres psql
```
*(no Windows, abra o "SQL Shell (psql)" que veio com a instalação)*

Dentro do `psql`, rode (troque a senha se quiser, mas anote o que usar):

```sql
CREATE DATABASE bdveiculos;
CREATE USER devdj WITH PASSWORD 'dj123';
GRANT ALL PRIVILEGES ON DATABASE bdveiculos TO devdj;
ALTER DATABASE bdveiculos OWNER TO devdj;

\c bdveiculos

ALTER SCHEMA public OWNER TO devdj;

\q
```

> Se você quiser usar outro nome de banco, usuário ou senha, tudo bem — só precisa deixar consistente com o próximo passo.

## Passo 5 — Configurar as variáveis do projeto

Na raiz do projeto, existe um arquivo `config/settings.py`. Confira se a seção `DATABASES` bate com o que você criou no banco:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'bdveiculos',
        'USER': 'devdj',
        'PASSWORD': 'dj123',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

## Passo 6 — Rodar as migrations

Isso cria todas as tabelas no banco de dados a partir dos models do projeto:

```bash
python manage.py migrate
```

Se der erro de permissão (`permission denied for schema public`), volte ao Passo 4 e confirme que rodou o `ALTER SCHEMA public OWNER TO devdj;` **depois** do `\c bdveiculos` (é fácil esquecer essa troca de banco no meio do processo).

## Passo 7 — Criar seu usuário administrador

```bash
python manage.py createsuperuser
```

Preencha usuário, e-mail (pode deixar em branco) e senha quando pedido.

## Passo 8 — Rodar o servidor

```bash
python manage.py runserver
```

Abra o navegador em: **http://127.0.0.1:8000/login/**

Se a tela de login aparecer, está tudo funcionando.

---

## Estrutura do projeto

```
PBD-Venda-de-Ve-culos/
├── config/              # Configurações do Django (settings, urls principal)
├── core/                # App principal: models, views, urls, templates
│   ├── models.py        # Usuario, PerfilVendedor, Veiculo, Reserva, etc.
│   ├── views.py         # Login, painéis por perfil
│   ├── urls.py          # Rotas do app
│   ├── decorators.py    # Checagem de permissão por perfil (sempre no servidor)
│   └── templates/core/  # Telas HTML
├── requirements.txt     # Dependências do projeto
└── manage.py
```

## Problemas comuns

| Erro | Causa provável | Solução |
|---|---|---|
| `ModuleNotFoundError: No module named 'django'` | Ambiente virtual não está ativo | Rode `source venv/bin/activate` de novo |
| `permission denied for schema public` | Permissões do Postgres não configuradas | Repita o Passo 4 com atenção ao `\c bdveiculos` |
| `django.db.utils.OperationalError: could not connect to server` | PostgreSQL não está rodando | Linux: `sudo service postgresql start` |
| Template não encontrado (`TemplateDoesNotExist`) | Arquivo HTML fora da pasta certa | Confirme que está em `core/templates/core/` |

## Fluxo de trabalho no Git

- A branch principal de desenvolvimento é `development` — sempre trabalhe a partir dela, não de `main`.
- Antes de começar a mexer no código: `git pull origin development`
- Depois de terminar uma parte: `git add .`, `git commit -m "descrição do que foi feito"`, `git push origin development`
