/* --------------------------------------------------------------------------
   ARQUIVO: web/main.js - Leitor de Relatório de IR
   -------------------------------------------------------------------------- */

let dadosRelatorioGlobal = [];
let nomeArquivoAtual = "Relatorio";
let ui = {};

eel.expose(update_progress);
function update_progress(percentual, mensagem) {
    if (ui.progressBar && ui.loadingText) {
        ui.progressBar.style.width = percentual + '%';
        ui.loadingText.innerText = mensagem;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    ui = {
        mainView:           document.getElementById('main-view'),
        dropZone:           document.getElementById('drop-zone'),
        fileInput:          document.getElementById('file-input'),
        loadingState:       document.getElementById('loading-state'),
        successState:       document.getElementById('success-state'),
        progressBar:        document.getElementById('progress-bar'),
        loadingText:        document.getElementById('loading-text'),
        resultsContainer:   document.getElementById('results-container'),
        resultsTitle:       document.getElementById('results-title'),
        cardsList:          document.getElementById('cards-list'),
        exportButton:       document.getElementById('export-button'),
        backToDropButton:   document.getElementById('back-to-drop-button'),
        historyButton:      document.getElementById('history-button'),
        historyContainer:   document.getElementById('history-container'),
        historyList:        document.getElementById('history-list'),
        closeHistoryButton: document.getElementById('close-history-button')
    };

    setUIState('idle');

    if (ui.exportButton) ui.exportButton.addEventListener('click', acionarExportacaoExcel);

    if (ui.backToDropButton) {
        ui.backToDropButton.addEventListener('click', () => {
            ui.mainView.style.display = 'block';
            ui.resultsContainer.style.display = 'block';
            ui.backToDropButton.style.display = 'none';
            ui.resultsTitle.innerText = "Resultado da Análise";
            dadosRelatorioGlobal = [];
            ui.exportButton.disabled = true;
            ui.cardsList.innerHTML = '<div class="placeholder-card">Aguardando novos arquivos...</div>';
        });
    }

    if (ui.historyButton) {
        ui.historyButton.addEventListener('click', () => {
            ui.historyContainer.style.display = 'block';
            carregarHistorico();
        });
    }
    if (ui.closeHistoryButton) {
        ui.closeHistoryButton.addEventListener('click', () => {
            ui.historyContainer.style.display = 'none';
        });
    }

    // --- Upload ---
    if (ui.dropZone) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(e =>
            ui.dropZone.addEventListener(e, ev => { ev.preventDefault(); ev.stopPropagation(); })
        );
        ui.dropZone.addEventListener('dragover', () => ui.dropZone.classList.add('dragover'));
        ui.dropZone.addEventListener('dragleave', () => ui.dropZone.classList.remove('dragover'));
        ui.dropZone.addEventListener('drop', e => {
            ui.dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) validarEProcessarArquivos(e.dataTransfer.files);
        });
    }
    if (ui.fileInput) {
        ui.fileInput.addEventListener('change', e => {
            if (e.target.files.length) validarEProcessarArquivos(e.target.files);
        });
    }

    // --- Processamento ---

    function validarEProcessarArquivos(fileList) {
        setUIState('loading');
        const files = Array.from(fileList);
        const zipFile = files.find(f => f.name.toLowerCase().endsWith('.zip'));
        if (zipFile && files.length === 1) {
            iniciarProcessamentoZip(zipFile);
        } else {
            const pdfs = files.filter(f => f.name.toLowerCase().endsWith('.pdf'));
            if (pdfs.length > 0) iniciarProcessamentoPdfs(pdfs);
            else { alert("Por favor, envie arquivos .pdf ou um arquivo .zip"); setUIState('idle'); }
        }
    }

    async function iniciarProcessamentoZip(file) {
        try {
            nomeArquivoAtual = file.name;
            const b64 = await converterParaBase64(file);
            eel.processar_arquivo_zip_paralelo(b64, file.name)(callbackProcessamentoConcluido);
        } catch (e) { setUIState('error', "Falha ao ler o arquivo compactado."); }
    }

    async function iniciarProcessamentoPdfs(files) {
        const payloads = [];
        nomeArquivoAtual = files.length === 1 ? files[0].name : 'Lote_IR';
        for (let f of files) payloads.push({ bytes: await converterParaBase64(f), nome: f.name });
        eel.processar_pdfs_soltos_paralelo(payloads)(callbackProcessamentoConcluido);
    }

    function callbackProcessamentoConcluido(res) {
        if (!res || !res.sucesso) return setUIState('error', res ? res.erro : "Falha na comunicação.");
        dadosRelatorioGlobal = res.dados;
        ordenarResultados(dadosRelatorioGlobal);
        renderizarCards(dadosRelatorioGlobal);
        ui.exportButton.disabled = false;
        ui.backToDropButton.style.display = 'flex';
        ui.mainView.style.display = 'none';
        setUIState('success');
    }

    // ─────────────────────────────────────────────────────────────
    // CARDS EXPANDÍVEIS
    // ─────────────────────────────────────────────────────────────

    function renderizarCards(dados) {
        ui.cardsList.innerHTML = '';
        dados.forEach((item, idx) => ui.cardsList.appendChild(criarCard(item, idx)));
    }

    function criarCard(item, idx) {
        const card = document.createElement('div');
        card.className = 'pessoa-card';

        const v2024 = item.total_2024 || 0;
        const v2025 = item.total_2025 || 0;
        const varPct = v2024 > 0 ? ((v2025 - v2024) / v2024 * 100) : null;
        const varStr = varPct === null ? null
            : Math.abs(varPct) > 9999 ? (varPct >= 0 ? '▲ &infin;' : '▼ &infin;')
            : `${varPct >= 0 ? '▲' : '▼'} ${Math.abs(varPct).toFixed(1)}%`;
        const varHtml = varStr
            ? `<span class="variacao ${varPct >= 0 ? 'var-pos' : 'var-neg'}">${varStr}</span>`
            : '';

        const totalDividas = (item.dividas || []).reduce((s, d) => s + (d.sit_2025 || 0), 0);
        const numBens  = (item.bens || []).length;
        const numDiv   = (item.dividas || []).length;
        const numIsen  = (item.rendimentos_isentos || []).length;
        const numExcl  = (item.rendimentos_exclusivos || []).length;
        const mesesDT  = (item.renda_variavel_dt  || []).length;
        const mesesFII = (item.renda_variavel_fii || []).length;

        const secoes   = construirSecoes(item, idx);
        const haDetail = secoes.length > 0;

        const partes = [];
        if (numBens)  partes.push(`${numBens} bens`);
        if (numDiv)   partes.push(`${numDiv} dívida${numDiv !== 1 ? 's' : ''}`);
        if (numIsen)  partes.push(`${numIsen} isentos`);
        if (numExcl)  partes.push(`${numExcl} excl.`);
        if (mesesDT || mesesFII) partes.push(`${mesesDT}m DT · ${mesesFII}m FII`);
        const badgesHtml = partes.length
            ? `<span class="card-summary">${partes.join(' · ')}</span>`
            : '';

        card.innerHTML = `
        <div class="card-header" onclick="toggleCard(${idx})">
            <div class="card-header-left">
                <div class="card-identity">
                    ${gerarBadgeStatus(item.status)}
                    <span class="card-nome">${esc(item.nome || 'Não Detectado')}</span>
                    <span class="card-meta">CPF: ${item.cpf || 'N/A'}&nbsp;&nbsp;·&nbsp;&nbsp;Ano ${item.ano_calendario || '-'}</span>
                </div>
                <div class="card-financeiro">
                    <div class="fin-bloco">
                        <span class="fin-label">31/12/2024</span>
                        <span class="fin-valor">${formatarMoeda(v2024)}</span>
                    </div>
                    <span class="fin-seta">→</span>
                    <div class="fin-bloco">
                        <span class="fin-label">31/12/2025</span>
                        <span class="fin-valor fin-principal">${formatarMoeda(v2025)}</span>
                    </div>
                    ${varHtml}
                    ${totalDividas > 0 ? `
                    <div class="fin-divider"></div>
                    <div class="fin-bloco">
                        <span class="fin-label fin-label-div">Dívidas 2025</span>
                        <span class="fin-valor divida-neg">− ${formatarMoeda(totalDividas)}</span>
                    </div>` : ''}
                </div>
                <div class="card-sections">
                    ${badgesHtml}
                    ${item.arquivo_pdf ? `<span class="arquivo-chip" title="${esc(item.arquivo_pdf)}">${esc(item.arquivo_pdf)}</span>` : ''}
                </div>
            </div>
            ${haDetail ? `<button class="card-toggle-btn" id="toggle-${idx}">▼ Detalhar</button>` : ''}
        </div>
        ${haDetail ? `<div class="card-body" id="body-${idx}" style="display:none;">${construirBody(secoes, idx)}</div>` : ''}
        `;
        return card;
    }

    window.toggleCard = function(idx) {
        const body   = document.getElementById(`body-${idx}`);
        const toggle = document.getElementById(`toggle-${idx}`);
        if (!body) return;
        const aberto = body.style.display !== 'none';
        body.style.display = aberto ? 'none' : 'block';
        toggle.textContent = aberto ? '▼ Detalhar' : '▲ Fechar';
        toggle.classList.toggle('ativo', !aberto);
    };

    window.mudarAba = function(cardIdx, abaIdx) {
        document.querySelectorAll(`.tab-btn[data-card="${cardIdx}"]`).forEach(b => b.classList.remove('ativa'));
        document.querySelectorAll(`.tab-content[data-card="${cardIdx}"]`).forEach(c => c.style.display = 'none');
        document.querySelector(`.tab-btn[data-card="${cardIdx}"][data-aba="${abaIdx}"]`).classList.add('ativa');
        document.querySelector(`.tab-content[data-card="${cardIdx}"][data-aba="${abaIdx}"]`).style.display = 'block';
    };

    function construirSecoes(item, idx) {
        const secoes = [];
        if ((item.bens || []).length)
            secoes.push({ titulo: `Bens e Direitos (${item.bens.length})`, html: tabelaBens(item.bens) });
        if ((item.dividas || []).length)
            secoes.push({ titulo: `Dívidas (${item.dividas.length})`, html: tabelaDividas(item.dividas) });
        if ((item.rendimentos_isentos || []).length)
            secoes.push({ titulo: `Isentos (${item.rendimentos_isentos.length})`, html: tabelaRendimentos(item.rendimentos_isentos) });
        if ((item.rendimentos_exclusivos || []).length)
            secoes.push({ titulo: `Excl./Definitiva (${item.rendimentos_exclusivos.length})`, html: tabelaRendimentos(item.rendimentos_exclusivos) });
        if ((item.renda_variavel_dt || []).length || (item.renda_variavel_fii || []).length)
            secoes.push({ titulo: 'Renda Variável', html: tabelaRendaVariavel(item.renda_variavel_dt || [], item.renda_variavel_fii || []) });
        return secoes;
    }

    function construirBody(secoes, cardIdx) {
        const tabs = secoes.map((s, i) =>
            `<button class="tab-btn${i===0?' ativa':''}" data-card="${cardIdx}" data-aba="${i}" onclick="mudarAba(${cardIdx},${i})">${s.titulo}</button>`
        ).join('');
        const contents = secoes.map((s, i) =>
            `<div class="tab-content" data-card="${cardIdx}" data-aba="${i}" style="display:${i===0?'block':'none'};">${s.html}</div>`
        ).join('');
        return `<div class="tabs-bar">${tabs}</div><div class="tab-area">${contents}</div>`;
    }

    // ── Mini-tabelas ──────────────────────────────────────────────

    function tabelaBens(bens) {
        const temExt = bens.some(b => (b.rendimento_exterior || 0) !== 0 || (b.imposto_exterior || 0) !== 0);
        const linhas = bens.map(b => {
            const v24 = b.sit_2024 || 0, v25 = b.sit_2025 || 0;
            const vp  = v24 > 0 ? ((v25 - v24) / v24 * 100) : null;
            const vpStr = vp !== null
                ? `<span class="${vp >= 0 ? 'mini-pos' : 'mini-neg'}">${vp >= 0 ? '+' : ''}${vp.toFixed(1)}%</span>`
                : '—';
            const extCols = temExt ? `
                <td class="td-val ${(b.rendimento_exterior||0) < 0 ? 'divida-neg' : ''}">${(b.rendimento_exterior||0) !== 0 ? formatarMoeda(b.rendimento_exterior) : '—'}</td>
                <td class="td-val">${(b.imposto_exterior||0) !== 0 ? formatarMoeda(b.imposto_exterior) : '—'}</td>` : '';
            return `<tr>
                <td class="td-mono">${esc(b.grupo)}-${esc(b.codigo)}</td>
                <td class="td-loc">${esc(b.local || '')}</td>
                <td class="td-disc" title="${esc(b.discriminacao)}">${esc(b.discriminacao)}</td>
                <td class="td-val">${formatarMoeda(v24)}</td>
                <td class="td-val td-dest">${formatarMoeda(v25)}</td>
                <td class="td-var">${vpStr}</td>
                ${extCols}
            </tr>`;
        }).join('');
        const extHeaders = temExt ? '<th>Rend. Ext.</th><th>Imp. Ext.</th>' : '';
        return `<div class="mini-table-wrap"><table class="mini-table">
            <thead><tr><th>Grupo-Cód</th><th>Local</th><th>Discriminação</th><th>31/12/2024</th><th>31/12/2025</th><th>Var.</th>${extHeaders}</tr></thead>
            <tbody>${linhas}</tbody>
        </table></div>`;
    }

    function tabelaDividas(dividas) {
        const linhas = dividas.map(d => `<tr>
            <td class="td-mono">${esc(d.codigo)}</td>
            <td class="td-disc" title="${esc(d.discriminacao)}">${esc(d.discriminacao)}</td>
            <td class="td-val">${formatarMoeda(d.sit_2024 || 0)}</td>
            <td class="td-val divida-neg">${formatarMoeda(d.sit_2025 || 0)}</td>
        </tr>`).join('');
        return `<div class="mini-table-wrap"><table class="mini-table">
            <thead><tr><th>Cód</th><th>Discriminação</th><th>31/12/2024</th><th>31/12/2025</th></tr></thead>
            <tbody>${linhas}</tbody>
        </table></div>`;
    }

    function tabelaRendimentos(rends) {
        const linhas = rends.map(r => `<tr>
            <td class="td-sub">${esc(r.sub_secao || '')}</td>
            <td class="td-mono">${esc(r.tipo || '')}</td>
            <td class="td-disc" title="${esc(r.nome_fonte || '')}">${esc(r.nome_fonte || '')}</td>
            <td class="td-disc small" title="${esc(r.descricao || '')}">${esc(r.descricao || '')}</td>
            <td class="td-val td-dest">${formatarMoeda(r.valor || 0)}</td>
        </tr>`).join('');
        return `<div class="mini-table-wrap"><table class="mini-table">
            <thead><tr><th>Sub-seção</th><th>Tipo</th><th>Fonte Pagadora</th><th>Descrição</th><th>Valor</th></tr></thead>
            <tbody>${linhas}</tbody>
        </table></div>`;
    }

    function tabelaRendaVariavel(dt, fii) {
        const linhasDT = dt.map(d => `<tr>
            <td class="td-sub rv-dt-label">Day-Trade</td>
            <td class="td-mono">${esc(d.mes || '')}</td>
            <td class="td-val">${formatarMoeda(d.resultado_comuns || 0)}</td>
            <td class="td-val">${formatarMoeda(d.resultado_dt || 0)}</td>
            <td class="td-val" style="color:#555;">—</td>
            <td class="td-val">${formatarMoeda(d.base_calculo || 0)}</td>
            <td class="td-val">${formatarMoeda(d.imposto_devido || 0)}</td>
            <td class="td-val ${(d.imposto_pagar||0) > 0 ? 'divida-neg' : ''}">${formatarMoeda(d.imposto_pagar || 0)}</td>
        </tr>`).join('');
        const linhasFII = fii.map(f => `<tr>
            <td class="td-sub rv-fii-label">FII</td>
            <td class="td-mono">${esc(f.mes || '')}</td>
            <td class="td-val" style="color:#555;">—</td>
            <td class="td-val" style="color:#555;">—</td>
            <td class="td-val">${formatarMoeda(f.resultado_liquido || 0)}</td>
            <td class="td-val">${formatarMoeda(f.base_calculo || 0)}</td>
            <td class="td-val">${formatarMoeda(f.imposto_devido || 0)}</td>
            <td class="td-val ${(f.imposto_pagar||0) > 0 ? 'divida-neg' : ''}">${formatarMoeda(f.imposto_pagar || 0)}</td>
        </tr>`).join('');
        return `<div class="mini-table-wrap"><table class="mini-table">
            <thead><tr><th>Tipo</th><th>Mês</th><th>Res. Comuns</th><th>Res. DT</th><th>Res. FII</th><th>Base Cálc.</th><th>Imp. Devido</th><th>Imp. Pagar</th></tr></thead>
            <tbody>${linhasDT}${linhasFII}</tbody>
        </table></div>`;
    }

    // ── Histórico ────────────────────────────────────────────────

    async function carregarHistorico() {
        ui.historyList.innerHTML = '<div style="color:#888; padding:20px;">Carregando...</div>';
        try {
            const sessoes = await eel.carregar_historico()();
            if (!sessoes || !sessoes.length) {
                ui.historyList.innerHTML = '<div style="color:#888; padding:20px;">Nenhuma sessão encontrada.</div>';
                return;
            }
            ui.historyList.innerHTML = '';
            sessoes.forEach(s => {
                const card = document.createElement('div');
                card.className = 'session-card';
                card.innerHTML = `
                    <div class="session-date">${formatarData(s.data_analise)}</div>
                    <div class="session-stats">
                        <span class="stat-item"><strong>${s.total}</strong> arquivo(s) analisado(s)</span>
                    </div>
                `;
                ui.historyList.appendChild(card);
            });
        } catch (e) {
            ui.historyList.innerHTML = '<div style="color:#888; padding:20px;">Erro ao carregar histórico.</div>';
        }
    }

    // ── Utilitários ──────────────────────────────────────────────

    function esc(str) {
        return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function formatarMoeda(valor) {
        return Number(valor).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    }

    function formatarData(iso) {
        try { return new Date(iso).toLocaleString('pt-BR'); } catch { return iso; }
    }

    function ordenarResultados(d) {
        d.sort((a, b) => {
            const pesos = { '❌': 3, '⚠️': 2, '✅': 1 };
            return (pesos[b.status] || 0) - (pesos[a.status] || 0);
        });
    }

    function gerarBadgeStatus(s) {
        if (s === '❌') return `<span class="status-pill status-pendencia">PENDENTE</span>`;
        if (s === '⚠️') return `<span class="status-pill status-atencao">ATENÇÃO</span>`;
        return `<span class="status-pill status-ok">REGULAR</span>`;
    }

    function converterParaBase64(file) {
        return new Promise(resolve => {
            const reader = new FileReader();
            reader.readAsDataURL(file);
            reader.onload = () => resolve(reader.result.split(',')[1]);
        });
    }

    function acionarExportacaoExcel() {
        if (!dadosRelatorioGlobal.length) return;
        ui.exportButton.innerHTML = '⏳ Gerando...';
        ui.exportButton.disabled = true;
        eel.salvar_excel(dadosRelatorioGlobal, nomeArquivoAtual)(r => {
            ui.exportButton.innerHTML = '📥 Baixar Excel';
            ui.exportButton.disabled = false;
            if (!r.sucesso && r.erro !== "Cancelado") alert("Erro: " + r.erro);
        });
    }

    function setUIState(state, msg = '') {
        if (ui.loadingState) ui.loadingState.style.display = 'none';
        if (ui.successState) ui.successState.style.display = 'none';
        if (state === 'loading') ui.loadingState.style.display = 'flex';
        else if (state === 'success') { ui.successState.style.display = 'flex'; setTimeout(() => setUIState('idle'), 2500); }
        else if (state === 'error') { alert(msg); setUIState('idle'); }
    }
});
