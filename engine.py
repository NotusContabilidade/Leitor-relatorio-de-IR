# --------------------------------------------------------------------------
# ARQUIVO: engine.py - Leitor de Relatório de IR (myProfit)
# --------------------------------------------------------------------------

import re
import pdfplumber
import io


def _normalizar_local(s):
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\bBRASI\s+L\b', 'BRASIL', s, flags=re.IGNORECASE)
    s = re.sub(r'\bBRASIL\b', 'Brasil', s, flags=re.IGNORECASE)
    s = re.sub(r'\bESTADOS\s+UNIDOS\b', 'Estados Unidos', s, flags=re.IGNORECASE)
    return s


def _parse_valor(text):
    if not text:
        return 0.0
    t = re.sub(r'[^\d,\.\-]', '', str(text).strip())
    if not t or t in (',', '.', '-'):
        return 0.0
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    try:
        return float(t)
    except:
        return 0.0


def _extrair_info_capa(texto):
    nome, cpf, ano = "", "", ""

    m_cpf = re.search(r'CPF:\s*([\d]{3}\.[\d]{3}\.[\d]{3}-[\d]{2})', texto)
    if m_cpf:
        cpf = m_cpf.group(1)

    m_ano = re.search(r'[Aa]no\s+calend[aá]rio:\s*(\d{4})', texto)
    if m_ano:
        ano = m_ano.group(1)

    if cpf:
        cpf_pos = texto.find(cpf)
        before = texto[:cpf_pos] if cpf_pos > 0 else ""
        lines = [l.strip() for l in before.split('\n') if l.strip()]
        EXCLUIR = {'CPF', 'CNPJ', 'RELATÓRIO', 'MYPROFIT', 'ANO', 'DECLARAÇÃO',
                   'IMPOSTO', 'RENDA', 'CALENDÁRIO', 'AUXILIAR', 'PARA'}
        for line in reversed(lines):
            if (len(line) >= 5
                    and re.match(r'^[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+$', line)
                    and not any(x in line.upper() for x in EXCLUIR)):
                nome = line
                break

    return nome, cpf, ano


# ── Extração via tabelas pdfplumber ──────────────────────────────────────────

def _extrair_bens_tabela(pdf):
    bens = []
    em_secao = False
    FIM = ['Dívidas e Ônus Reais', 'Rendimentos isentos']

    for page in pdf.pages:
        texto = page.extract_text() or ""

        if 'Bens e direitos (Ativos sob sua cust' in texto:
            em_secao = True

        if not em_secao:
            continue

        # Detecta fim antes de processar para pegar últimas linhas da página
        parar_apos = False
        for marker in FIM:
            if marker in texto:
                parar_apos = True
                break

        for table in (page.extract_tables() or []):
            for row in table:
                if not row:
                    continue
                cells = [str(c).strip().replace('\n', ' ') if c else '' for c in row]

                # Linha válida começa com grupo (2 dígitos)
                if not cells[0] or not re.match(r'^\d{2}$', cells[0].strip()):
                    continue

                # Ignora linhas de cabeçalho
                combined = ' '.join(cells).lower()
                if any(h in combined for h in ['grupo', 'discrimin', 'situação', 'cód.']):
                    continue

                bem = _parse_row_cells(cells)
                if bem:
                    bens.append(bem)

        if parar_apos:
            break

    return bens


def _tem_valor_monetario(c):
    """True se célula contém valor monetário mesmo com espaços/newlines nos decimais."""
    return bool(re.search(r'\d+,\s*\d{2}', re.sub(r'\s', '', c)))


