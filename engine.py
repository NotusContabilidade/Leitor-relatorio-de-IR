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
    
    # BLINDAGEM 1: Barreira estendida para garantir que a extração pare antes de encostar em Rendimentos
    FIM = [
        'Dívidas e Ônus Reais', 
        'Rendimentos isentos e não tributáveis',
        'Rendimentos sujeitos a tributação exclusiva',
        'Renda variável'
    ]

    for page in pdf.pages:
        texto = page.extract_text() or ""

        if 'Bens e direitos (Ativos sob sua cust' in texto:
            em_secao = True

        if not em_secao:
            continue

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

                if not cells[0] or not re.match(r'^\d{2}$', cells[0].strip()):
                    continue

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
    return bool(re.search(r'\d+,\s*\d{2}', re.sub(r'\s', '', c)))


def _parse_row_cells(cells):
    grupo  = cells[0].strip()
    codigo = cells[1].strip() if len(cells) > 1 else ""

    # BLINDAGEM 2: Trava de Assinatura. Se não tem padrão de Bem, aborta a linha.
    if not re.match(r'^\d{2}$', grupo):
        return None
        
    # Se o código existe, TEM que ser 2 dígitos. Se for CNPJ ou texto (vazamento de Rendimentos), pulveriza.
    if codigo and not re.match(r'^\d{2}$', codigo):
        return None

    local  = _normalizar_local(cells[2]) if len(cells) > 2 else ""
    
    # Se a coluna do código foi mesclada e o CNPJ caiu na coluna de local, pulveriza.
    if re.search(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', local):
        return None

    cnpj_c = cells[3].strip() if len(cells) > 3 else ""
    cnpj   = cnpj_c if re.match(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$', cnpj_c) else ""

    valores = [(i, c) for i, c in enumerate(cells) if _tem_valor_monetario(c)]
    if not valores:
        return None

    sit_2025 = _parse_valor(valores[-1][1])
    sit_2024 = _parse_valor(valores[-2][1]) if len(valores) >= 2 else 0.0

    disc_start = 4 if cnpj else (
        3 if len(cells) > 3 and re.search(r'[A-Za-z]', cells[3]) and len(cells[3]) > 5
        else 4
    )
    val_first_idx = valores[-2][0] if len(valores) >= 2 else valores[-1][0]
    disc_end = max(disc_start + 1, val_first_idx)

    disc = ' '.join(cells[disc_start:disc_end]).strip()
    disc = re.sub(r'\s+', ' ', disc)

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
    
    # BLINDAGEM 1 (Fallback): Barreira estendida
    FIM = [
        'Dívidas e Ônus Reais', 
        'Rendimentos isentos e não tributáveis',
        'Rendimentos sujeitos a tributação exclusiva',
        'Renda variável'
    ]

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
        # BLINDAGEM 3: Regex Anti-CNPJ. O (?!\.) impede que o "12" de "12.345..." seja lido como código do bem.
        m = re.match(r'^(\d{2})\s+(\d{2})(?:\s+(?!\.)(.*))?$', ls)
        if m:
            if buffer and grupo:
                bem = _parse_entry_texto(grupo, codigo, buffer)
                if bem:
                    bens.append(bem)
            grupo, codigo = m.group(1), m.group(2)
            buffer = [m.group(3).strip()] if m.group(3) and m.group(3).strip() else []
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

    m_local = re.search(r'(\d{3}\s*-\s*(?:Brasil|BRASIL|Estados\s+Unidos|ESTADOS\s+UNIDOS))', text, re.IGNORECASE)
    
    if m_local:
        local = _normalizar_local(m_local.group(1))
    elif "estados unidos" in text.lower() or "unidos" in text.lower():
        local = "249 - Estados Unidos"
    elif "brasil" in text.lower() or cnpj:
        local = "105 - Brasil"
    else:
        local = "105 - Brasil"

    valores = re.findall(r'(?<![,\d])(\d{1,3}(?:\.\d{3})*,\d{2})(?![,\d])', text)
    if not valores:
        return None

    sit_2024 = _parse_valor(valores[-2]) if len(valores) >= 2 else 0.0
    sit_2025 = _parse_valor(valores[-1])

    disc = text
    for v in (valores[-2:] if len(valores) >= 2 else valores[-1:]):
        pos = disc.rfind(v)
        if pos >= 0:
            disc = disc[:pos].strip()
    for rem in [m_local.group(1) if m_local else "", cnpj]:
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
    ('Vendas abaixo de 20mil', 'Vendas abaixo de 20mil no mês'),
    ('Bonificações',           'Bonificações'),
    ('Rendimentos de fundos',  'Rendimentos de fundos e renda fixa'),
]
_EXCLUSIVOS_SUBS = [
    ('JCP (Juros sobre Capital', 'JCP'),
    ('Outros rendimentos',       'Outros rendimentos'),
    ('Aluguel (',                'Aluguel'),
    ('Amortizações',             'Amortizações'),
    ('Rendimentos de fundos',    'Rendimentos de fundos e renda fixa'),
]


def _extrair_rendimentos_exterior(pdf):
    result = {}
    for page in pdf.pages:
        texto = page.extract_text() or ""
        ticker_atual = None
        for linha in texto.split('\n'):
            ls = linha.strip()
            
            m = re.match(r'^Rendimentos de (\S+)$', ls)
            if m:
                ticker_atual = m.group(1)
                if ticker_atual not in result:
                    result[ticker_atual] = []
                continue
                
            if ticker_atual and 'Aplica' in ls and 'Financeira' in ls:
                m_rend = re.search(r'Rendimento ou Perda:\s*(-?)\s*R\$\s*(-?)\s*([\d.,]+)', ls)
                m_imp  = re.search(r'Imposto pago no Exterior:\s*R\$\s*([\d.,]+)', ls)
                
                rend = 0.0
                imp  = 0.0
                
                if m_rend:
                    rend = _parse_valor(m_rend.group(3))
                    if '-' in m_rend.group(1) or '-' in m_rend.group(2):
                        rend = -rend
                if m_imp:
                    imp = _parse_valor(m_imp.group(1))
                    
                result[ticker_atual].append({'rendimento_exterior': rend, 'imposto_exterior': imp})
                ticker_atual = None
    return result


def _extrair_dividas(pdf):
    dividas = []
    em_secao = False
    for page in pdf.pages:
        texto = page.extract_text() or ""
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
                disc = re.sub(r'\s+', ' ', cells[2]).strip() if len(cells) > 2 else ''
                valores = [(i, c) for i, c in enumerate(cells) if re.search(r'\d+,\s*\d{2}', c)]
                sit_2024 = _parse_valor(valores[-2][1]) if len(valores) >= 2 else 0.0
                sit_2025 = _parse_valor(valores[-1][1]) if valores else 0.0
                if disc and len(disc) > 5:
                    dividas.append({'codigo': codigo, 'discriminacao': disc,
                                    'sit_2024': sit_2024, 'sit_2025': sit_2025})
        if parar:
            break
    return dividas


def _parse_row_rendimento(row, sub_secao):
    if not row:
        return None
    cells = [str(c).strip().replace('\n', ' ') if c else '' for c in row]
    compact = [c for c in cells if c.strip()]
    if not compact:
        return None
    combined = ' '.join(compact).lower()
    if any(h in combined for h in ['tipo', 'cnpj da fonte', 'nome da fonte']):
        return None
    tipo_raw = compact[0].strip()
    m_tipo = re.match(r'^(\d{2})\b', tipo_raw)
    if not m_tipo:
        return None
    tipo = m_tipo.group(1)
    valores_c = [(i, c) for i, c in enumerate(compact) if re.search(r'\d+,\s*\d{2}', c)]
    if not valores_c:
        return None
    valor   = _parse_valor(valores_c[-1][1])
    val_pos = valores_c[-1][0]
    middle  = compact[1:val_pos]
    cnpj  = middle[0] if middle and re.match(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', middle[0]) else ''
    nome_f = middle[1] if len(middle) > 1 else (middle[0] if middle and not cnpj else '')
    desc  = re.sub(r'\s+', ' ', ' '.join(middle[2:])).strip() if len(middle) > 2 else ''
    return {'sub_secao': sub_secao, 'tipo': tipo, 'cnpj': cnpj,
            'nome_fonte': nome_f, 'descricao': desc, 'valor': valor}


def _sub_acima_da_tabela(page, bbox_top, sub_headers, sub_atual):
    """Retorna a última sub-seção encontrada no texto ACIMA da tabela na página."""
    if bbox_top <= 2:
        return sub_atual
    try:
        text_above = page.crop((0, 0, page.width, bbox_top)).extract_text() or ""
    except Exception:
        return sub_atual
    last_pos = -1
    resultado = sub_atual
    for chave, nome in sub_headers:
        pos = text_above.rfind(chave)
        if pos > last_pos:
            last_pos = pos
            resultado = nome
    return resultado


def _extrair_rendimentos_secao(pdf, start_marker, end_marker, sub_headers):
    linhas = []
    em_secao = False
    sub_atual = ''
    start_occurrences = 0  # conta quantas vezes o start_marker foi encontrado

    for page in pdf.pages:
        texto = page.extract_text() or ""
        just_activated = False

        if not em_secao:
            if start_marker not in texto:
                continue
            start_occurrences += 1
            # A primeira ocorrência do start_marker junto com o end_marker é a página de visão
            # geral (resumo inicial do PDF). Ignora e espera a ocorrência real da seção.
            if end_marker in texto and start_occurrences == 1:
                continue
            em_secao = True
            just_activated = True

        # Se o end_marker aparece nesta página e não foi a página de ativação,
        # para ANTES de processar as tabelas (evita capturar dados da próxima seção).
        if end_marker in texto and not just_activated:
            break

        # Tenta detecção posicional: associa cada tabela à sub-seção que aparece acima dela
        try:
            page_tables = page.find_tables()
        except Exception:
            page_tables = []

        if page_tables:
            for tbl in page_tables:
                try:
                    bbox_top = tbl.bbox[1]
                except Exception:
                    bbox_top = 0
                local_sub = _sub_acima_da_tabela(page, bbox_top, sub_headers, sub_atual)
                try:
                    rows = tbl.extract()
                except Exception:
                    continue
                for row in (rows or []):
                    linha = _parse_row_rendimento(row, local_sub)
                    if linha:
                        linhas.append(linha)
        else:
            # Fallback sem posição: usa última sub-seção encontrada na página
            last_pos = -1
            for chave, nome in sub_headers:
                pos = texto.rfind(chave)
                if pos > last_pos:
                    last_pos = pos
                    sub_atual = nome
            for table in (page.extract_tables() or []):
                for row in table:
                    linha = _parse_row_rendimento(row, sub_atual)
                    if linha:
                        linhas.append(linha)

        # Atualiza sub_atual para a última sub-seção desta página (usada como fallback na próxima)
        last_pos = -1
        for chave, nome in sub_headers:
            pos = texto.rfind(chave)
            if pos > last_pos:
                last_pos = pos
                sub_atual = nome

        if end_marker in texto:
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
            atual = {
                'mes': m.group(1),
                'resultado_comuns': 0.0, 'resultado_dt': 0.0,
                'resultado_neg_anterior': 0.0,
                'prejuizo_compensar': 0.0, 'base_calculo': 0.0,
                'imposto_devido': 0.0, 'imposto_pagar': 0.0, 'imposto_pago': 0.0,
            }

        if not atual:
            continue

        acertos = 0
        for table in (page.extract_tables() or []):
            for row in table:
                if not row or not row[0]:
                    continue
                cells = [str(c).strip().replace('\n', ' ') if c else '' for c in row]
                first_upper = cells[0].upper()

                if any(h in first_upper for h in [
                    'OPERAÇÕES', 'RESULTADOS', 'CONSOLIDAÇÃO',
                    'MERCADO', 'TITULAR', 'DEPENDENTES'
                ]):
                    continue

                vals = []
                for c in cells[1:]:
                    if c and re.search(r'\d', c) and '%' not in c:
                        vals.append(_parse_valor(c))

                if 'RESULTADO LÍQUIDO DO MÊS' in first_upper and vals:
                    if len(vals) >= 2:
                        atual['resultado_comuns'] = vals[0]
                        atual['resultado_dt']     = vals[1]
                    else:
                        atual['resultado_comuns'] = vals[0]
                    acertos += 1
                elif 'RESULTADO NEGATIVO' in first_upper and vals:
                    atual['resultado_neg_anterior'] = vals[0]; acertos += 1
                elif 'BASE DE CÁLCULO' in first_upper and vals:
                    atual['base_calculo'] = vals[0]; acertos += 1
                elif 'PREJUÍZO A COMPENSAR' in first_upper and vals:
                    atual['prejuizo_compensar'] = vals[0]; acertos += 1
                elif 'IMPOSTO DEVIDO' in first_upper and 'TOTAL' not in first_upper and vals:
                    atual['imposto_devido'] = vals[0]; acertos += 1
                elif first_upper == 'IMPOSTO A PAGAR' and vals:
                    atual['imposto_pagar'] = vals[0]; acertos += 1
                elif first_upper == 'IMPOSTO PAGO' and vals:
                    atual['imposto_pago'] = vals[0]; acertos += 1

        # Fallback texto: usado quando o PDF não tem tabelas reais na seção DT
        if acertos == 0:
            for linha in texto.split('\n'):
                ls = linha.strip()
                lu = ls.upper()
                vals = [_parse_valor(v) for v in re.findall(r'-?\d{1,3}(?:\.\d{3})*,\d{2}', ls)]
                if not vals:
                    continue
                if 'RESULTADO' in lu and 'LÍQUIDO' in lu and 'MÊS' in lu:
                    if len(vals) >= 2:
                        atual['resultado_comuns'] = vals[0]
                        atual['resultado_dt']     = vals[1]
                    else:
                        atual['resultado_comuns'] = vals[0]
                elif 'RESULTADO NEGATIVO' in lu:
                    atual['resultado_neg_anterior'] = vals[0]
                elif 'BASE DE CÁLCULO' in lu:
                    atual['base_calculo'] = vals[0]
                elif 'PREJUÍZO' in lu and 'COMPENSAR' in lu:
                    atual['prejuizo_compensar'] = vals[0]
                elif 'IMPOSTO DEVIDO' in lu and 'TOTAL' not in lu:
                    atual['imposto_devido'] = vals[0]
                elif 'IMPOSTO A PAGAR' in lu:
                    atual['imposto_pagar'] = vals[0]
                elif 'IMPOSTO PAGO' in lu:
                    atual['imposto_pago'] = vals[0]

    if atual:
        meses.append(atual)
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
            texto_capa = "".join((p.extract_text() or "") + "\n" for p in pdf.pages[:2])
            dados["nome"], dados["cpf"], dados["ano_calendario"] = _extrair_info_capa(texto_capa)

            bens = _extrair_bens_tabela(pdf)

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
                    lista_rend = rendimentos_ext[m_t.group(1)]
                    if lista_rend:
                        rd = lista_rend.pop(0)
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

def montar_linhas_bens_brasil(item):
    linhas = []
    for b in item.get("bens", []):
        local = b.get("local", "").lower()
        if ("105" in local or "brasil" in local) and b.get('rendimento_exterior', 0.0) == 0.0:
            linhas.append({
                "Nome":                  item.get("nome", ""),
                "CPF":                   item.get("cpf", ""),
                "Ano Calendário":        item.get("ano_calendario", ""),
                "Grupo":                 b.get("grupo", ""),
                "Código":                b.get("codigo", ""),
                "CNPJ":                  b.get("cnpj", ""),
                "Discriminação":         b.get("discriminacao", ""),
                "Sit. 31/12/2024 (R$)":  b.get("sit_2024", 0.0),
                "Sit. 31/12/2025 (R$)":  b.get("sit_2025", 0.0)
            })
    return linhas

def montar_linhas_bens_exterior(item):
    linhas = []
    for b in item.get("bens", []):
        local = b.get("local", "").lower()
        if ("105" not in local and "brasil" not in local) or b.get('rendimento_exterior', 0.0) != 0.0:
            linhas.append({
                "Nome":                  item.get("nome", ""),
                "CPF":                   item.get("cpf", ""),
                "Ano Calendário":        item.get("ano_calendario", ""),
                "Grupo":                 b.get("grupo", ""),
                "Código":                b.get("codigo", ""),
                "Localização":           b.get("local", "") if b.get("local") else "249 - Estados Unidos",
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
            "Resultado Neg. Anterior (R$)":      d.get("resultado_neg_anterior", 0.0),
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