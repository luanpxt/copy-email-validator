"""
Email Validator — Flask Backend
Generic email marketing scoring tool. Calibrate with your own data.
"""

import os, json, sqlite3, io, csv, time
from collections import defaultdict
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv

load_dotenv()

from scorer import score_email, SEGMENT_BENCHMARKS, THEME_BENCHMARKS, get_effective_segment_benchmarks

app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = os.getenv("FLASK_ENV") == "production"
app.config["MAX_CONTENT_LENGTH"]      = 10 * 1024 * 1024  # 10 MB

APP_PASSWORD = os.getenv("APP_PASSWORD", "00000")
DB_PATH      = os.path.join(os.path.dirname(__file__), "data", "validator.db")
DATA_DIR     = os.path.join(os.path.dirname(__file__), "data")

# ── Rate limiting ─────────────────────────────────────────────────────────────
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
    os.makedirs(DATA_DIR, exist_ok=True)
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
            abertura    REAL,
            cltk        REAL,
            enviados    INTEGER,
            source      TEXT
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ── AI config helpers ─────────────────────────────────────────────────────────
def _ai_config_path():
    return os.path.join(DATA_DIR, "ai_config.json")

def get_ai_config() -> dict:
    try:
        with open(_ai_config_path()) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_ai_config(config: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_ai_config_path(), "w") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

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

@app.route("/welcome")
@login_required
def welcome_page():
    with open(os.path.join(app.static_folder, "welcome.html"), encoding="utf-8") as f:
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
    data      = request.json or {}
    subject   = data.get("subject", "").strip()
    body      = data.get("body", "").strip()
    preheader = data.get("preheader", "").strip()
    segment   = data.get("segment", "Geral")
    category  = data.get("category", "Newsletter")
    has_cta   = data.get("has_cta", True)
    cta_count = int(data.get("cta_count", 1))

    if not subject:
        return jsonify({"error": "Assunto é obrigatório"}), 400

    result = score_email(
        subject=subject, body=body, segment=segment,
        email_category=category, has_cta=has_cta,
        cta_count=cta_count, preheader=preheader,
    )

    ai_cfg = get_ai_config()
    if ai_cfg.get("api_key"):
        try:
            result = enrich_with_ai(result, subject, body, segment, category, preheader, ai_cfg)
        except Exception as e:
            result["ai_error"] = str(e)

    conn = get_db()
    conn.execute(
        "INSERT INTO validations (created_at, subject, segment, category, total_score, rating, result_json) VALUES (?,?,?,?,?,?,?)",
        (datetime.utcnow().isoformat(), subject, segment, category,
         result["total_score"], result["rating"], json.dumps(result, ensure_ascii=False))
    )
    conn.commit()
    conn.close()

    return jsonify(result)

# ── AI enrichment (multi-provider) ───────────────────────────────────────────
def _build_ai_prompt(result, subject, body, segment, category, preheader) -> str:
    score_summary = (
        f"Score total: {result['total_score']}/100 ({result['rating']})\n"
        f"- Assunto: {result['dimensions']['subject']['points']}/30\n"
        f"- Tema ({result['theme_label']}): {result['dimensions']['theme']['points']}/20\n"
        f"- Segmento ({segment}): {result['dimensions']['segment']['points']}/20\n"
        f"- Copy: {result['dimensions']['copy']['points']}/30\n"
        f"Abertura estimada: {result['performance']['abertura_estimada']}%\n"
        f"CLTK estimado: {result['performance']['cltk_estimado']}%"
    )
    return (
        "Você é um especialista em email marketing B2B. "
        "Analise este e-mail e dê 3 sugestões de melhoria ESPECÍFICAS E ACIONÁVEIS, em português.\n\n"
        f"Assunto: {subject}\n"
        f"Pré-header: {preheader or '(não informado)'}\n"
        f"Segmento: {segment} | Categoria: {category}\n"
        f"Copy:\n{body[:1000]}\n\n"
        f"{score_summary}\n\n"
        "Formato:\n1. [Área]: [Sugestão com exemplo reescrito quando relevante]\n2. ...\n3. ...\n\n"
        "Seja direto. Não repita o que o score já diz. Foque no que mais impacta o resultado."
    )

