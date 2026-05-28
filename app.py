"""
Cobli Email Validator — Flask Backend
"""

import os, json, sqlite3, io, csv, time
from collections import defaultdict
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv

load_dotenv()

from scorer import score_email, SEGMENT_BENCHMARKS, THEME_BENCHMARKS

app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = os.getenv("FLASK_ENV") == "production"
app.config["MAX_CONTENT_LENGTH"]      = 10 * 1024 * 1024  # 10 MB

APP_PASSWORD  = os.getenv("APP_PASSWORD", "cobli2026")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DB_PATH       = os.path.join(os.path.dirname(__file__), "data", "validator.db")

# ── Rate limiting (in-memory, simples) ───────────────────────────────────────
_login_attempts: dict = defaultdict(list)
_MAX_ATTEMPTS   = 10
_WINDOW_SECONDS = 300

def _is_rate_limited(ip: str) -> bool:
    now  = time.time()
    hits = [t for t in _login_attempts[ip] if now - t < _WINDOW_SECONDS]
    _login_attempts[ip] = hits
    if len(hits) >= _MAX_ATTEMPTS:
        return True
    _login_attempts[ip].append(now)
    return False

# ── Security headers ──────────────────────────────────────────────────────────
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["X-XSS-Protection"]        = "1; mode=block"
    response.headers["Referrer-Policy"]          = "strict-origin-when-cross-origin"
    return response

# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS validations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT NOT NULL,
            subject     TEXT,
            segment     TEXT,
            category    TEXT,
            total_score INTEGER,
            rating      TEXT,
            result_json TEXT
        );
        CREATE TABLE IF NOT EXISTS email_data (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            imported_at TEXT NOT NULL,
            subject     TEXT,
            segment     TEXT,
            category    TEXT,
            abertura    REAL,
            cltk        REAL,
            enviados    INTEGER,
            source      TEXT
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ── Auth ──────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated

# ── Pages ─────────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    with open(os.path.join(app.static_folder, "app.html"), encoding="utf-8") as f:
        return f.read()

@app.route("/login", methods=["GET"])
def login_page():
    with open(os.path.join(app.static_folder, "login.html"), encoding="utf-8") as f:
        return f.read()

@app.route("/admin")
@login_required
def admin_page():
    with open(os.path.join(app.static_folder, "admin.html"), encoding="utf-8") as f:
        return f.read()

# ── Auth API ──────────────────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def login():
    ip = request.remote_addr or "unknown"
    if _is_rate_limited(ip):
        return jsonify({"ok": False, "error": "Muitas tentativas. Aguarde alguns minutos."}), 429
    data = request.json or {}
    if data.get("password") == APP_PASSWORD:
        session["logged_in"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Senha incorreta"}), 401

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/me")
def me():
    return jsonify({"logged_in": bool(session.get("logged_in"))})

# ── Validate API ──────────────────────────────────────────────────────────────
@app.route("/api/validate", methods=["POST"])
@login_required
def validate():
    data = request.json or {}
    subject       = data.get("subject", "").strip()
    body          = data.get("body", "").strip()
    preheader     = data.get("preheader", "").strip()
    segment       = data.get("segment", "Geral")
    category      = data.get("category", "Newsletter")
    has_cta       = data.get("has_cta", True)
    cta_count     = int(data.get("cta_count", 1))

    if not subject:
        return jsonify({"error": "Assunto é obrigatório"}), 400

    result = score_email(
        subject=subject,
        body=body,
        segment=segment,
        email_category=category,
        has_cta=has_cta,
        cta_count=cta_count,
        preheader=preheader,
    )

    # Se tiver API Anthropic, enriquecer sugestões
    if ANTHROPIC_KEY:
        try:
            result = enrich_with_claude(result, subject, body, segment, category, preheader)
        except Exception as e:
            result["claude_error"] = str(e)

    # Salvar histórico
    conn = get_db()
    conn.execute(
        "INSERT INTO validations (created_at, subject, segment, category, total_score, rating, result_json) VALUES (?,?,?,?,?,?,?)",
        (datetime.utcnow().isoformat(), subject, segment, category,
         result["total_score"], result["rating"], json.dumps(result, ensure_ascii=False))
    )
    conn.commit()
    conn.close()

    return jsonify(result)

# ── Claude enrichment (opcional) ──────────────────────────────────────────────
def enrich_with_claude(result, subject, body, segment, category, preheader):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    score_summary = f"""
Score total: {result['total_score']}/100 ({result['rating']})
- Assunto: {result['dimensions']['subject']['points']}/30
- Tema ({result['theme_label']}): {result['dimensions']['theme']['points']}/20
- Segmento ({segment}): {result['dimensions']['segment']['points']}/20
- Copy: {result['dimensions']['copy']['points']}/30
Abertura estimada: {result['performance']['abertura_estimada']}%
CLTK estimado: {result['performance']['cltk_estimado']}%
"""

    prompt = f"""Você é um especialista em email marketing B2B para a Cobli, empresa brasileira de gestão de frotas.
Analise este e-mail com base nos dados históricos de performance da Cobli.

CONTEXTO HISTÓRICO DA COBLI:
- Os e-mails com maior CLTK são os de Novidades do Painel/Produto (média 4,42% CLTK)
- [Guia] no assunto gera abertura alta mas CLTK muito baixo
- Clientes têm CLTK 3,22%; Prospects apenas 0,84%
- Plain text supera formato visual para Conversão
- Benefício concreto no assunto > curiosidade vaga

E-MAIL PARA ANÁLISE:
Assunto: {subject}
Pré-header: {preheader or '(não informado)'}
Segmento: {segment} | Categoria: {category}
Copy:
{body[:1000]}

{score_summary}

Dê 3 sugestões de melhoria ESPECÍFICAS E ACIONÁVEIS, em português, no formato:
1. [Área]: [Sugestão concreta com exemplo reescrito quando relevante]
2. ...
3. ...

Seja direto. Não repita o que o score já diz. Foque no que mais impacta o resultado."""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    claude_text = msg.content[0].text

    result["claude_suggestions"] = claude_text
    return result

# ── History API ───────────────────────────────────────────────────────────────
@app.route("/api/history")
@login_required
def history():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, created_at, subject, segment, category, total_score, rating FROM validations ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── Benchmarks API ────────────────────────────────────────────────────────────
@app.route("/api/benchmarks")
@login_required
def benchmarks():
    conn = get_db()
    # Contar e-mails importados
    count = conn.execute("SELECT COUNT(*) as n FROM email_data").fetchone()["n"]
    conn.close()
    return jsonify({
        "segments": SEGMENT_BENCHMARKS,
        "themes": THEME_BENCHMARKS,
        "imported_emails": count,
    })

# ── Admin: upload CSV ─────────────────────────────────────────────────────────
@app.route("/api/admin/upload", methods=["POST"])
@login_required
def admin_upload():
    if "file" not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400

    file = request.files["file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error": "Formato inválido. Envie um .csv"}), 400

    try:
        content = file.read().decode("utf-8-sig")
        reader  = csv.DictReader(io.StringIO(content))
        rows_raw = list(reader)
        headers  = reader.fieldnames or []
    except Exception as e:
        return jsonify({"error": f"Erro ao ler CSV: {str(e)}"}), 400

    # Mapear colunas — aceita português (HubSpot BR) e inglês
    col_candidates = {
        "subject":   ["Assunto", "Subject", "assunto", "subject"],
        "sent":      ["Enviado", "Sent", "enviado"],
        "open_rate": ["Taxa de abertura", "Open Rate", "taxa_abertura", "taxa de abertura"],
        "cltk":      ["Taxa de clickthrough", "CLTK", "taxa_cltk", "taxa de clickthrough"],
    }

    def find_col(headers, keys):
        for k in keys:
            if k in headers:
                return k
        return None

    subj_col = find_col(headers, col_candidates["subject"])
    open_col = find_col(headers, col_candidates["open_rate"])
    cltk_col = find_col(headers, col_candidates["cltk"])
    sent_col = find_col(headers, col_candidates["sent"])

    if not (open_col and cltk_col):
        return jsonify({
            "error": "CSV não contém colunas de taxa de abertura e/ou taxa de clickthrough. "
                     f"Colunas encontradas: {list(headers[:10])}"
        }), 400

    inserted = 0
    conn = get_db()
    now  = datetime.utcnow().isoformat()

    for row in rows_raw:
        try:
            subject  = str(row.get(subj_col, "")).strip()
            abertura = float(str(row[open_col]).replace(",", ".").replace("%", ""))
            cltk     = float(str(row[cltk_col]).replace(",", ".").replace("%", ""))
            enviados = int(float(str(row[sent_col]).replace(",", "."))) if sent_col and row.get(sent_col) else None
            if not (0 <= abertura <= 100 and 0 <= cltk <= 100):
                continue
            conn.execute(
                "INSERT INTO email_data (imported_at, subject, abertura, cltk, enviados, source) VALUES (?,?,?,?,?,?)",
                (now, subject, abertura, cltk, enviados, file.filename)
            )
            inserted += 1
        except (ValueError, TypeError, KeyError):
            continue

    conn.commit()

    # Recalcular benchmarks dinâmicos
    db_rows = conn.execute("SELECT abertura, cltk FROM email_data").fetchall()
    conn.close()

    if db_rows:
        ab_vals   = [r["abertura"] for r in db_rows if r["abertura"] is not None]
        cltk_vals = [r["cltk"]    for r in db_rows if r["cltk"] is not None]
        avg_ab    = round(sum(ab_vals)   / len(ab_vals),   2) if ab_vals   else 34.2
        avg_cltk  = round(sum(cltk_vals) / len(cltk_vals), 2) if cltk_vals else 1.74
        bench_path = os.path.join(os.path.dirname(__file__), "data", "custom_benchmarks.json")
        os.makedirs(os.path.dirname(bench_path), exist_ok=True)
        with open(bench_path, "w") as f:
            json.dump({"media_abertura": avg_ab, "media_cltk": avg_cltk,
                       "total_emails": len(ab_vals)}, f)

    return jsonify({
        "ok": True,
        "inserted": inserted,
        "total_rows": len(rows_raw),
        "message": f"{inserted} e-mails importados com sucesso."
    })

# ── Admin: stats ──────────────────────────────────────────────────────────────
@app.route("/api/admin/stats")
@login_required
def admin_stats():
    conn = get_db()
    total_val  = conn.execute("SELECT COUNT(*) as n FROM validations").fetchone()["n"]
    total_data = conn.execute("SELECT COUNT(*) as n FROM email_data").fetchone()["n"]
    last_import = conn.execute("SELECT MAX(imported_at) as d FROM email_data").fetchone()["d"]
    avg_score  = conn.execute("SELECT AVG(total_score) as s FROM validations").fetchone()["s"]
    recent     = conn.execute(
        "SELECT subject, total_score, rating, segment, created_at FROM validations ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()

    bench_path = os.path.join(os.path.dirname(__file__), "data", "custom_benchmarks.json")
    custom_bench = {}
    if os.path.exists(bench_path):
        with open(bench_path) as f:
            custom_bench = json.load(f)

    return jsonify({
        "total_validations": total_val,
        "total_email_data":  total_data,
        "last_import":       last_import,
        "avg_score":         round(avg_score, 1) if avg_score else None,
        "recent_validations": [dict(r) for r in recent],
        "custom_benchmarks": custom_bench,
    })

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=5000)
                                 