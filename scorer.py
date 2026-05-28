"""
Email Validator — Scoring Engine
Generic email marketing scoring based on industry benchmarks.
Calibrate with your own data by uploading a historical CSV.
"""

import re, json, os

# ── Default benchmarks (industry averages) ────────────────────────────────────

SEGMENT_BENCHMARKS = {
    "Clientes":  {"abertura": 27.0, "cltk": 3.00, "label": "Clientes / Ativos"},
    "MQL+":      {"abertura": 30.0, "cltk": 2.00, "label": "MQL+ (leads quentes)"},
    "MQL-":      {"abertura": 22.0, "cltk": 1.00, "label": "MQL- (leads frios)"},
    "Lost":      {"abertura": 15.0, "cltk": 0.70, "label": "Lost / Churn"},
    "Prospects": {"abertura": 32.0, "cltk": 0.80, "label": "Prospects"},
    "Geral":     {"abertura": 25.0, "cltk": 1.50, "label": "Base geral / Newsletter"},
}

THEME_BENCHMARKS = {
    "product_news":   {"cltk": 4.00, "label": "Novidades de Produto / Features"},
    "roi_efficiency": {"cltk": 2.50, "label": "ROI / Custo / Eficiência"},
    "events":         {"cltk": 2.20, "label": "Eventos / Webinars"},
    "security":       {"cltk": 1.80, "label": "Segurança / Compliance"},
    "logistics":      {"cltk": 1.60, "label": "Logística / Operações"},
    "trends_tech":    {"cltk": 1.30, "label": "Tendências / Tecnologia / IA"},
    "people_hr":      {"cltk": 1.00, "label": "Pessoas / RH / Equipe"},
    "general":        {"cltk": 1.50, "label": "Geral / Newsletter"},
}

