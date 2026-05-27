# Cobli Email Validator — Guia de Deploy

## Deploy recomendado: Render.com (gratuito)

### Passo a passo

**1. Criar conta no GitHub**
- Crie um repositório privado (ex: `cobli-email-validator`)
- Faça upload de todos os arquivos desta pasta

**2. Criar conta no Render.com**
- Acesse https://render.com e crie uma conta gratuita
- Clique em **New → Web Service**
- Conecte seu repositório GitHub
- O Render vai detectar o `render.yaml` automaticamente

**3. Configurar variáveis de ambiente no Render**
No painel do Render, vá em **Environment** e adicione:

| Variável | Valor |
|----------|-------|
| `APP_PASSWORD` | Senha do time (ex: `cobli@2026`) |
| `SECRET_KEY` | Qualquer string longa e aleatória |
| `ANTHROPIC_API_KEY` | *(opcional)* Chave da API Anthropic para sugestões com IA |

**4. Deploy**
- Clique em **Create Web Service**
- O deploy leva ~2 minutos
- Acesse a URL gerada (ex: `cobli-email-validator.onrender.com`)

---

## Uso com API Anthropic (sugestões em IA)

Se quiser sugestões de melhoria em linguagem natural via Claude:

1. Crie uma conta em https://console.anthropic.com
2. Gere uma API key em **API Keys**
3. Adicione como variável `ANTHROPIC_API_KEY` no Render
4. O modelo usado é `claude-haiku-4-5-20251001` — custo estimado: **< R$10/mês** para uso interno

---

## Atualizar inteligência com novos dados

1. No HubSpot: **Marketing → Email → Exportar → CSV**
2. Acesse `/admin` na ferramenta
3. Faça upload do CSV exportado
4. A ferramenta processa automaticamente e atualiza os benchmarks

---

## Rodar localmente (desenvolvimento)

```bash
# Instalar dependências
pip install -r requirements.txt

# Configurar variáveis
cp .env.example .env
# Edite o .env com sua senha

# Rodar
python app.py
# Acesse: http://localhost:5000
```

---

## Estrutura do projeto

```
email-validator/
├── app.py           # Backend Flask (rotas, API, auth)
├── scorer.py        # Motor de scoring (lógica de análise)
├── requirements.txt
├── render.yaml      # Config de deploy no Render
├── .env.example
├── static/
│   ├── app.html     # Interface principal
│   ├── login.html   # Tela de login
│   └── admin.html   # Painel admin (upload CSV, stats)
└── data/            # Criado automaticamente
    └── validator.db # Banco SQLite (histórico, dados importados)
```

---

## Notas

- O banco de dados (SQLite) é criado automaticamente na primeira execução
- No Render free tier, o serviço "dorme" após 15 min sem uso — o primeiro acesso pode levar ~30s para "acordar"
- Para produção com acesso frequente, considere o plano Starter do Render (US$7/mês)