def enrich_with_ai(result, subject, body, segment, category, preheader, cfg: dict) -> dict:
    provider = cfg.get("provider", "anthropic").lower()
    api_key  = cfg["api_key"]
    prompt   = _build_ai_prompt(result, subject, body, segment, category, preheader)

    if provider == "openai":
        import openai
        model  = cfg.get("model") or "gpt-4o-mini"
        client = openai.OpenAI(
            api_key=api_key,
            base_url=cfg.get("base_url") or None,
        )
        resp = client.chat.completions.create(
            model=model, max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        ai_text = resp.choices[0].message.content

    else:  # anthropic (default)
        import anthropic
        model  = cfg.get("model") or "claude-haiku-4-5-20251001"
        client = anthropic.Anthropic(api_key=api_key)
        msg    = client.messages.create(
            model=model, max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        ai_text = msg.content[0].text

    result["ai_suggestions"] = ai_text
    result["ai_provider"]    = provider
    return result

# ── History API ───────────────────────────────────────────────────────────────
@app.route("/api/history")
@login_required
def history():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, created_at, subject, segment, category, total_score, rating "
        "FROM validations ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── Benchmarks API ────────────────────────────────────────────────────────────
@app.route("/api/benchmarks")
@login_required
def benchmarks():
    conn  = get_db()
    count = conn.execute("SELECT COUNT(*) as n FROM email_data").fetchone()["n"]
    conn.close()
    return jsonify({
        "segments":       get_effective_segment_benchmarks(),
        "themes":         THEME_BENCHMARKS,
        "imported_emails": count,
    })

# ── Admin: AI config ──────────────────────────────────────────────────────────
@app.route("/api/admin/ai-config", methods=["GET"])
@login_required
def get_ai_config_route():
    cfg = get_ai_config()
    # Never return the raw key to the client
    safe = {k: v for k, v in cfg.items() if k != "api_key"}
    safe["has_key"] = bool(cfg.get("api_key"))
    return jsonify(safe)

@app.route("/api/admin/ai-config", methods=["POST"])
@login_required
def save_ai_config_route():
    data     = request.json or {}
    provider = data.get("provider", "anthropic")
    model    = data.get("model", "").strip()
    base_url = data.get("base_url", "").strip()
    api_key  = data.get("api_key", "").strip()

    if provider not in ("anthropic", "openai", "custom"):
        return jsonify({"error": "Provider inválido. Use: anthropic, openai ou custom"}), 400

    existing = get_ai_config()
    cfg = {
        "provider": provider,
        "model":    model,
        "base_url": base_url,
        # Keep existing key if new one is blank
        "api_key":  api_key or existing.get("api_key", ""),
    }
    save_ai_config(cfg)
    return jsonify({"ok": True, "message": "Configuração de IA salva."})

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
        content  = file.read().decode("utf-8-sig")
        reader   = csv.DictReader(io.StringIO(content))
        rows_raw = list(reader)
        headers  = list(reader.fieldnames or [])
    except Exception as e:
        return jsonify({"error": f"Erro ao ler CSV: {str(e)}"}), 400

    col_candidates = {
        "subject":   ["Assunto", "Subject", "assunto", "subject", "Name", "Nome", "Email name"],
        "sent":      ["Enviado", "Sent", "enviado", "Recipients", "Enviados"],
        "open_rate": ["Taxa de abertura", "Open Rate", "taxa_abertura", "taxa de abertura", "Open rate"],
        "cltk":      ["Taxa de clickthrough", "CLTK", "taxa_cltk", "taxa de clickthrough", "Click rate"],
        "segment":   ["Segmento", "Segment", "Audience", "Público", "Lista", "List", "segmento", "audience"],
    }

    def find_col(hdrs, keys):
        for k in keys:
            if k in hdrs:
                return k
        return None

    subj_col = find_col(headers, col_candidates["subject"])
    open_col = find_col(headers, col_candidates["open_rate"])
    cltk_col = find_col(headers, col_candidates["cltk"])
    sent_col = find_col(headers, col_candidates["sent"])
    seg_col  = find_col(headers, col_candidates["segment"])

    if not (open_col and cltk_col):
        return jsonify({
            "error": "CSV não contém colunas de taxa de abertura e/ou taxa de clickthrough. "
                     f"Colunas encontradas: {headers[:10]}"
        }), 400

    inserted = 0
    conn = get_db()
    now  = datetime.utcnow().isoformat()

    for row in rows_raw:
        try:
            subject  = str(row.get(subj_col, "")).strip() if subj_col else ""
            abertura = float(str(row[open_col]).replace(",", ".").replace("%", ""))
            cltk     = float(str(row[cltk_col]).replace(",", ".").replace("%", ""))
            enviados = int(float(str(row[sent_col]).replace(",", "."))) if sent_col and row.get(sent_col) else None
            segment  = str(row.get(seg_col, "")).strip() if seg_col else None
            if not (0 <= abertura <= 100 and 0 <= cltk <= 100):
                continue
            conn.execute(
                "INSERT INTO email_data (imported_at, subject, segment, abertura, cltk, enviados, source) VALUES (?,?,?,?,?,?,?)",
                (now, subject, segment, abertura, cltk, enviados, file.filename)
            )
            inserted += 1
        except (ValueError, TypeError, KeyError):
            continue

    conn.commit()

    # Rebuild benchmarks from all imported data
    db_rows = conn.execute("SELECT segment, abertura, cltk FROM email_data").fetchall()
    conn.close()

    _rebuild_benchmarks(db_rows)

    return jsonify({
        "ok":           True,
        "inserted":     inserted,
        "total_rows":   len(rows_raw),
        "has_segments": seg_col is not None,
        "message":      f"{inserted} e-mails importados com sucesso."
                        + (f" Segmento detectado: coluna '{seg_col}'." if seg_col else ""),
    })

def _rebuild_benchmarks(db_rows):
    """Recalculate overall and per-segment benchmarks from all imported rows."""
    if not db_rows:
        return

    all_ab   = [r["abertura"] for r in db_rows if r["abertura"] is not None]
    all_cltk = [r["cltk"]    for r in db_rows if r["cltk"]    is not None]

    by_segment: dict = defaultdict(lambda: {"ab": [], "cltk": []})
    for r in db_rows:
        seg = (r["segment"] or "").strip()
        if seg:
            by_segment[seg]["ab"].append(r["abertura"])
            by_segment[seg]["cltk"].append(r["cltk"])

    custom = {
        "media_abertura": round(sum(all_ab)   / len(all_ab),   2) if all_ab   else 25.0,
        "media_cltk":     round(sum(all_cltk) / len(all_cltk), 2) if all_cltk else 1.5,
        "total_emails":   len(all_ab),
    }

    if by_segment:
        custom["segments"] = {}
        for seg, vals in by_segment.items():
            if vals["ab"] and vals["cltk"]:
                custom["segments"][seg] = {
                    "abertura": round(sum(vals["ab"])   / len(vals["ab"]),   2),
                    "cltk":     round(sum(vals["cltk"]) / len(vals["cltk"]), 2),
                    "total":    len(vals["ab"]),
                }

    os.makedirs(DATA_DIR, exist_ok=True)
    bench_path = os.path.join(DATA_DIR, "custom_benchmarks.json")
    with open(bench_path, "w") as f:
        json.dump(custom, f, ensure_ascii=False, indent=2)

# ── Admin: stats ──────────────────────────────────────────────────────────────
@app.route("/api/admin/stats")
@login_required
def admin_stats():
    conn        = get_db()
    total_val   = conn.execute("SELECT COUNT(*) as n FROM validations").fetchone()["n"]
    total_data  = conn.execute("SELECT COUNT(*) as n FROM email_data").fetchone()["n"]
    last_import = conn.execute("SELECT MAX(imported_at) as d FROM email_data").fetchone()["d"]
    avg_score   = conn.execute("SELECT AVG(total_score) as s FROM validations").fetchone()["s"]
    recent      = conn.execute(
        "SELECT subject, total_score, rating, segment, created_at FROM validations ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()

    bench_path   = os.path.join(DATA_DIR, "custom_benchmarks.json")
    custom_bench = {}
    if os.path.exists(bench_path):
        with open(bench_path) as f:
            custom_bench = json.load(f)

    return jsonify({
        "total_validations":  total_val,
        "total_email_data":   total_data,
        "last_import":        last_import,
        "avg_score":          round(avg_score, 1) if avg_score else None,
        "recent_validations": [dict(r) for r in recent],
        "custom_benchmarks":  custom_bench,
    })

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=5000)
