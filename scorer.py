"""
Motor de scoring de e-mails — Cobli Email Validator
Baseado na análise de 2.013 e-mails HubSpot (2022–2026)
"""

import re
import math

# ─────────────────────────────────────────────────────────────────────────────
# BENCHMARKS HISTÓRICOS (extraídos da análise real)
# ─────────────────────────────────────────────────────────────────────────────

SEGMENT_BENCHMARKS = {
    "Clientes":  {"abertura": 29.6, "cltk": 3.22, "label": "Clientes ativos"},
    "MQL+":      {"abertura": 33.0, "cltk": 2.03, "label": "MQL+ (leads quentes)"},
    "MQL-":      {"abertura": 28.9, "cltk": 1.32, "label": "MQL- (leads frios)"},
    "Lost":      {"abertura": 17.9, "cltk": 0.97, "label": "Lost / Churn"},
    "Prospects": {"abertura": 37.6, "cltk": 0.84, "label": "Prospects (novo)"},
    "Geral":     {"abertura": 34.2, "cltk": 1.74, "label": "Base geral / Newsletter"},
}

THEME_BENCHMARKS = {
    "novidades_produto":   {"cltk": 4.42, "label": "Novidades do Painel / Produto"},
    "custo_eficiencia":    {"cltk": 1.66, "label": "Custo / Eficiência / ROI"},
    "cobli_cam":           {"cltk": 1.33, "label": "Cobli Cam"},
    "logistica":           {"cltk": 1.29, "label": "Logística / Field / Rotas"},
    "ia_tendencias":       {"cltk": 1.21, "label": "IA / Tendências / Tecnologia"},
    "seguranca":           {"cltk": 1.20, "label": "Segurança / Maio Amarelo"},
    "gestao_pessoas":      {"cltk": 0.93, "label": "Gestão de Pessoas / RH"},
    "geral":               {"cltk": 1.50, "label": "Geral / Editorial"},
}

CATEGORY_BENCHMARKS = {
    "Agradecimento": {"cltk": 46.6, "abertura": 60.8},
    "Nutricao":      {"cltk": 8.0,  "abertura": 40.0},
    "Conversao":     {"cltk": 3.5,  "abertura": 30.0},
    "Newsletter":    {"cltk": 1.74, "abertura": 34.2},
    "Pre-vendas":    {"cltk": 5.0,  "abertura": 35.0},
}

# ─────────────────────────────────────────────────────────────────────────────
# CLASSIFICAÇÃO DE TEMA (pelo assunto)
# ─────────────────────────────────────────────────────────────────────────────

def classify_theme(subject: str, body: str = "") -> str:
    text = (subject + " " + body).lower()

    if any(k in text for k in ["painel", "plataforma", "dashboard", "novidade no painel",
                                "melhoria", "atualização", "lançamento", "funcionalidade",
                                "nova feature", "novo recurso", "app do gestor", "melhoramos"]):
        return "novidades_produto"
    if any(k in text for k in ["custo", "combustível", "combustivel", "economia", "eficiência",
                                "eficiencia", "roi", "lucro", "reduzir gastos", "economizar"]):
        return "custo_eficiencia"
    if any(k in text for k in ["cam", "câmera", "camera", "cobli cam", "câmera de ré"]):
        return "cobli_cam"
    if any(k in text for k in ["segurança", "seguranca", "acidente", "maio amarelo",
                                "prevenção", "prevencao", "motorista", "risco", "fadiga"]):
        return "seguranca"
    if any(k in text for k in ["ia", "inteligência artificial", "inteligencia artificial",
                                "automação", "automacao", "tendência", "tendencia",
                                "tecnologia", "digital", "futuro"]):
        return "ia_tendencias"
    if any(k in text for k in ["gestão de pessoa", "gestao de pessoa", "rh", "equipe",
                                "time", "colaborador", "funcionário", "funcionario"]):
        return "gestao_pessoas"
    if any(k in text for k in ["logística", "logistica", "entrega", "field", "campo",
                                "rota", "roteirização", "roteirizacao"]):
        return "logistica"
    return "geral"

# ─────────────────────────────────────────────────────────────────────────────
# SCORE DO ASSUNTO (0–30 pts)
# ─────────────────────────────────────────────────────────────────────────────