def _parse_row_cells(cells):
    grupo  = cells[0].strip()
    codigo = cells[1].strip() if len(cells) > 1 else ""
    local  = _normalizar_local(cells[2]) if len(cells) > 2 else ""

    # Verifica CNPJ na posição 3 (layout BR padrão: grupo|cod|local|cnpj|disc|val|val)
    cnpj_c = cells[3].strip() if len(cells) > 3 else ""
    cnpj   = cnpj_c if re.match(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$', cnpj_c) else ""

    # Células com valor monetário (tolerante a espaços/\n internos)
    valores = [(i, c) for i, c in enumerate(cells) if _tem_valor_monetario(c)]
    if not valores:
        return None

    sit_2025 = _parse_valor(valores[-1][1])
    sit_2024 = _parse_valor(valores[-2][1]) if len(valores) >= 2 else 0.0

    # Discriminação: célula(s) com letras entre local/cnpj e os valores
    # Layout BR (com CNPJ): disc começa em idx 4
    # Layout US (sem CNPJ, cells[3] tem letras longas): disc começa em idx 3
    disc_start = 4 if cnpj else (
        3 if len(cells) > 3 and re.search(r'[A-Za-z]', cells[3]) and len(cells[3]) > 5
        else 4
    )
    val_first_idx = valores[-2][0] if len(valores) >= 2 else valores[-1][0]
    disc_end = max(disc_start + 1, val_first_idx)

    disc = ' '.join(cells[disc_start:disc_end]).strip()
    disc = re.sub(r'\s+', ' ', disc)

    # Rejeita disc puramente numérica (linhas de continuação/custo médio)
    if not disc or len(disc) < 4 or not re.search(r'[A-Za-zÀ-ÖØ-öø-ÿ]', disc):
        return None

    return {
        "grupo": grupo,
        "codigo": codigo,
        "local": local,
        "cnpj": cnpj,
        "discriminacao": disc,
        "sit_2024": sit_2024,
        "sit_2025": sit_2025
    }


# ── Extração via texto (fallback) ────────────────────────────────────────────

def _extrair_bens_texto(pdf):
    texto_secao = ""
    em_secao = False
    FIM = ['Dívidas e Ônus Reais', 'Rendimentos isentos']

    for page in pdf.pages:
        texto = page.extract_text() or ""

        if 'Bens e direitos (Ativos sob sua cust' in texto:
            em_secao = True

        if not em_secao:
            continue

        parar = False
        for marker in FIM:
            if marker in texto:
                idx = texto.find(marker)
                texto_secao += "\n" + texto[:idx]
                parar = True
                break

        if not parar:
            texto_secao += "\n" + texto

        if parar:
            break

    bens = []
    grupo = codigo = ""
    buffer = []

    for line in texto_secao.split('\n'):
        ls = line.strip()
        m = re.match(r'^(\d{2})\s+(\d{2})\b(.*)', ls)
        if m:
            if buffer and grupo:
                bem = _parse_entry_texto(grupo, codigo, buffer)
                if bem:
                    bens.append(bem)
            grupo, codigo = m.group(1), m.group(2)
            buffer = [m.group(3).strip()] if m.group(3).strip() else []
        elif grupo and ls:
            buffer.append(ls)

    if buffer and grupo:
        bem = _parse_entry_texto(grupo, codigo, buffer)
        if bem:
            bens.append(bem)

    return bens


def _parse_entry_texto(grupo, codigo, lines):
    text = ' '.join(l for l in lines if l)

    m_cnpj  = re.search(r'(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})', text)
    cnpj    = m_cnpj.group(1) if m_cnpj else ""

    m_local = re.search(r'(1\d{2}\s*-\s*(?:Brasil|BRASIL|Estados\s+Unidos|ESTADOS\s+UNIDOS))', text, re.IGNORECASE)
    local   = _normalizar_local(m_local.group(1)) if m_local else "105 - Brasil"

    valores = re.findall(r'(?<![,\d])(\d{1,3}(?:\.\d{3})*,\d{2})(?![,\d])', text)
    if not valores:
        return None

    sit_2024 = _parse_valor(valores[-2]) if len(valores) >= 2 else 0.0
    sit_2025 = _parse_valor(valores[-1])

    # Discriminação: remove valores, local, cnpj
    disc = text
    for v in (valores[-2:] if len(valores) >= 2 else valores[-1:]):
        pos = disc.rfind(v)
        if pos >= 0:
            disc = disc[:pos].strip()
    for rem in [local, cnpj]:
        if rem:
            disc = disc.replace(rem, '', 1)
    disc = re.sub(r'^\s*[\d\-/\s]+', '', disc)
    disc = re.sub(r'\s+', ' ', disc).strip()

    if not disc or len(disc) < 5:
        return None

    return {"grupo": grupo, "codigo": codigo, "local": local,
            "cnpj": cnpj, "discriminacao": disc,
            "sit_2024": sit_2024, "sit_2025": sit_2025}


# ── Seções adicionais ────────────────────────────────────────────────────────

_MESES_FULL = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
_MESES_ABR  = ['Jan','Fev','Mar','Abr','Mai','Jun',
               'Jul','Ago','Set','Out','Nov','Dez']

_ISENTOS_SUBS = [
    ('Dividendos',             'Dividendos'),
    ('Rendimentos de FII',     'Rendimentos de FII'),
    ('Vendas abaixo de 20mil', 'Vendas abaixo de 20mil'),
    ('Bonificações',           'Bonificações'),
]
_EXCLUSIVOS_SUBS = [
    ('JCP (Juros sobre Capital',  'JCP'),
    ('Outros rendimentos',        'Outros rendimentos'),
    ('Aluguel (',                 'Aluguel'),
    ('Amortizações',              'Amortizações'),
    ('Rendimentos de fundos',     'Rendimentos de fundos e renda fixa'),
]


def _extrair_rendimentos_exterior(pdf):
    """Extrai Aplicação Financeira (rendimento/perda + imposto) de ativos no exterior."""
    result = {}
    for page in pdf.pages:
        texto = page.extract_text() or ""
        ticker_atual = None
        for linha in texto.split('\n'):
            ls = linha.strip()
            m = re.match(r'^Rendimentos de (\S+)$', ls)
            if m:
                ticker_atual = m.group(1)
                continue
            if ticker_atual and 'Aplica' in ls and 'Financeira' in ls:
                m_rend = re.search(r'Rendimento ou Perda:\s*(-?)R\$\s*([\d.,]+)', ls)
                m_imp  = re.search(r'Imposto pago no Exterior:\s*R\$\s*([\d.,]+)', ls)
                rend = 0.0
                imp  = 0.0
                if m_rend:
                    rend = _parse_valor(m_rend.group(2))
                    if m_rend.group(1) == '-':
                        rend = -rend
                if m_imp:
                    imp = _parse_valor(m_imp.group(1))
                result[ticker_atual] = {'rendimento_exterior': rend, 'imposto_exterior': imp}
                ticker_atual = None
    return result


def _extrair_dividas(pdf):
    dividas = []
    em_secao = False
    for page in pdf.pages:
        texto = page.extract_text() or ""
        # Ativa apenas na página de corpo (tem "SHORT/VENDIDA"), não na intro
        if 'Dívidas e Ônus Reais' in texto and 'Rendimentos isentos' not in texto:
            em_secao = True
        if not em_secao:
            continue
        parar = 'Rendimentos isentos' in texto
        for table in (page.extract_tables() or []):
            for row in table:
                if not row:
                    continue
                cells = [str(c).strip().replace('\n', ' ') if c else '' for c in row]
                if not cells[0] or not re.match(r'^\d{2}$', cells[0].strip()):
                    continue
                combined = ' '.join(cells).lower()
                if any(h in combined for h in ['cód', 'discrimin', 'situação']):
                    continue
                codigo = cells[0].strip()
                # Discriminação está em cells[2] (cells[1] é artefato None do pdfplumber)
                disc = re.sub(r'\s+', ' ', cells[2]).strip() if len(cells) > 2 else ''
                # Valor pode ter \n → "746, 20", usar \s* no padrão
                valores = [(i, c) for i, c in enumerate(cells) if re.search(r'\d+,\s*\d{2}', c)]
                sit_2024 = _parse_valor(valores[-2][1]) if len(valores) >= 2 else 0.0
                sit_2025 = _parse_valor(valores[-1][1]) if valores else 0.0
                if disc and len(disc) > 5:
                    dividas.append({'codigo': codigo, 'discriminacao': disc,
                                    'sit_2024': sit_2024, 'sit_2025': sit_2025})
        if parar:
            break
    return dividas


def _extrair_rendimentos_secao(pdf, start_marker, end_marker, sub_headers):
    linhas    = []
    em_secao  = False
    sub_atual = ''
    for page in pdf.pages:
        texto = page.extract_text() or ""
        # Ativa apenas quando o end_marker NÃO está na mesma página (evita página de intro
        # que lista todas as seções ao mesmo tempo)
        if start_marker in texto and end_marker not in texto and not em_secao:
            em_secao = True
        if not em_secao:
            continue
        parar = end_marker in texto
        for chave, nome in sub_headers:
            if chave in texto:
                sub_atual = nome
        for table in (page.extract_tables() or []):
            for row in table:
                if not row:
                    continue
                cells = [str(c).strip().replace('\n', ' ') if c else '' for c in row]
                # Compacta: remove células vazias/None para lidar com colunas mescladas
                compact = [c for c in cells if c.strip()]
                if not compact:
                    continue
                combined = ' '.join(compact).lower()
                if any(h in combined for h in ['tipo', 'cnpj da fonte', 'nome da fonte', 'tip\nipo']):
                    continue
                tipo = compact[0].strip()
                if not re.match(r'^\d{2}$', tipo):
                    continue
                # Valor: último elemento não vazio que case \d+,\s*\d{2}
                valores_c = [(i, c) for i, c in enumerate(compact) if re.search(r'\d+,\s*\d{2}', c)]
                if not valores_c:
                    continue
                valor   = _parse_valor(valores_c[-1][1])
                val_pos = valores_c[-1][0]
                middle  = compact[1:val_pos]
                cnpj = middle[0] if middle and re.match(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', middle[0]) else ''
                nome = middle[1] if len(middle) > 1 else (middle[0] if middle and not cnpj else '')
                desc = re.sub(r'\s+', ' ', ' '.join(middle[2:])).strip() if len(middle) > 2 else ''
                linhas.append({'sub_secao': sub_atual, 'tipo': tipo, 'cnpj': cnpj,
                               'nome_fonte': nome, 'descricao': desc, 'valor': valor})
        if parar:
            break
    return linhas


def _extrair_dt_mensal(pdf):
    meses  = []
    em_dt  = False
    atual  = None
    for page in pdf.pages:
        texto = page.extract_text() or ""
        if 'Operações Comuns / Day-Trade' in texto and not em_dt:
            em_dt = True
        if not em_dt:
            continue
        if 'Operações Fundos Invest. Imob.' in texto:
            if atual:
                meses.append(atual)
            break
        m = re.search(r'Mês:\s*(' + '|'.join(_MESES_FULL) + r')', texto)
        if m:
            if atual:
                meses.append(atual)
            atual = {'mes': m.group(1), 'resultado_comuns': 0.0, 'resultado_dt': 0.0,
                     'prejuizo_compensar': 0.0, 'base_calculo': 0.0,
                     'imposto_devido': 0.0, 'imposto_pagar': 0.0, 'imposto_pago': 0.0}
        if not atual:
            continue
        for line in texto.split('\n'):
            ls  = line.strip()
            ul  = ls.upper()
            pv  = [_parse_valor(v) for v in re.findall(r'-?R\$\s*[\d.,]+', ls)]
            if 'RESULTADO LÍQUIDO DO MÊS' in ul and len(pv) >= 2:
                atual['resultado_comuns'] = pv[0]
                atual['resultado_dt']     = pv[1]
            elif 'PREJUÍZO A COMPENSAR' in ul and pv:
                atual['prejuizo_compensar'] = pv[0]
            elif 'BASE DE CÁLCULO DO IMPOSTO' in ul and pv:
                atual['base_calculo'] = pv[0]
            elif 'IMPOSTO DEVIDO' in ul and 'TOTAL' not in ul and pv:
                atual['imposto_devido'] = pv[0]
            elif ls.lower().startswith('imposto a pagar') and pv:
                atual['imposto_pagar'] = pv[0]
            elif ls.lower().startswith('imposto pago') and pv:
                atual['imposto_pago'] = pv[0]
    return meses


def _extrair_fii_mensal(pdf):
    fii    = []
    em_fii = False
    for page in pdf.pages:
        texto = page.extract_text() or ""
        if 'Operações Fundos Invest. Imob.' in texto:
            em_fii = True
        if not em_fii:
            continue
        for table in (page.extract_tables() or []):
            for row in table:
                if not row:
                    continue
                cells = [str(c).strip().replace('\n', ' ') if c else '' for c in row]
                if not cells[0]:
                    continue
                mes = cells[0].strip()
                if mes not in _MESES_ABR and mes not in _MESES_FULL:
                    continue
                def pv(idx): return _parse_valor(cells[idx]) if len(cells) > idx else 0.0
                fii.append({
                    'mes': mes,
                    'resultado_liquido':      pv(1),
                    'resultado_neg_anterior': pv(2),
                    'base_calculo':           pv(3),
                    'prejuizo_compensar':     pv(4),
                    'aliquota':               cells[5].strip() if len(cells) > 5 else '',
                    'imposto_devido':         pv(6),
                    'saldo_ir_retido':        pv(7),
                    'ir_retido':              pv(8),
                    'ir_compensar':           pv(9),
                    'imposto_pagar':          pv(10),
                    'imposto_pago':           pv(11),
                })
    return fii


# ── Função principal ──────────────────────────────────────────────────────────

def analisar_pdf_worker(pdf_bytes, pasta_nome, nome_arquivo_pdf):
    dados = {
        "pasta_empresa": pasta_nome,
        "arquivo_pdf": nome_arquivo_pdf,
        "cpf": "",
        "nome": "",
        "ano_calendario": "",
        "bens": [],
        "total_2024": 0.0,
        "total_2025": 0.0,
        "dividas": [],
        "rendimentos_isentos": [],
        "rendimentos_exclusivos": [],
        "renda_variavel_dt": [],
        "renda_variavel_fii": [],
        "status": "✅",
        "detalhes_raw": ""
    }

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            # Capa: nome, CPF, ano
            texto_capa = "".join((p.extract_text() or "") + "\n" for p in pdf.pages[:2])
            dados["nome"], dados["cpf"], dados["ano_calendario"] = _extrair_info_capa(texto_capa)

            # Extração principal (tabela)
            bens = _extrair_bens_tabela(pdf)

            # Fallback por texto se poucos resultados
            if len(bens) < 3:
                bens_txt = _extrair_bens_texto(pdf)
                if len(bens_txt) > len(bens):
                    bens = bens_txt

            dados["bens"] = bens
            dados["total_2024"] = sum(b["sit_2024"] for b in bens)
            dados["total_2025"] = sum(b["sit_2025"] for b in bens)
            dados["status"] = "✅" if bens else "⚠️"

            if not bens:
                dados["detalhes_raw"] = "Tabela de Bens e Direitos não encontrada no PDF"

            rendimentos_ext = _extrair_rendimentos_exterior(pdf)
            for bem in dados["bens"]:
                bem.setdefault('rendimento_exterior', 0.0)
                bem.setdefault('imposto_exterior', 0.0)
                local = bem.get('local', '')
                if '105' in local or 'brasil' in local.lower():
                    continue
                m_t = re.match(r'^(\S+)\s+-', bem.get('discriminacao', ''))
                if m_t and m_t.group(1) in rendimentos_ext:
                    rd = rendimentos_ext[m_t.group(1)]
                    bem['rendimento_exterior'] = rd['rendimento_exterior']
                    bem['imposto_exterior']    = rd['imposto_exterior']

            dados["dividas"] = _extrair_dividas(pdf)
            dados["rendimentos_isentos"] = _extrair_rendimentos_secao(
                pdf,
                'Rendimentos isentos e não tributáveis',
                'Rendimentos sujeitos a tributação exclusiva',
                _ISENTOS_SUBS)
            dados["rendimentos_exclusivos"] = _extrair_rendimentos_secao(
                pdf,
                'Rendimentos sujeitos a tributação exclusiva',
                'Renda variável',
                _EXCLUSIVOS_SUBS)
            dados["renda_variavel_dt"]  = _extrair_dt_mensal(pdf)
            dados["renda_variavel_fii"] = _extrair_fii_mensal(pdf)

    except Exception as e:
        dados["status"] = "❌"
        dados["detalhes_raw"] = str(e)

    return dados


# ── Funções para exportação Excel ─────────────────────────────────────────────

def montar_linha_resumo(item):
    status_txt = {"✅": "OK", "⚠️": "ATENÇÃO", "❌": "ERRO"}.get(item.get("status", ""), "")
    return {
        "Status":                  status_txt,
        "Nome":                    item.get("nome", ""),
        "CPF":                     item.get("cpf", ""),
        "Ano Calendário":          item.get("ano_calendario", ""),
        "Total 31/12/2024 (R$)":   item.get("total_2024", 0.0),
        "Total 31/12/2025 (R$)":   item.get("total_2025", 0.0),
        "Qtde Ativos":             len(item.get("bens", [])),
        "Arquivo PDF":             item.get("arquivo_pdf", "")
    }


def montar_linhas_detalhe(item):
    linhas = []
    for b in item.get("bens", []):
        linhas.append({
            "Nome":                  item.get("nome", ""),
            "CPF":                   item.get("cpf", ""),
            "Ano Calendário":        item.get("ano_calendario", ""),
            "Grupo":                 b.get("grupo", ""),
            "Código":                b.get("codigo", ""),
            "Localização":           b.get("local", ""),
            "CNPJ":                  b.get("cnpj", ""),
            "Discriminação":         b.get("discriminacao", ""),
            "Sit. 31/12/2024 (R$)":  b.get("sit_2024", 0.0),
            "Sit. 31/12/2025 (R$)":  b.get("sit_2025", 0.0),
            "Rend./Perda Ext. (R$)": b.get("rendimento_exterior", 0.0),
            "Imp. Pago Ext. (R$)":   b.get("imposto_exterior", 0.0)
        })
    return linhas


def montar_linhas_dividas(item):
    rows = []
    for d in item.get("dividas", []):
        rows.append({
            "Nome":                  item.get("nome", ""),
            "CPF":                   item.get("cpf", ""),
            "Código":                d.get("codigo", ""),
            "Discriminação":         d.get("discriminacao", ""),
            "Sit. 31/12/2024 (R$)":  d.get("sit_2024", 0.0),
            "Sit. 31/12/2025 (R$)":  d.get("sit_2025", 0.0),
        })
    return rows


def montar_linhas_rendimentos(item, campo):
    rows = []
    for r in item.get(campo, []):
        rows.append({
            "Nome":                   item.get("nome", ""),
            "CPF":                    item.get("cpf", ""),
            "Sub-seção":              r.get("sub_secao", ""),
            "Tipo":                   r.get("tipo", ""),
            "CNPJ Fonte Pagadora":    r.get("cnpj", ""),
            "Nome Fonte Pagadora":    r.get("nome_fonte", ""),
            "Descrição":              r.get("descricao", ""),
            "Valor (R$)":             r.get("valor", 0.0),
        })
    return rows


def montar_linhas_renda_variavel(item):
    rows = []
    for d in item.get("renda_variavel_dt", []):
        rows.append({
            "Nome":                              item.get("nome", ""),
            "CPF":                               item.get("cpf", ""),
            "Tipo":                              "Day-Trade / Op. Comuns",
            "Mês":                               d.get("mes", ""),
            "Resultado Líquido Comuns (R$)":     d.get("resultado_comuns", 0.0),
            "Resultado Líquido Day-Trade (R$)":  d.get("resultado_dt", 0.0),
            "Resultado Líquido FII (R$)":        None,
            "Resultado Neg. Anterior (R$)":      None,
            "Base de Cálculo (R$)":              d.get("base_calculo", 0.0),
            "Prejuízo a Compensar (R$)":         d.get("prejuizo_compensar", 0.0),
            "Imposto Devido (R$)":               d.get("imposto_devido", 0.0),
            "Saldo IR Retido (R$)":              None,
            "IR Retido (R$)":                    None,
            "IR a Compensar (R$)":               None,
            "Imposto a Pagar (R$)":              d.get("imposto_pagar", 0.0),
            "Imposto Pago (R$)":                 d.get("imposto_pago", 0.0),
        })
    for f in item.get("renda_variavel_fii", []):
        rows.append({
            "Nome":                              item.get("nome", ""),
            "CPF":                               item.get("cpf", ""),
            "Tipo":                              "Fundos Invest. Imob.",
            "Mês":                               f.get("mes", ""),
            "Resultado Líquido Comuns (R$)":     None,
            "Resultado Líquido Day-Trade (R$)":  None,
            "Resultado Líquido FII (R$)":        f.get("resultado_liquido", 0.0),
            "Resultado Neg. Anterior (R$)":      f.get("resultado_neg_anterior", 0.0),
            "Base de Cálculo (R$)":              f.get("base_calculo", 0.0),
            "Prejuízo a Compensar (R$)":         f.get("prejuizo_compensar", 0.0),
            "Imposto Devido (R$)":               f.get("imposto_devido", 0.0),
            "Saldo IR Retido (R$)":              f.get("saldo_ir_retido", 0.0),
            "IR Retido (R$)":                    f.get("ir_retido", 0.0),
            "IR a Compensar (R$)":               f.get("ir_compensar", 0.0),
            "Imposto a Pagar (R$)":              f.get("imposto_pagar", 0.0),
            "Imposto Pago (R$)":                 f.get("imposto_pago", 0.0),
        })
    return rows
