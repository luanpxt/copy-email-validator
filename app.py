"""
Email Validator — Flask Backend
Generic email marketing scoring tool. Calibrate with your own data.
"""

import os, json, sqlite3, io, csv, time, re
from collections import defaultdict
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv

load_dotenv()

from scorer import score_email

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
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            imported_at     TEXT NOT NULL,
            subject         TEXT,
            segment         TEXT,
            category        TEXT,
            email_copy      TEXT,
            abertura        REAL,
            cltk            REAL,
            enviados        INTEGER,
            has_button      INTEGER,
            button_count    INTEGER,
            has_hyperlink   INTEGER,
            hyperlink_count INTEGER,
            source          TEXT
        );
    """)
    conn.commit()
    conn.close()

init_db()

def _migrate_db():
    conn = get_db()
    new_cols = [
        ("category",        "TEXT"),
        ("email_copy",      "TEXT"),
        ("has_button",      "INTEGER"),
        ("button_count",    "INTEGER"),
        ("has_hyperlink",   "INTEGER"),
        ("hyperlink_count", "INTEGER"),
    ]
    for col, coltype in new_cols:
        try:
            conn.execute(f"ALTER TABLE email_data ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass
    conn.close()

_migrate_db()

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

# ── Clusters API ──────────────────────────────────────────────────────────────
@app.route("/api/clusters")
@login_required
def get_clusters():
    """Return available segments and categories extracted from imported data."""
    bench_path = os.path.join(DATA_DIR, "custom_benchmarks.json")
    if not os.path.exists(bench_path):
        return jsonify({"segments": [], "categories": [], "has_data": False})
    try:
        with open(bench_path) as f:
            data = json.load(f)
        clusters   = data.get("clusters", {})
        segments   = sorted({k.split("|")[0] for k in clusters if k.split("|")[0]})
        categories = sorted({k.split("|")[1] for k in clusters
                             if len(k.split("|")) > 1 and k.split("|")[1]})
        return jsonify({
            "segments":   segments,
            "categories": categories,
            "has_data":   bool(clusters),
        })
    except Exception:
        return jsonify({"segments": [], "categories": [], "has_data": False})

# ── Validate API ──────────────────────────────────────────────────────────────
@app.route("/api/validate", methods=["POST"])
@login_required
def validate():
    data            = request.json or {}
    subject         = data.get("subject",   "").strip()
    body            = data.get("body",      "").strip()
    preheader       = data.get("preheader", "").strip()
    segment         = data.get("segment",   "").strip()
    category        = data.get("category",  "").strip()
    has_cta         = data.get("has_cta",        False)
    cta_count       = int(data.get("cta_count",       0))
    has_hyperlink   = data.get("has_hyperlink",  False)
    hyperlink_count = int(data.get("hyperlink_count",  0))

    if not subject:
        return jsonify({"error": "Assunto é obrigatório"}), 400

    cluster_data = _load_cluster_data()

    result = score_email(
        subject=subject,
        body=body,
        segment=segment,
        category=category,
        preheader=preheader,
        has_cta=has_cta,
        cta_count=cta_count,
        has_hyperlink=has_hyperlink,
        hyperlink_count=hyperlink_count,
        cluster_data=cluster_data,
    )

    ai_cfg = get_ai_config()
    if ai_cfg.get("api_key"):
        try:
            result = enrich_with_ai(result, subject, body, segment, category, preheader, ai_cfg)
        except Exception as e:
            result["ai_error"] = str(e)

    conn = get_db()
    conn.execute(
        "INSERT INTO validations (created_at, subject, segment, category, total_score, rating, result_json) "
        "VALUES (?,?,?,?,?,?,?)",
        (datetime.utcnow().isoformat(), subject, segment, category,
         result["total_score"], result["rating"], json.dumps(result, ensure_ascii=False))
    )
    conn.commit()
    conn.close()

    return jsonify(result)

def _load_cluster_data() -> dict:
    bench_path = os.path.join(DATA_DIR, "custom_benchmarks.json")
    try:
        with open(bench_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# ── AI enrichment (multi-provider) ───────────────────────────────────────────
def _build_ai_prompt(result, subject, body, segment, category, preheader) -> str:
    dims = result.get("dimensions", {})
    score_summary = (
        f"Score total: {result['total_score']}/100 ({result['rating']})\n"
        f"- Assunto: {dims.get('subject', {}).get('points', 0)}/30\n"
        f"- Copy: {dims.get('copy', {}).get('points', 0)}/30\n"
        f"- Estrutura: {dims.get('structure', {}).get('points', 0)}/20\n"
        f"- Contexto/Cluster: {dims.get('context', {}).get('points', 0)}/20\n"
        f"Abertura estimada: {result.get('performance', {}).get('abertura_estimada', '?')}%\n"
        f"CLTK estimado: {result.get('performance', {}).get('cltk_estimado', '?')}%"
    )
    return (
        "Você é um especialista em email marketing B2B. "
        "Analise este e-mail e dê 3 sugestões de melhoria ESPECÍFICAS E ACIONÁVEIS, em português.\n\n"
        f"Assunto: {subject}\n"
        f"Pré-header: {preheader or '(não informado)'}\n"
        f"Segmento: {segment or 'Não informado'} | Categoria: {category or 'Não informada'}\n"
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
        client = openai.OpenAI(api_key=api_key, base_url=cfg.get("base_url") or None)
        resp   = client.chat.completions.create(
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
    custom_bench = _load_cluster_data()
    return jsonify({
        "custom_benchmarks": custom_bench,
        "imported_emails":   count,
        "has_data":          bool(custom_bench.get("clusters")),
    })

# ── Admin: AI config ──────────────────────────────────────────────────────────
@app.route("/api/admin/ai-config", methods=["GET"])
@login_required
def get_ai_config_route():
    cfg  = get_ai_config()
    safe = {k: v for k, v in cfg.items() if k != "api_key"}
    safe["has_key"] = bool(cfg.get("api_key"))
    return jsonify(safe)

@app.route("/api/admin/ai-config", methods=["POST"])
@login_required
def save_ai_config_route():
    data     = request.json or {}
    provider = data.get("provider", "anthropic")
    model    = data.get("model",    "").strip()
    base_url = data.get("base_url", "").strip()
    api_key  = data.get("api_key",  "").strip()

    if provider not in ("anthropic", "openai", "custom"):
        return jsonify({"error": "Provider inválido. Use: anthropic, openai ou custom"}), 400

    existing = get_ai_config()
    cfg = {
        "provider": provider,
        "model":    model,
        "base_url": base_url,
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
        "subject":          ["Assunto", "Subject", "assunto", "subject", "Name", "Nome", "Email name"],
        "sent":             ["Enviado", "Sent", "enviado", "Recipients", "Enviados"],
        "open_rate":        ["Taxa de abertura", "Open Rate", "taxa_abertura", "taxa de abertura", "Open rate"],
        "cltk":             ["Taxa de clickthrough", "CLTK", "taxa_cltk", "taxa de clickthrough", "Click rate"],
        "segment":          ["Segmento", "Segment", "Audience", "Público", "Lista", "List", "segmento", "audience"],
        "category":         ["Categoria", "Category", "Objetivo", "Tipo", "Type", "categoria", "category", "objetivo"],
        "copy":             ["Copy", "Texto", "Body", "Conteúdo", "Conteudo", "copy", "texto", "body"],
        "has_button":       ["Tem botão", "Has button", "Botão", "Button", "tem_botao", "has_button"],
        "button_count":     ["Qtd botões", "Button count", "qtd_botoes", "button_count"],
        "has_hyperlink":    ["Tem link", "Has link", "Hyperlink", "Link", "tem_link", "has_hyperlink"],
        "hyperlink_count":  ["Qtd links", "Link count", "qtd_links", "hyperlink_count"],
    }

    def find_col(hdrs, keys):
        for k in keys:
            if k in hdrs:
                return k
        return None

    subj_col      = find_col(headers, col_candidates["subject"])
    open_col      = find_col(headers, col_candidates["open_rate"])
    cltk_col      = find_col(headers, col_candidates["cltk"])
    sent_col      = find_col(headers, col_candidates["sent"])
    seg_col       = find_col(headers, col_candidates["segment"])
    cat_col       = find_col(headers, col_candidates["category"])
    copy_col      = find_col(headers, col_candidates["copy"])
    btn_col       = find_col(headers, col_candidates["has_button"])
    btn_cnt_col   = find_col(headers, col_candidates["button_count"])
    link_col      = find_col(headers, col_candidates["has_hyperlink"])
    link_cnt_col  = find_col(headers, col_candidates["hyperlink_count"])

    if not (open_col and cltk_col):
        return jsonify({
            "error": "CSV não contém colunas de taxa de abertura e/ou taxa de clickthrough. "
                     f"Colunas encontradas: {headers[:10]}"
        }), 400

    def _parse_bool(val):
        if val is None:
            return None
        return 1 if str(val).strip().lower() in ("1", "true", "sim", "yes", "s", "y") else 0

    def _parse_int(row, col):
        if not col or not row.get(col):
            return None
        try:
            return int(float(str(row[col]).replace(",", ".")))
        except (ValueError, TypeError):
            return None

    inserted = 0
    conn = get_db()
    now  = datetime.utcnow().isoformat()

    for row in rows_raw:
        try:
            abertura = float(str(row[open_col]).replace(",", ".").replace("%", ""))
            cltk     = float(str(row[cltk_col]).replace(",", ".").replace("%", ""))
            if not (0 <= abertura <= 100 and 0 <= cltk <= 100):
                continue

            conn.execute(
                "INSERT INTO email_data "
                "(imported_at, subject, segment, category, email_copy, abertura, cltk, enviados, "
                " has_button, button_count, has_hyperlink, hyperlink_count, source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    now,
                    str(row.get(subj_col, "")).strip() if subj_col else "",
                    str(row.get(seg_col,  "")).strip() if seg_col  else None,
                    str(row.get(cat_col,  "")).strip() if cat_col  else None,
                    str(row.get(copy_col, "")).strip() if copy_col else None,
                    abertura, cltk,
                    _parse_int(row, sent_col),
                    _parse_bool(row.get(btn_col))  if btn_col  else None,
                    _parse_int(row, btn_cnt_col),
                    _parse_bool(row.get(link_col)) if link_col else None,
                    _parse_int(row, link_cnt_col),
                    file.filename,
                )
            )
            inserted += 1
        except (ValueError, TypeError, KeyError):
            continue

    conn.commit()

    db_rows = conn.execute(
        "SELECT segment, category, abertura, cltk, subject, email_copy, "
        "has_button, button_count, has_hyperlink, hyperlink_count FROM email_data"
    ).fetchall()
    conn.close()

    _rebuild_benchmarks(db_rows)

    extra_cols = [c for c in [
        seg_col  and "segmento",
        cat_col  and "categoria",
        copy_col and "copy",
        btn_col  and "botão",
        link_col and "hiperlink",
    ] if c]

    return jsonify({
        "ok":         True,
        "inserted":   inserted,
        "total_rows": len(rows_raw),
        "message":    f"{inserted} e-mails importados com sucesso."
                      + (f" Colunas detectadas: {', '.join(extra_cols)}." if extra_cols else
                         " Dica: adicione colunas de Segmento, Categoria e Copy para calibração mais precisa."),
    })

# ── Feature extraction & benchmark rebuild ───────────────────────────────────

def _count_emojis(text: str) -> int:
    return len(re.findall(r'[\U00010000-\U0010ffff]|[☀-⟿]', text or ""))

def _word_count(text: str) -> int:
    return len((text or "").split())

def _percentile(data: list, p: int) -> float:
    if not data:
        return 0.0
    s   = sorted(data)
    idx = (p / 100) * (len(s) - 1)
    lo  = int(idx)
    hi  = min(lo + 1, len(s) - 1)
    return round(s[lo] + (idx - lo) * (s[hi] - s[lo]), 2)


def _rebuild_benchmarks(db_rows):
    """Rebuild cluster benchmarks with percentiles and feature profiles from all imported rows."""
    if not db_rows:
        return

    clusters: dict = defaultdict(list)
    for r in db_rows:
        seg = (r["segment"]  or "").strip()
        cat = (r["category"] or "").strip()
        clusters[f"{seg}|{cat}"].append(r)

    cluster_data = {}
    for key, rows in clusters.items():
        ab = [r["abertura"] for r in rows if r["abertura"] is not None]
        cl = [r["cltk"]    for r in rows if r["cltk"]    is not None]
        if not ab:
            continue

        subj_lens   = [len(r["subject"]    or "") for r in rows if r["subject"]]
        subj_emojis = [_count_emojis(r["subject"] or "") for r in rows if r["subject"]]
        copy_words  = [_word_count(r["email_copy"] or "") for r in rows if r["email_copy"]]
        copy_lens   = [len(r["email_copy"] or "") for r in rows if r["email_copy"]]
        btn_rows    = [r["has_button"]      for r in rows if r["has_button"]      is not None]
        link_rows   = [r["has_hyperlink"]   for r in rows if r["has_hyperlink"]   is not None]
        btn_cnts    = [r["button_count"]    for r in rows if r["button_count"]    is not None]
        link_cnts   = [r["hyperlink_count"] for r in rows if r["hyperlink_count"] is not None]

        cluster_data[key] = {
            "total": len(ab),
            "abertura": {
                "p25": _percentile(ab, 25),
                "p50": _percentile(ab, 50),
                "p75": _percentile(ab, 75),
            },
            "cltk": {
                "p25": _percentile(cl, 25),
                "p50": _percentile(cl, 50),
                "p75": _percentile(cl, 75),
            },
            "subject": {
                "len_p25":   _percentile(subj_lens,   25) if subj_lens   else None,
                "len_p50":   _percentile(subj_lens,   50) if subj_lens   else None,
                "len_p75":   _percentile(subj_lens,   75) if subj_lens   else None,
                "emoji_p50": _percentile(subj_emojis, 50) if subj_emojis else None,
            },
            "copy": {
                "word_p25": _percentile(copy_words, 25) if copy_words else None,
                "word_p50": _percentile(copy_words, 50) if copy_words else None,
                "word_p75": _percentile(copy_words, 75) if copy_words else None,
                "len_p50":  _percentile(copy_lens,  50) if copy_lens  else None,
            },
            "cta": {
                "button_rate":  round(sum(btn_rows)  / len(btn_rows),  2) if btn_rows  else None,
                "link_rate":    round(sum(link_rows) / len(link_rows), 2) if link_rows else None,
                "btn_cnt_p50":  _percentile(btn_cnts,  50)               if btn_cnts  else None,
                "link_cnt_p50": _percentile(link_cnts, 50)               if link_cnts else None,
            },
        }

    all_ab   = [r["abertura"] for r in db_rows if r["abertura"] is not None]
    all_cltk = [r["cltk"]    for r in db_rows if r["cltk"]    is not None]

    output = {
        "clusters": cluster_data,
        "global": {
            "total":        len(all_ab),
            "abertura_p50": _percentile(all_ab,   50),
            "cltk_p50":     _percentile(all_cltk, 50),
        },
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "custom_benchmarks.json"), "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

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

    return jsonify({
        "total_validations":  total_val,
        "total_email_data":   total_data,
        "last_import":        last_import,
        "avg_score":          round(avg_score, 1) if avg_score else None,
        "recent_validations": [dict(r) for r in recent],
        "custom_benchmarks":  _load_cluster_data(),
    })

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=5000)