def score_subject(subject: str) -> dict:
    s = subject.strip()
    sl = s.lower()
    points = 0
    breakdown = []

    # Keywords de produto de alto impacto
    product_kws = ["painel", "novidade", "novidades", "melhoria", "melhorias",
                   "lançamento", "lancamento", "atualização", "atualizacao",
                   "app do gestor", "nova feature", "melhoramos", "implementamos"]
    if any(k in sl for k in product_kws):
        points += 10
        breakdown.append({"type": "positive", "msg": "Menciona produto/painel diretamente (+10 pts) — padrão dos melhores CLTKs históricos"})

    # Benefício concreto
    benefit_kws = ["reduzir", "economizar", "aumentar", "melhorar", "otimizar",
                   "evitar", "resolver", "facilitar", "transformar", "descobrir"]
    if any(k in sl for k in benefit_kws):
        points += 6
        breakdown.append({"type": "positive", "msg": "Contém verbo de benefício concreto (+6 pts)"})

    # Emoji
    emoji_count = len(re.findall(r'[\U00010000-\U0010ffff]|[☀-⟿]', s))
    if 1 <= emoji_count <= 2:
        points += 4
        breakdown.append({"type": "positive", "msg": f"{emoji_count} emoji(s) — uso adequado (+4 pts)"})
    elif emoji_count > 3:
        points -= 2
        breakdown.append({"type": "warning", "msg": f"{emoji_count} emojis — excesso pode prejudicar deliverability (-2 pts)"})

    # Comprimento ideal
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

    # Personalização (Gestor, Você)
    if re.search(r'\bgestor\b|\bvocê\b|\bseu\b|\bsua\b', sl):
        points += 3
        breakdown.append({"type": "positive", "msg": "Usa linguagem direta/personalizada (+3 pts)"})

    # Padrões que não funcionam
    guia_pattern = re.search(r'\[guia\]|\[ebook\]|\[webinar\]|\[material\]', sl)
    if guia_pattern:
        points -= 8
        breakdown.append({"type": "negative", "msg": "Padrão [Guia]/[Ebook] — historicamente gera abertura alta mas CLTK muito baixo (-8 pts). Considere remover o prefixo."})

    vague_kws = ["você sabia", "voce sabia", "descubra como", "tudo sobre",
                 "tendências de", "o futuro de", "entenda como a tecnologia"]
    if any(k in sl for k in vague_kws):
        points -= 5
        breakdown.append({"type": "negative", "msg": "Assunto vago/curiosidade sem especificidade (-5 pts) — promete mas não entrega contexto"})

    # Caps excessivo
    upper_ratio = sum(1 for c in s if c.isupper()) / max(len(s), 1)
    if upper_ratio > 0.4:
        points -= 3
        breakdown.append({"type": "warning", "msg": "Excesso de letras maiúsculas — pode ativar filtros de spam (-3 pts)"})

    points = max(0, min(30, points))
    return {"points": points, "max": 30, "breakdown": breakdown}

# ─────────────────────────────────────────────────────────────────────────────
# SCORE DO TEMA (0–20 pts)
# ─────────────────────────────────────────────────────────────────────────────

def score_theme(theme_key: str) -> dict:
    benchmark = THEME_BENCHMARKS.get(theme_key, THEME_BENCHMARKS["geral"])
    max_cltk = 4.42  # novidades_produto
    ratio = benchmark["cltk"] / max_cltk
    points = round(ratio * 20)
    breakdown = []

    if theme_key == "novidades_produto":
        breakdown.append({"type": "positive", "msg": f"Tema de maior CLTK histórico (4,42%) — as 10 edições com maior engajamento são todas de produto (+{points} pts)"})
    elif theme_key in ("ia_tendencias", "seguranca", "gestao_pessoas"):
        breakdown.append({"type": "warning", "msg": f"Tema de CLTK moderado/baixo ({benchmark['cltk']}%). Considere ancorar em funcionalidade do produto para aumentar relevância (+{points} pts)"})
    else:
        breakdown.append({"type": "neutral", "msg": f"Tema com CLTK histórico de {benchmark['cltk']}% (+{points} pts)"})

    return {"points": points, "max": 20, "theme": theme_key,
            "theme_label": benchmark["label"], "theme_cltk": benchmark["cltk"], "breakdown": breakdown}

# ─────────────────────────────────────────────────────────────────────────────
# SCORE DO SEGMENTO (0–20 pts)
# ─────────────────────────────────────────────────────────────────────────────

