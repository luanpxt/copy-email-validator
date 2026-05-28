"""
Email Validator — Scoring Engine
Scores against learned cluster benchmarks when data is available,
falls back to generic industry averages otherwise.
"""

import re

# ── Fallback benchmarks (used when no data has been imported) ─────────────────
FALLBACK_BENCHMARKS = {
    "abertura": 25.0,
    "cltk":      1.5,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _count_emojis(text: str) -> int:
    return len(re.findall(r'[\U00010000-\U0010ffff]|[☀-⟿]', text or ""))

def _word_count(text: str) -> int:
    return len((text or "").split())

def _get_cluster(cluster_data: dict, segment: str, category: str):
    if not cluster_data or not cluster_data.get("clusters"):
        return None
    return cluster_data["clusters"].get(f"{segment}|{category}")


# ── Subject scoring (0–30 pts) ────────────────────────────────────────────────

def score_subject(subject: str, cluster) -> dict:
    s         = subject.strip()
    sl        = s.lower()
    points    = 0
    breakdown = []

    # Length — compare against cluster profile if available
    char_count = len(s)
    if cluster and cluster.get("subject", {}).get("len_p50"):
        p25 = cluster["subject"].get("len_p25", 30)
        p50 = cluster["subject"].get("len_p50", 55)
        p75 = cluster["subject"].get("len_p75", 80)
        if p25 <= char_count <= p75:
            points += 7
            breakdown.append({"type": "positive", "msg": f"{char_count} chars — dentro da faixa do seu cluster (p25={p25:.0f}–p75={p75:.0f}) (+7 pts)"})
        else:
            direction = "curto" if char_count < p25 else "longo"
            ref = p25 if char_count < p25 else p75
            points += 2
            breakdown.append({"type": "warning", "msg": f"{char_count} chars — muito {direction} para o cluster (referência p50={p50:.0f})"})
    else:
        if 35 <= char_count <= 80:
            points += 7
            breakdown.append({"type": "positive", "msg": f"{char_count} chars — comprimento ideal 35–80 (+7 pts)"})
        elif char_count < 20:
            points -= 2
            breakdown.append({"type": "negative", "msg": f"Muito curto ({char_count} chars) (-2 pts)"})
        elif char_count > 100:
            points -= 3
            breakdown.append({"type": "negative", "msg": f"Muito longo ({char_count} chars) — pode ser truncado em mobile (-3 pts)"})
        else:
            points += 3
            breakdown.append({"type": "neutral", "msg": f"{char_count} chars — aceitável, ideal é 35–80"})

    # Emojis — compare against cluster if available
    emoji_count = _count_emojis(s)
    if cluster and cluster.get("subject", {}).get("emoji_p50") is not None:
        expected = cluster["subject"]["emoji_p50"]
        if abs(emoji_count - expected) <= 1:
            points += 4
            breakdown.append({"type": "positive", "msg": f"{emoji_count} emoji(s) — alinhado com a média do cluster ({expected:.1f}) (+4 pts)"})
        elif emoji_count > expected + 2:
            points -= 2
            breakdown.append({"type": "warning", "msg": f"{emoji_count} emojis — acima da média do cluster ({expected:.1f})"})
        else:
            points += 2
            breakdown.append({"type": "neutral", "msg": f"{emoji_count} emoji(s)"})
    else:
        if 1 <= emoji_count <= 2:
            points += 4
            breakdown.append({"type": "positive", "msg": f"{emoji_count} emoji(s) — uso adequado (+4 pts)"})
        elif emoji_count > 3:
            points -= 2
            breakdown.append({"type": "warning", "msg": f"{emoji_count} emojis — excesso pode prejudicar deliverability"})

    # Benefit verb
    benefit_kws = ["reduzir", "economizar", "aumentar", "melhorar", "otimizar",
                   "evitar", "resolver", "facilitar", "transformar", "descobrir",
                   "ganhar", "garantir", "acelerar",
                   "reduce", "save", "increase", "improve", "optimize", "solve"]
    if any(k in sl for k in benefit_kws):
        points += 6
        breakdown.append({"type": "positive", "msg": "Verbo de benefício concreto (+6 pts)"})

    # Direct/personalized language
    if re.search(r'\bvocê\b|\byour\b|\byou\b|\bseu\b|\bsua\b', sl):
        points += 3
        breakdown.append({"type": "positive", "msg": "Linguagem direta/personalizada (+3 pts)"})

    # Patterns that underperform
    if re.search(r'\[guia\]|\[ebook\]|\[webinar\]|\[material\]|\[guide\]|\[report\]', sl):
        points -= 8
        breakdown.append({"type": "negative", "msg": "Padrão [Guia]/[Ebook] — abertura alta mas CLTK baixo (-8 pts)"})

    vague_kws = ["você sabia", "voce sabia", "descubra como", "tudo sobre",
                 "tendências de", "o futuro de", "did you know", "everything about"]
    if any(k in sl for k in vague_kws):
        points -= 4
        breakdown.append({"type": "negative", "msg": "Assunto vago sem especificidade (-4 pts)"})

    if sum(1 for c in s if c.isupper()) / max(len(s), 1) > 0.4:
        points -= 3
        breakdown.append({"type": "warning", "msg": "Excesso de maiúsculas — pode ativar filtros de spam (-3 pts)"})

    spam_kws = ["grátis", "gratis", "urgente!", "promoção exclusiva", "oferta imperdível",
                "100% garantido", "free!", "click here", "act now"]
    found = [k for k in spam_kws if k in sl]
    if found:
        points -= 4
        breakdown.append({"type": "negative", "msg": f"Termos de spam: {', '.join(found)} (-4 pts)"})

    return {"points": max(0, min(30, points)), "max": 30, "breakdown": breakdown}


# ── Copy scoring (0–30 pts) ───────────────────────────────────────────────────

def score_copy(body: str, cluster) -> dict:
    b          = body.strip()
    bl         = b.lower()
    word_count = _word_count(b)
    points     = 0
    breakdown  = []

    # Word count — compare against cluster profile if available
    if cluster and cluster.get("copy", {}).get("word_p50"):
        p25 = cluster["copy"].get("word_p25", 80)
        p50 = cluster["copy"].get("word_p50", 180)
        p75 = cluster["copy"].get("word_p75", 350)
        if p25 <= word_count <= p75:
            points += 8
            breakdown.append({"type": "positive", "msg": f"{word_count} palavras — dentro da faixa do cluster (p25={p25:.0f}–p75={p75:.0f}) (+8 pts)"})
        elif word_count < p25:
            points += 3
            breakdown.append({"type": "warning", "msg": f"{word_count} palavras — abaixo do p25 ({p25:.0f}) do cluster"})
        else:
            points += 3
            breakdown.append({"type": "warning", "msg": f"{word_count} palavras — acima do p75 ({p75:.0f}) do cluster"})
    else:
        if 80 <= word_count <= 350:
            points += 8
            breakdown.append({"type": "positive", "msg": f"{word_count} palavras — comprimento adequado (+8 pts)"})
        elif word_count < 30:
            points += 1
            breakdown.append({"type": "warning", "msg": f"Copy muito curta ({word_count} palavras)"})
        elif word_count > 600:
            points += 2
            breakdown.append({"type": "warning", "msg": f"Copy longa ({word_count} palavras) — boa estrutura é essencial"})
        else:
            points += 5

    # Concrete data/numbers
    if re.search(r'\d+%|\d+x|\d+ vezes|r\$\s*\d+|\$\s*\d+|\d+\s*min|\d+\s*h\b', bl):
        points += 5
        breakdown.append({"type": "positive", "msg": "Dados ou números concretos (+5 pts) — aumenta credibilidade"})

    # Opening hook
    first = b[:200].lower()
    hook_kws = ["você já", "voce ja", "quantas vezes", "imagine", "e se você",
                "have you ever", "what if", "problema", "desafio", "dificuldade",
                "challenge", "o que seria", "já pensou"]
    if any(k in first for k in hook_kws):
        points += 5
        breakdown.append({"type": "positive", "msg": "Abertura contextualiza cenário/dor do leitor (+5 pts)"})

    # Personalization tokens
    if re.search(r'\{\{.*?\}\}|\[nome\]|\[name\]|\bfirst.?name\b', bl):
        points += 3
        breakdown.append({"type": "positive", "msg": "Token de personalização (+3 pts)"})

    # Paragraph structure
    line_breaks = b.count("\n")
    if line_breaks >= 3 and word_count > 50:
        points += 4
        breakdown.append({"type": "positive", "msg": "Boa estrutura com parágrafos curtos (+4 pts)"})
    elif word_count > 100 and line_breaks < 2:
        breakdown.append({"type": "warning", "msg": "Texto corrido sem quebras — parágrafos curtos melhoram leitura em mobile"})

    # Spam triggers
    spam_kws = ["grátis", "gratis", "clique aqui", "urgente!", "promoção exclusiva",
                "oferta imperdível", "100% garantido", "free!", "click here", "act now"]
    found = [k for k in spam_kws if k in bl]
    if found:
        points -= 5
        breakdown.append({"type": "negative", "msg": f"Termos de spam: {', '.join(found)} (-5 pts)"})

    return {"points": max(0, min(30, points)), "max": 30, "word_count": word_count, "breakdown": breakdown}


# ── Structure scoring (0–20 pts) ─────────────────────────────────────────────

def score_structure(preheader: str, has_cta: bool, cta_count: int,
                    has_hyperlink: bool, hyperlink_count: int, cluster) -> dict:
    points    = 0
    breakdown = []

    # Preheader
    if preheader.strip():
        ph_len = len(preheader)
        if ph_len <= 90:
            points += 5
            breakdown.append({"type": "positive", "msg": f"Pré-header presente ({ph_len} chars) (+5 pts)"})
        else:
            points += 2
            breakdown.append({"type": "warning", "msg": f"Pré-header com {ph_len} chars — pode ser truncado. Ideal: até 90 (+2 pts)"})
    else:
        breakdown.append({"type": "warning", "msg": "Sem pré-header — adicionar pode aumentar abertura em até 10%"})

    # CTA/Button
    cluster_btn_rate = cluster.get("cta", {}).get("button_rate") if cluster else None
    if has_cta:
        if cluster_btn_rate is not None:
            pct = round(cluster_btn_rate * 100)
            if cluster_btn_rate >= 0.5:
                points += 8
                breakdown.append({"type": "positive", "msg": f"Tem botão/CTA — {pct}% dos e-mails do cluster usam botão (+8 pts)"})
            else:
                points += 5
                breakdown.append({"type": "neutral", "msg": f"Tem botão/CTA. Apenas {pct}% do cluster usa botão — avalie se o formato é adequado (+5 pts)"})
        else:
            points += 8
            breakdown.append({"type": "positive", "msg": "Tem botão/CTA (+8 pts)"})

        if cta_count == 1:
            points += 4
            breakdown.append({"type": "positive", "msg": "CTA único — foco claro aumenta taxa de clique (+4 pts)"})
        elif cta_count == 2:
            points += 2
            breakdown.append({"type": "neutral", "msg": "2 CTAs — aceitável, mas 1 único tende a converter melhor (+2 pts)"})
        else:
            breakdown.append({"type": "warning", "msg": f"{cta_count} CTAs — múltiplos CTAs dividem a atenção do leitor"})
    else:
        breakdown.append({"type": "negative", "msg": "Sem botão/CTA — e-mail sem ação definida tende a ter CLTK próximo de zero"})

    # Hyperlinks
    if has_hyperlink:
        points += 3
        if hyperlink_count <= 3:
            breakdown.append({"type": "positive", "msg": f"{hyperlink_count} hiperlink(s) — uso adequado (+3 pts)"})
        else:
            breakdown.append({"type": "warning", "msg": f"{hyperlink_count} hiperlinks — muitos links podem distrair do CTA (+3 pts)"})
        if cluster and cluster.get("cta", {}).get("link_rate") is not None:
            pct = round(cluster["cta"]["link_rate"] * 100)
            breakdown.append({"type": "neutral", "msg": f"{pct}% dos e-mails do cluster também usam hiperlinks"})
    else:
        breakdown.append({"type": "neutral", "msg": "Sem hiperlinks no corpo"})

    return {"points": max(0, min(20, points)), "max": 20, "breakdown": breakdown}


# ── Context/Cluster scoring (0–20 pts) ───────────────────────────────────────

def score_context(segment: str, category: str, cluster,
                  copy_word_count: int, subject_char_count: int) -> dict:
    points    = 0
    breakdown = []

    if not cluster:
        if segment and category:
            points = 10
            breakdown.append({"type": "neutral", "msg": "Segmento e categoria informados (+10 pts). Importe sua base para calibrar com dados reais."})
        elif segment or category:
            points = 6
            breakdown.append({"type": "neutral", "msg": "Segmento ou categoria informado (+6 pts). Importe sua base para calibrar."})
        else:
            points = 3
            breakdown.append({"type": "warning", "msg": "Sem segmento/categoria — selecione para um score mais preciso (+3 pts)"})
        return {"points": points, "max": 20, "has_cluster": False, "breakdown": breakdown}

    total = cluster.get("total", 0)
    if total >= 20:
        points += 8
        breakdown.append({"type": "positive", "msg": f"Cluster com {total} e-mails históricos — boa base de referência (+8 pts)"})
    elif total >= 5:
        points += 5
        breakdown.append({"type": "neutral", "msg": f"Cluster com {total} e-mails — válido, mais dados melhoram a precisão (+5 pts)"})
    else:
        points += 3
        breakdown.append({"type": "warning", "msg": f"Cluster com apenas {total} e-mail(s) — adicione mais dados (+3 pts)"})

    # Copy length alignment
    if cluster.get("copy", {}).get("word_p50"):
        p25 = cluster["copy"].get("word_p25", 0)
        p75 = cluster["copy"].get("word_p75", 9999)
        if p25 <= copy_word_count <= p75:
            points += 6
            breakdown.append({"type": "positive", "msg": "Tamanho da copy alinhado com o padrão do cluster (+6 pts)"})
        else:
            points += 2
            breakdown.append({"type": "warning", "msg": "Tamanho da copy fora da faixa típica do cluster (+2 pts)"})

    # Subject length alignment
    if cluster.get("subject", {}).get("len_p50"):
        p25 = cluster["subject"].get("len_p25", 0)
        p75 = cluster["subject"].get("len_p75", 9999)
        if p25 <= subject_char_count <= p75:
            points += 6
            breakdown.append({"type": "positive", "msg": "Comprimento do assunto alinhado com o padrão do cluster (+6 pts)"})
        else:
            points += 2
            breakdown.append({"type": "warning", "msg": "Comprimento do assunto fora da faixa típica do cluster (+2 pts)"})

    return {
        "points":        max(0, min(20, points)),
        "max":           20,
        "has_cluster":   True,
        "cluster_total": total,
        "breakdown":     breakdown,
    }


# ── Performance estimation ────────────────────────────────────────────────────

def estimate_performance(total_score: int, cluster, global_data: dict) -> dict:
    if cluster:
        base_ab   = cluster["abertura"]["p50"]
        base_cltk = cluster["cltk"]["p50"]
        source    = "cluster"
    elif global_data:
        base_ab   = global_data.get("abertura_p50", FALLBACK_BENCHMARKS["abertura"])
        base_cltk = global_data.get("cltk_p50",    FALLBACK_BENCHMARKS["cltk"])
        source    = "global"
    else:
        base_ab   = FALLBACK_BENCHMARKS["abertura"]
        base_cltk = FALLBACK_BENCHMARKS["cltk"]
        source    = "fallback"

    score_ratio = (total_score - 50) / 50
    abertura    = round(max(5.0,  min(65.0, base_ab   * (1 + score_ratio * 0.25))), 1)
    cltk        = round(max(0.1,  min(15.0, base_cltk * (1 + score_ratio * 0.40))), 2)

    return {
        "abertura_estimada":    abertura,
        "cltk_estimado":        cltk,
        "taxa_clique_estimada": round(cltk * abertura / 100, 2),
        "benchmark_abertura":   base_ab,
        "benchmark_cltk":       base_cltk,
        "source":               source,
    }


# ── Suggestions ───────────────────────────────────────────────────────────────

def generate_suggestions(s_subject, s_copy, s_structure, s_context, cluster) -> list:
    suggestions = []

    if s_subject["points"] < 15:
        suggestions.append({
            "area": "Assunto", "priority": "alta",
            "suggestion": "Adicione especificidade: verbos de benefício concreto ('reduzir', 'aumentar', 'garantir') e comprimento entre 35–80 chars tendem a performar melhor."
        })

    if any("Padrão [Guia]" in b["msg"] for b in s_subject["breakdown"]):
        suggestions.append({
            "area": "Assunto", "priority": "alta",
            "suggestion": "Remova o prefixo [Guia]/[Ebook] — esse padrão gera abertura alta mas CLTK baixo. O público abre por curiosidade mas não clica."
        })

    if cluster and cluster.get("copy", {}).get("word_p75"):
        p75 = cluster["copy"]["word_p75"]
        if s_copy["word_count"] > p75:
            suggestions.append({
                "area": "Copy", "priority": "média",
                "suggestion": f"Sua copy tem {s_copy['word_count']} palavras — acima do p75 do cluster ({p75:.0f}). Considere reduzir e focar no CTA."
            })

    no_cta = not any(
        b["type"] in ("positive", "neutral") and ("CTA" in b["msg"] or "botão" in b["msg"].lower())
        for b in s_structure["breakdown"]
    )
    if no_cta:
        suggestions.append({
            "area": "Estrutura", "priority": "alta",
            "suggestion": "Adicione um CTA claro. Sem ação definida, o CLTK tende a zero."
        })

    no_preheader = not any("Pré-header presente" in b["msg"] for b in s_structure["breakdown"])
    if no_preheader:
        suggestions.append({
            "area": "Estrutura", "priority": "média",
            "suggestion": "Adicione um pré-header de 40–90 chars complementando o assunto. Pode aumentar a taxa de abertura em até 10%."
        })

    if not s_context.get("has_cluster"):
        suggestions.append({
            "area": "Calibração", "priority": "baixa",
            "suggestion": "Importe sua base histórica no Admin para calibrar os benchmarks com dados reais. O score ficará mais preciso."
        })

    if not suggestions:
        suggestions.append({
            "area": "Geral", "priority": "baixa",
            "suggestion": "E-mail bem estruturado. Verifique se assunto, pré-header e CTA estão alinhados — essa consistência é o principal fator de CLTK em e-mail B2B."
        })

    return suggestions[:5]


# ── Main function ─────────────────────────────────────────────────────────────

def score_email(subject: str, body: str, segment: str = "", category: str = "",
                preheader: str = "", has_cta: bool = False, cta_count: int = 0,
                has_hyperlink: bool = False, hyperlink_count: int = 0,
                cluster_data: dict = None) -> dict:

    cluster     = _get_cluster(cluster_data or {}, segment, category)
    global_data = (cluster_data or {}).get("global", {})

    s_subject   = score_subject(subject, cluster)
    s_copy      = score_copy(body, cluster)
    s_structure = score_structure(preheader, has_cta, cta_count,
                                  has_hyperlink, hyperlink_count, cluster)
    s_context   = score_context(segment, category, cluster,
                                s_copy["word_count"], len(subject.strip()))

    total = min(100, s_subject["points"] + s_copy["points"] +
                     s_structure["points"] + s_context["points"])

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

    performance = estimate_performance(total, cluster, global_data)
    suggestions = generate_suggestions(s_subject, s_copy, s_structure, s_context, cluster)

    return {
        "total_score":  total,
        "rating":       rating,
        "rating_color": rating_color,
        "rating_desc":  rating_desc,
        "dimensions": {
            "subject":   s_subject,
            "copy":      s_copy,
            "structure": s_structure,
            "context":   s_context,
        },
        "performance": performance,
        "suggestions": suggestions,
        "cluster_key": f"{segment}|{category}" if (segment or category) else None,
        "has_cluster": cluster is not None,
    }