CATEGORY_BENCHMARKS = {
    "Agradecimento": {"cltk": 8.0,  "abertura": 50.0},
    "Nutricao":      {"cltk": 2.5,  "abertura": 30.0},
    "Conversao":     {"cltk": 3.5,  "abertura": 28.0},
    "Newsletter":    {"cltk": 1.5,  "abertura": 25.0},
    "Pre-vendas":    {"cltk": 5.0,  "abertura": 32.0},
}

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _load_custom_benchmarks() -> dict:
    path = os.path.join(_DATA_DIR, "custom_benchmarks.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_effective_segment_benchmarks() -> dict:
    """Merge default benchmarks with any per-segment custom data from uploads."""
    custom = _load_custom_benchmarks()
    if not custom.get("segments"):
        return SEGMENT_BENCHMARKS
    merged = {k: dict(v) for k, v in SEGMENT_BENCHMARKS.items()}
    for seg, data in custom["segments"].items():
        if seg in merged:
            merged[seg].update({k: v for k, v in data.items() if k in ("abertura", "cltk")})
    return merged


# ── Theme classification ───────────────────────────────────────────────────────

def classify_theme(subject: str, body: str = "") -> str:
    text = (subject + " " + body).lower()

    if any(k in text for k in ["product", "feature", "release", "launch", "update",
                                "new feature", "improvement", "dashboard", "platform",
                                "painel", "plataforma", "novidade", "melhoria",
                                "lançamento", "atualização", "nova feature", "melhoramos"]):
        return "product_news"
    if any(k in text for k in ["roi", "cost", "saving", "reduce cost", "efficiency",
                                "revenue", "profit", "budget", "custo", "economia",
                                "eficiência", "eficiencia", "combustível", "reduzir gastos"]):
        return "roi_efficiency"
    if any(k in text for k in ["event", "webinar", "conference", "workshop", "course",
                                "training", "evento", "curso", "treinamento"]):
        return "events"
    if any(k in text for k in ["security", "compliance", "safety", "risk", "breach",
                                "segurança", "seguranca", "compliance", "acidente",
                                "prevenção", "prevencao", "risco"]):
        return "security"
    if any(k in text for k in ["logistics", "delivery", "shipping", "supply chain",
                                "logística", "logistica", "entrega", "rota",
                                "roteirização", "roteirizacao", "field", "operações"]):
        return "logistics"
    if any(k in text for k in ["ai", "artificial intelligence", "automation", "trend",
                                "technology", "digital", "future", "inteligência artificial",
                                "automação", "automacao", "tendência", "tendencia",
                                "tecnologia", "futuro"]):
        return "trends_tech"
    if any(k in text for k in ["people", "hr", "team", "employee", "staff", "culture",
                                "pessoas", "equipe", "rh", "colaborador", "funcionário",
                                "funcionario", "gestão de pessoa"]):
        return "people_hr"
    return "general"


# ── Subject scoring (0–30 pts) ─────────────────────────────────────────────────

def score_subject(subject: str) -> dict:
    s  = subject.strip()
    sl = s.lower()
    points    = 0
    breakdown = []

    # Product/feature keywords — highest-performing category in most B2B email programs
    product_kws = ["product", "feature", "launch", "update", "new", "release", "improvement",
                   "painel", "novidade", "novidades", "melhoria", "melhorias",
                   "lançamento", "lancamento", "atualização", "atualizacao",
                   "nova feature", "melhoramos", "implementamos"]
    if any(k in sl for k in product_kws):
        points += 10
        breakdown.append({"type": "positive", "msg": "Menciona produto/feature diretamente (+10 pts) — padrão dos maiores CLTKs em programas B2B"})

    # Concrete benefit verb
    benefit_kws = ["reduzir", "economizar", "aumentar", "melhorar", "otimizar",
                   "evitar", "resolver", "facilitar", "transformar", "descobrir",
                   "reduce", "save", "increase", "improve", "optimize", "solve"]
    if any(k in sl for k in benefit_kws):
        points += 6
        breakdown.append({"type": "positive", "msg": "Contém verbo de benefício concreto (+6 pts)"})

    # Emoji usage
    emoji_count = len(re.findall(r'[\U00010000-\U0010ffff]|[☀-⟿]', s))
    if 1 <= emoji_count <= 2:
        points += 4
        breakdown.append({"type": "positive", "msg": f"{emoji_count} emoji(s) — uso adequado (+4 pts)"})
    elif emoji_count > 3:
        points -= 2
        breakdown.append({"type": "warning", "msg": f"{emoji_count} emojis — excesso pode prejudicar deliverability (-2 pts)"})

    # Ideal length
    char_count = len(s)
    if 35 <= char_count <= 80:
        points += 5
        breakdown.append({"type": "positive", "msg": f"{char_count} caracteres — comprimento ideal 35–80 (+5 pts)"})
    elif char_count < 20:
        points -= 3
        breakdown.append({"type": "negative", "msg": f"Muito curto ({char_count} chars) — pouca informação (-3 pts)"})
    elif char_count > 100:
        points -= 4
        breakdown.append({"type": "negative", "msg": f"Muito longo ({char_count} chars) — pode ser truncado em mobile (-4 pts)"})
    else:
        breakdown.append({"type": "neutral", "msg": f"{char_count} caracteres — aceitável, mas o ideal é 35–80"})

    # Direct/personalized language
    if re.search(r'\bvocê\b|\byour\b|\byou\b|\bseu\b|\bsua\b', sl):
        points += 3
        breakdown.append({"type": "positive", "msg": "Usa linguagem direta/personalizada (+3 pts)"})

    # Patterns that underperform
    guia_pattern = re.search(r'\[guia\]|\[ebook\]|\[webinar\]|\[material\]|\[guide\]|\[report\]', sl)
    if guia_pattern:
        points -= 8
        breakdown.append({"type": "negative", "msg": "Padrão [Guia]/[Ebook] — tende a gerar abertura alta mas CLTK muito baixo (-8 pts). Considere remover o prefixo."})

    vague_kws = ["você sabia", "voce sabia", "descubra como", "tudo sobre",
                 "tendências de", "o futuro de", "did you know", "everything about"]
    if any(k in sl for k in vague_kws):
        points -= 5
        breakdown.append({"type": "negative", "msg": "Assunto vago/curiosidade sem especificidade (-5 pts) — promete mas não entrega contexto"})

    # Excessive caps
    upper_ratio = sum(1 for c in s if c.isupper()) / max(len(s), 1)
    if upper_ratio > 0.4:
        points -= 3
        breakdown.append({"type": "warning", "msg": "Excesso de letras maiúsculas — pode ativar filtros de spam (-3 pts)"})

    points = max(0, min(30, points))
    return {"points": points, "max": 30, "breakdown": breakdown}


# ── Theme scoring (0–20 pts) ───────────────────────────────────────────────────

def score_theme(theme_key: str) -> dict:
    benchmark = THEME_BENCHMARKS.get(theme_key, THEME_BENCHMARKS["general"])
    max_cltk  = 4.0  # product_news
    ratio     = benchmark["cltk"] / max_cltk
    points    = round(ratio * 20)
    breakdown = []

    if theme_key == "product_news":
        breakdown.append({"type": "positive", "msg": f"Tema de maior CLTK histórico em B2B ({benchmark['cltk']}%) — e-mails de produto lideram engajamento (+{points} pts)"})
    elif theme_key in ("trends_tech", "people_hr"):
        breakdown.append({"type": "warning", "msg": f"Tema de CLTK moderado/baixo ({benchmark['cltk']}%). Considere ancorar em resultado concreto ou feature do produto (+{points} pts)"})
    else:
        breakdown.append({"type": "neutral", "msg": f"Tema com CLTK típico de {benchmark['cltk']}% em programas B2B (+{points} pts)"})

    return {
        "points":      points,
        "max":         20,
        "theme":       theme_key,
        "theme_label": benchmark["label"],
        "theme_cltk":  benchmark["cltk"],
        "breakdown":   breakdown,
    }


# ── Segment scoring (0–20 pts) ────────────────────────────────────────────────

def score_segment(segment: str, email_category: str) -> dict:
    benchmarks = get_effective_segment_benchmarks()
    bench      = benchmarks.get(segment, SEGMENT_BENCHMARKS["Geral"])
    breakdown  = []
    points     = 10

    if segment == "Clientes":
        points = 18
        breakdown.append({"type": "positive", "msg": f"Clientes têm o melhor CLTK ({bench['cltk']}%) — segmento ideal para newsletter e conteúdo de produto"})
    elif segment == "MQL+":
        points = 14
        breakdown.append({"type": "positive", "msg": f"MQL+ tem boa resposta ({bench['cltk']}% CLTK) — conteúdo pode acelerar conversão"})
    elif segment == "MQL-":
        points = 10
        breakdown.append({"type": "neutral", "msg": f"MQL- tem CLTK médio ({bench['cltk']}%) — conteúdo mais direto e com CTA único tende a performar melhor"})
    elif segment == "Lost":
        points = 7
        breakdown.append({"type": "warning", "msg": f"Lost tem abertura baixa ({bench['abertura']}%) e CLTK de {bench['cltk']}% — recomendado fluxo de reativação específico"})
    elif segment == "Prospects":
        points = 5
        breakdown.append({"type": "negative", "msg": f"Prospects abrem ({bench['abertura']}%) mas não clicam ({bench['cltk']}% CLTK). E-mail mais curto com 1 CTA direto converte melhor nesse público."})
    else:
        breakdown.append({"type": "neutral", "msg": f"Base geral — CLTK típico de {bench['cltk']}%"})

    # Category × segment cross-signals
    if email_category == "Conversao" and segment == "Prospects":
        breakdown.append({"type": "warning", "msg": "E-mail de Conversão para Prospects: plain text curto supera formato visual para esse público"})
    if email_category == "Newsletter" and segment == "Prospects":
        points -= 2
        breakdown.append({"type": "negative", "msg": "Newsletter para Prospects: CLTK historicamente muito baixo — considere e-mail de conversão direto"})

    points = max(0, min(20, points))
    return {
        "points":             points,
        "max":                20,
        "breakdown":          breakdown,
        "benchmark_abertura": bench["abertura"],
        "benchmark_cltk":     bench["cltk"],
    }


# ── Copy scoring (0–30 pts) ───────────────────────────────────────────────────

def score_copy(body: str, email_category: str, has_cta: bool, cta_count: int) -> dict:
    points    = 0
    breakdown = []
    b         = body.strip()
    bl        = b.lower()
    word_count = len(b.split())

    # CTA presence
    if has_cta:
        points += 10
        breakdown.append({"type": "positive", "msg": "Tem CTA (call-to-action) (+10 pts)"})
        if cta_count == 1:
            points += 5
            breakdown.append({"type": "positive", "msg": "CTA único — foco claro aumenta taxa de clique (+5 pts)"})
        elif cta_count > 2:
            breakdown.append({"type": "warning", "msg": f"{cta_count} CTAs — múltiplos CTAs dividem atenção. Considere deixar apenas 1 primário"})
    else:
        breakdown.append({"type": "negative", "msg": "Sem CTA identificado — e-mail sem ação definida tende a ter CLTK próximo de zero"})

    # Copy length vs category
    if email_category in ("Conversao", "Pre-vendas"):
        if word_count <= 150:
            points += 6
            breakdown.append({"type": "positive", "msg": f"{word_count} palavras — copy curta para Conversão (+6 pts). Plain text curto supera visual longo."})
        elif word_count > 300:
            breakdown.append({"type": "warning", "msg": f"{word_count} palavras — copy longa para e-mail de Conversão. Considere reduzir e focar no CTA."})
        else:
            points += 3
            breakdown.append({"type": "neutral", "msg": f"{word_count} palavras — comprimento aceitável"})
    elif email_category == "Nutricao":
        if 100 <= word_count <= 400:
            points += 5
            breakdown.append({"type": "positive", "msg": f"{word_count} palavras — comprimento ideal para Nutrição (+5 pts)"})
        elif word_count > 600:
            breakdown.append({"type": "warning", "msg": f"{word_count} palavras — muito longo. Considere resumir ou criar uma série."})
        else:
            points += 3

    # Opening with pain/context
    first_sentence = b[:200].lower()
    pain_kws = ["gestor", "frota", "custo", "problema", "desafio", "dificuldade",
                "você já", "voce ja", "quantas vezes", "imagine", "e se você",
                "manager", "fleet", "challenge", "problem", "have you ever"]
    if any(k in first_sentence for k in pain_kws):
        points += 5
        breakdown.append({"type": "positive", "msg": "Abertura contextualiza dor/cenário do leitor (+5 pts)"})

    # Concrete data/numbers
    if re.search(r'\d+%|\d+x|\d+ vezes|r\$\s*\d+|\$\s*\d+|\d+ km|\d+\s*min', bl):
        points += 4
        breakdown.append({"type": "positive", "msg": "Usa dados ou números concretos (+4 pts) — aumenta credibilidade"})

    # Personalization tokens
    if re.search(r'\{\{.*?\}\}|\[nome\]|\[name\]|\bgestor\b|\bmanager\b', bl):
        points += 3
        breakdown.append({"type": "positive", "msg": "Tem token de personalização (+3 pts)"})

    # Paragraph structure
    line_breaks = b.count("\n")
    if line_breaks >= 3 and word_count > 50:
        points += 3
        breakdown.append({"type": "positive", "msg": "Boa estrutura visual com parágrafos curtos (+3 pts)"})
    elif word_count > 100 and line_breaks < 2:
        breakdown.append({"type": "warning", "msg": "Texto corrido sem quebras — parágrafos curtos melhoram leitura em mobile"})

    # Spam triggers
    spam_kws = ["grátis", "gratis", "clique aqui", "urgente!", "promoção exclusiva",
                "oferta imperdível", "100% garantido", "free!", "click here", "act now"]
    found_spam = [k for k in spam_kws if k in bl]
    if found_spam:
        points -= 5
        breakdown.append({"type": "negative", "msg": f"Termos que ativam filtros de spam: {', '.join(found_spam)} (-5 pts)"})

    points = max(0, min(30, points))
    return {"points": points, "max": 30, "word_count": word_count, "breakdown": breakdown}


# ── Performance estimation ─────────────────────────────────────────────────────

def estimate_performance(total_score: int, segment: str, theme_key: str, email_category: str) -> dict:
    benchmarks  = get_effective_segment_benchmarks()
    bench_seg   = benchmarks.get(segment, SEGMENT_BENCHMARKS["Geral"])
    bench_theme = THEME_BENCHMARKS.get(theme_key, THEME_BENCHMARKS["general"])

    score_ratio  = (total_score - 50) / 50
    abertura_adj = bench_seg["abertura"] * (1 + score_ratio * 0.25)
    abertura     = round(max(5, min(65, abertura_adj)), 1)

    base_cltk = (bench_seg["cltk"] * 0.5 + bench_theme["cltk"] * 0.5)
    cltk_adj  = base_cltk * (1 + score_ratio * 0.4)
    cltk      = round(max(0.1, min(15, cltk_adj)), 2)

    taxa_clique = round(cltk * abertura / 100, 2)

    return {
        "abertura_estimada":    abertura,
        "cltk_estimado":        cltk,
        "taxa_clique_estimada": taxa_clique,
        "benchmark_abertura":   bench_seg["abertura"],
        "benchmark_cltk":       bench_seg["cltk"],
    }


# ── Rule-based suggestions ─────────────────────────────────────────────────────

def generate_rule_suggestions(subject_result, theme_result, segment_result, copy_result,
                               segment, theme_key, email_category) -> list:
    suggestions = []

    # Subject
    if subject_result["points"] < 15:
        if theme_key == "trends_tech":
            suggestions.append({
                "area": "Assunto", "priority": "alta",
                "suggestion": "Ancore IA/tendências em um resultado concreto. Ex: em vez de 'O futuro da gestão com IA', tente 'Como a IA já está reduzindo custo da sua operação'."
            })
        elif theme_key == "security":
            suggestions.append({
                "area": "Assunto", "priority": "alta",
                "suggestion": "Para segurança, mencione o benefício tangível: 'Reduza acidentes em X%' ou 'Seu painel agora alerta para fadiga do motorista'. Específico converte mais que genérico."
            })
        else:
            suggestions.append({
                "area": "Assunto", "priority": "alta",
                "suggestion": "Adicione especificidade ao assunto. Os e-mails com maior CLTK em B2B mencionam diretamente produto, novidade ou melhoria. Ex: 'Novidade: [feature] já disponível para você'."
            })

    if any(b["msg"].startswith("Padrão [Guia]") for b in subject_result["breakdown"]):
        suggestions.append({
            "area": "Assunto", "priority": "alta",
            "suggestion": "Remova o prefixo [Guia] ou [Ebook] do assunto. Esse padrão tende a gerar abertura alta mas CLTK muito baixo — o público abre mas não clica."
        })

    # Theme
    if theme_key == "people_hr":
        suggestions.append({
            "area": "Tema", "priority": "média",
            "suggestion": "Pessoas/RH tem o menor CLTK típico. Considere enquadrar o conteúdo pela lente do gestor de operações: 'Como treinar sua equipe usando dados do painel' performa melhor que conteúdo genérico de RH."
        })
    elif theme_key == "trends_tech":
        suggestions.append({
            "area": "Tema", "priority": "média",
            "suggestion": "IA/Tendências gera abertura alta mas CLTK baixo. O público se interessa mas não age. Combine com novidade de produto: 'Veja como a IA já funciona no seu painel hoje'."
        })

    # Segment
    if segment == "Prospects":
        suggestions.append({
            "area": "Segmento", "priority": "alta",
            "suggestion": "Para Prospects, newsletter padrão tem CLTK muito baixo. Considere e-mail mais curto (< 150 palavras) com 1 CTA único e direto para demo ou trial."
        })
    elif segment == "Lost":
        suggestions.append({
            "area": "Segmento", "priority": "média",
            "suggestion": "Para Lost, foque em reativação pontual — uma oferta específica ou novidade de produto que resolva o motivo do churn. Newsletter padrão tem baixa adesão nesse segmento."
        })

    # Copy
    if not any(b["msg"].startswith("Tem CTA") for b in copy_result["breakdown"]):
        suggestions.append({
            "area": "Copy", "priority": "alta",
            "suggestion": "Adicione um CTA claro. Sem CTA, o CLTK tende a zero. Para Conversão: botão direto ('Ver demonstração'). Para Nutrição: link contextual no texto ('veja como funciona')."
        })

    if copy_result["word_count"] > 400 and email_category == "Conversao":
        suggestions.append({
            "area": "Copy", "priority": "média",
            "suggestion": f"Copy com {copy_result['word_count']} palavras para e-mail de Conversão. Plain text curto (< 200 palavras) supera formato longo para Conversão. Corte ao essencial e confie no CTA."
        })

    if not suggestions:
        suggestions.append({
            "area": "Geral", "priority": "baixa",
            "suggestion": "E-mail bem estruturado. Para garantir o topo do ranking, verifique se o assunto menciona uma novidade ou melhoria concreta do produto — esse é o padrão consistente nos e-mails com maior CLTK em B2B."
        })

    return suggestions


# ── Main function ──────────────────────────────────────────────────────────────

def score_email(subject: str, body: str, segment: str, email_category: str,
                has_cta: bool = True, cta_count: int = 1,
                preheader: str = "") -> dict:

    theme_key = classify_theme(subject, body)

    s_subject = score_subject(subject)
    s_theme   = score_theme(theme_key)
    s_segment = score_segment(segment, email_category)
    s_copy    = score_copy(body, email_category, has_cta, cta_count)

    total = min(100, s_subject["points"] + s_theme["points"] + s_segment["points"] + s_copy["points"])

    if total >= 80:
        rating, rating_color = "Excelente", "green"
        rating_desc = "E-mail com alto potencial de engajamento."
    elif total >= 60:
        rating, rating_color = "Bom", "blue"
        rating_desc = "E-mail sólido com espaço para melhorias pontuais."
    elif total >= 40:
        rating, rating_color = "Regular", "yellow"
        rating_desc = "Alguns ajustes podem aumentar significativamente o engajamento."
    else:
        rating, rating_color = "Precisa de revisão", "red"
        rating_desc = "Pontos críticos identificados — recomendado revisar antes de enviar."

    performance = estimate_performance(total, segment, theme_key, email_category)
    suggestions = generate_rule_suggestions(s_subject, s_theme, s_segment, s_copy,
                                            segment, theme_key, email_category)

    # Preheader check
    if not preheader.strip():
        preheader_feedback = {
            "type": "warning",
            "msg": "Pré-header não informado. Aparece após o assunto na caixa de entrada e pode aumentar a abertura em até 10%. Recomendado: 40–90 caracteres complementando o assunto."
        }
    elif len(preheader) > 90:
        preheader_feedback = {
            "type": "warning",
            "msg": f"Pré-header com {len(preheader)} caracteres — pode ser truncado. Ideal: até 90 caracteres."
        }
    else:
        preheader_feedback = {
            "type": "positive",
            "msg": f"Pré-header presente ({len(preheader)} chars) — boa prática."
        }

    benchmarks = get_effective_segment_benchmarks()

    return {
        "total_score":   total,
        "rating":        rating,
        "rating_color":  rating_color,
        "rating_desc":   rating_desc,
        "dimensions": {
            "subject": s_subject,
            "theme":   s_theme,
            "segment": s_segment,
            "copy":    s_copy,
        },
        "theme_key":          theme_key,
        "theme_label":        s_theme["theme_label"],
        "theme_cltk":         s_theme["theme_cltk"],
        "performance":        performance,
        "suggestions":        suggestions,
        "preheader_feedback": preheader_feedback,
        "segment_label":      benchmarks.get(segment, {}).get("label", segment),
    }