def score_segment(segment: str, email_category: str) -> dict:
    bench = SEGMENT_BENCHMARKS.get(segment, SEGMENT_BENCHMARKS["Geral"])
    breakdown = []
    points = 10  # base

    if segment == "Clientes":
        points = 18
        breakdown.append({"type": "positive", "msg": "Clientes têm o melhor CLTK (3,22%) — este é o segmento ideal para newsletter e conteúdo de produto"})
    elif segment == "MQL+":
        points = 14
        breakdown.append({"type": "positive", "msg": "MQL+ tem boa resposta (2,03% CLTK) — conteúdo pode acelerar conversão"})
    elif segment == "MQL-":
        points = 10
        breakdown.append({"type": "neutral", "msg": "MQL- tem CLTK médio (1,32%) — conteúdo mais direto e com CTA único tende a performar melhor"})
    elif segment == "Lost":
        points = 7
        breakdown.append({"type": "warning", "msg": "Lost tem abertura baixa (17,9%) e CLTK de 0,97% — recomendado fluxo de reativação específico, não newsletter padrão"})
    elif segment == "Prospects":
        points = 5
        breakdown.append({"type": "negative", "msg": "Prospects abrem (37,6%) mas não clicam (0,84% CLTK). Newsletter padrão não converte para esse público. Considere e-mail mais curto com 1 CTA direto."})
    else:
        points = 10
        breakdown.append({"type": "neutral", "msg": f"Base geral — CLTK histórico de {bench['cltk']}%"})

    # Cruzamento categoria × segmento
    if email_category == "Conversao" and segment == "Prospects":
        breakdown.append({"type": "warning", "msg": "E-mail de Conversão para Prospects: histórico mostra que plain text supera formato visual para esse público"})
    if email_category == "Newsletter" and segment == "Prospects":
        points -= 2
        breakdown.append({"type": "negative", "msg": "Newsletter para Prospects: CLTK historicamente 0,84% — resultado muito abaixo dos outros segmentos"})

    points = max(0, min(20, points))
    return {"points": points, "max": 20, "breakdown": breakdown,
            "benchmark_abertura": bench["abertura"], "benchmark_cltk": bench["cltk"]}

# ─────────────────────────────────────────────────────────────────────────────
# SCORE DA COPY (0–30 pts)
# ─────────────────────────────────────────────────────────────────────────────

def score_copy(body: str, email_category: str, has_cta: bool, cta_count: int) -> dict:
    points = 0
    breakdown = []
    b = body.strip()
    bl = b.lower()
    word_count = len(b.split())

    # CTA
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

    # Comprimento da copy
    if email_category in ("Conversao", "Pre-vendas"):
        if word_count <= 150:
            points += 6
            breakdown.append({"type": "positive", "msg": f"{word_count} palavras — copy curta para Conversão (+6 pts). Dados mostram que plain text curto supera visual longo"})
        elif word_count > 300:
            breakdown.append({"type": "warning", "msg": f"{word_count} palavras — copy longa para e-mail de Conversão. Considere reduzir e focar no CTA"})
        else:
            points += 3
            breakdown.append({"type": "neutral", "msg": f"{word_count} palavras — comprimento aceitável"})
    elif email_category == "Nutricao":
        if 100 <= word_count <= 400:
            points += 5
            breakdown.append({"type": "positive", "msg": f"{word_count} palavras — comprimento ideal para Nutrição (+5 pts)"})
        elif word_count > 600:
            breakdown.append({"type": "warning", "msg": f"{word_count} palavras — muito longo para e-mail. Considere resumir ou criar uma série"})
        else:
            points += 3

    # Abertura com dor/contexto
    first_sentence = b[:200].lower()
    pain_kws = ["gestor", "frota", "custo", "problema", "desafio", "dificuldade",
                "você já", "voce ja", "quantas vezes", "imagine", "e se você"]
    if any(k in first_sentence for k in pain_kws):
        points += 5
        breakdown.append({"type": "positive", "msg": "Abertura contextualiza dor/cenário do gestor (+5 pts)"})

    # Dados/números concretos
    if re.search(r'\d+%|\d+x|\d+ vezes|r\$\s*\d+|\d+ km', bl):
        points += 4
        breakdown.append({"type": "positive", "msg": "Usa dados ou números concretos (+4 pts) — aumenta credibilidade"})

    # Personalização
    if re.search(r'\{\{.*?\}\}|\[nome\]|\bgestor\b', bl):
        points += 3
        breakdown.append({"type": "positive", "msg": "Tem token de personalização (+3 pts)"})

    # Parágrafos curtos (heurística: muitas quebras de linha)
    line_breaks = b.count("\n")
    if line_breaks >= 3 and word_count > 50:
        points += 3
        breakdown.append({"type": "positive", "msg": "Boa estrutura visual com parágrafos curtos (+3 pts)"})
    elif word_count > 100 and line_breaks < 2:
        breakdown.append({"type": "warning", "msg": "Texto corrido sem quebras — parágrafos curtos melhoram leitura em mobile"})

    # Spam triggers
    spam_kws = ["grátis", "gratis", "clique aqui", "urgente!", "promoção exclusiva",
                "oferta imperdível", "100% garantido"]
    found_spam = [k for k in spam_kws if k in bl]
    if found_spam:
        points -= 5
        breakdown.append({"type": "negative", "msg": f"Termos que ativam filtros de spam: {', '.join(found_spam)} (-5 pts)"})

    points = max(0, min(30, points))
    return {"points": points, "max": 30, "word_count": word_count, "breakdown": breakdown}

# ─────────────────────────────────────────────────────────────────────────────
# ESTIMATIVAS DE PERFORMANCE
# ─────────────────────────────────────────────────────────────────────────────

def estimate_performance(total_score: int, segment: str, theme_key: str, email_category: str) -> dict:
    bench_seg = SEGMENT_BENCHMARKS.get(segment, SEGMENT_BENCHMARKS["Geral"])
    bench_theme = THEME_BENCHMARKS.get(theme_key, THEME_BENCHMARKS["geral"])

    # Abertura: benchmark do segmento ± ajuste pelo score total
    score_ratio = (total_score - 50) / 50  # -1 a +1
    abertura_adj = bench_seg["abertura"] * (1 + score_ratio * 0.25)
    abertura = round(max(5, min(65, abertura_adj)), 1)

    # CLTK: média ponderada entre benchmark de segmento e de tema, ajustada pelo score
    base_cltk = (bench_seg["cltk"] * 0.5 + bench_theme["cltk"] * 0.5)
    cltk_adj = base_cltk * (1 + score_ratio * 0.4)
    cltk = round(max(0.1, min(15, cltk_adj)), 2)

    # Taxa de clique = CLTK × abertura / 100
    taxa_clique = round(cltk * abertura / 100, 2)

    return {
        "abertura_estimada": abertura,
        "cltk_estimado": cltk,
        "taxa_clique_estimada": taxa_clique,
        "benchmark_abertura": bench_seg["abertura"],
        "benchmark_cltk": bench_seg["cltk"],
    }

# ─────────────────────────────────────────────────────────────────────────────
# SUGESTÕES BASEADAS EM REGRAS (fallback sem API)
# ─────────────────────────────────────────────────────────────────────────────

def generate_rule_suggestions(subject_result, theme_result, segment_result, copy_result,
                               segment, theme_key, email_category) -> list:
    suggestions = []

    # Assunto
    if subject_result["points"] < 15:
        if theme_key == "ia_tendencias":
            suggestions.append({
                "area": "Assunto",
                "priority": "alta",
                "suggestion": "Ancore IA/tendências em uma funcionalidade concreta do Painel Cobli. Ex: em vez de 'O futuro da gestão com IA', tente 'Como a IA do Painel Cobli já está reduzindo custo da sua frota'."
            })
        elif theme_key == "seguranca":
            suggestions.append({
                "area": "Assunto",
                "priority": "alta",
                "suggestion": "Para segurança, mencione o benefício tangível: 'Reduza acidentes em X%' ou 'Seu painel Cobli agora alerta para fadiga do motorista'. Específico converte mais que genérico."
            })
        else:
            suggestions.append({
                "area": "Assunto",
                "priority": "alta",
                "suggestion": "Adicione especificidade ao assunto. Os 10 e-mails com maior CLTK histórico mencionam diretamente 'Painel', 'novidade' ou 'melhoria'. Ex: 'Novidade no Painel: [funcionalidade] já disponível para você'."
            })

    has_guia = any(b["msg"].startswith("Padrão [Guia]") for b in subject_result["breakdown"])
    if has_guia:
        suggestions.append({
            "area": "Assunto",
            "priority": "alta",
            "suggestion": "Remova o prefixo [Guia] ou [Ebook] do assunto. Esses padrões historicamente têm abertura alta mas CLTK muito baixo — o público abre mas não clica no conteúdo."
        })

    # Tema
    if theme_key == "gestao_pessoas":
        suggestions.append({
            "area": "Tema",
            "priority": "média",
            "suggestion": "Gestão de pessoas tem o menor CLTK histórico (0,93%). Considere enquadrar o conteúdo pela lente do gestor de frota: 'Como treinar motoristas usando dados do Painel' performa melhor que conteúdo genérico de RH."
        })
    elif theme_key == "ia_tendencias":
        suggestions.append({
            "area": "Tema",
            "priority": "média",
            "suggestion": "IA/Tendências gera abertura alta (36,3%) mas CLTK baixo (1,21%). O público se interessa pelo tema mas não age. Combine com novidade de produto: 'Veja como a IA do Cobli já funciona no seu Painel'."
        })

    # Segmento
    if segment == "Prospects":
        suggestions.append({
            "area": "Segmento",
            "priority": "alta",
            "suggestion": "Para Prospects, a newsletter padrão tem CLTK histórico de apenas 0,84%. Considere um e-mail mais curto (< 150 palavras), com 1 CTA único e direto para demo ou trial, ao invés de newsletter editorial."
        })
    elif segment == "Lost":
        suggestions.append({
            "area": "Segmento",
            "priority": "média",
            "suggestion": "Para Lost, foque em reativação pontual — uma oferta específica ou novidade de produto que resolva o motivo do churn. Newsletter padrão tem baixa adesão nesse segmento (abertura 17,9%)."
        })

    # Copy
    no_cta = not any(b["msg"].startswith("Tem CTA") for b in copy_result["breakdown"])
    if no_cta:
        suggestions.append({
            "area": "Copy",
            "priority": "alta",
            "suggestion": "Adicione um CTA claro. Sem CTA, o CLTK tende a zero. Para Conversão: botão direto ('Ver demonstração'). Para Nutrição: link contextual no texto ('veja como funciona no Painel')."
        })

    if copy_result["word_count"] > 400 and email_category == "Conversao":
        suggestions.append({
            "area": "Copy",
            "priority": "média",
            "suggestion": f"Copy com {copy_result['word_count']} palavras para e-mail de Conversão. Os dados mostram que plain text curto (< 200 palavras) supera formato longo para Conversão. Corte ao essencial e confie no CTA."
        })

    if not suggestions:
        suggestions.append({
            "area": "Geral",
            "priority": "baixa",
            "suggestion": "E-mail bem estruturado. Para garantir o topo do ranking, verifique se o assunto menciona uma novidade ou melhoria concreta do produto — esse é o padrão consistente nos e-mails com maior CLTK histórico."
        })

    return suggestions

# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÃO PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def score_email(subject: str, body: str, segment: str, email_category: str,
                has_cta: bool = True, cta_count: int = 1,
                preheader: str = "") -> dict:

    theme_key = classify_theme(subject, body)

    s_subject = score_subject(subject)
    s_theme   = score_theme(theme_key)
    s_segment = score_segment(segment, email_category)
    s_copy    = score_copy(body, email_category, has_cta, cta_count)

    total = s_subject["points"] + s_theme["points"] + s_segment["points"] + s_copy["points"]
    total = min(100, total)

    if total >= 80:
        rating = "Excelente"
        rating_color = "green"
        rating_desc = "E-mail com alto potencial de performance para a base Cobli."
    elif total >= 60:
        rating = "Bom"
        rating_color = "blue"
        rating_desc = "E-mail sólido com espaço para melhorias pontuais."
    elif total >= 40:
        rating = "Regular"
        rating_color = "yellow"
        rating_desc = "Alguns ajustes podem aumentar significativamente o engajamento."
    else:
        rating = "Precisa de revisão"
        rating_color = "red"
        rating_desc = "Pontos críticos identificados — recomendado revisar antes de enviar."

    performance = estimate_performance(total, segment, theme_key, email_category)
    suggestions = generate_rule_suggestions(s_subject, s_theme, s_segment, s_copy,
                                            segment, theme_key, email_category)

    # Preheader analysis
    preheader_feedback = None
    if not preheader.strip():
        preheader_feedback = {
            "type": "warning",
            "msg": "Pré-header não informado. O pré-header aparece logo após o assunto na caixa de entrada e aumenta a taxa de abertura em até 10%. Recomendado complementar o assunto com 40–90 caracteres."
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

    return {
        "total_score": total,
        "rating": rating,
        "rating_color": rating_color,
        "rating_desc": rating_desc,
        "dimensions": {
            "subject":  s_subject,
            "theme":    s_theme,
            "segment":  s_segment,
            "copy":     s_copy,
        },
        "theme_key":   theme_key,
        "theme_label": s_theme["theme_label"],
        "theme_cltk":  s_theme["theme_cltk"],
        "performance": performance,
        "suggestions": suggestions,
        "preheader_feedback": preheader_feedback,
        "segment_label": SEGMENT_BENCHMARKS.get(segment, {}).get("label", segment),
    }
