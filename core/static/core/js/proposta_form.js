/*
 * Tela de proposta: soma ao vivo, desconto embutido, aviso de reserva e
 * linhas dinâmicas da composição do pagamento.
 */
(function () {
    "use strict";

    // 1. Procura o formulário pelos seletores compatíveis (#proposta-form ou #form-proposta)
    var form = document.getElementById("proposta-form") || document.getElementById("form-proposta");
    if (!form) return;

    // ---------- Atalhos ----------
    function $(seletor, contexto) {
        return (contexto || document).querySelector(seletor);
    }
    function $$(seletor, contexto) {
        return Array.prototype.slice.call((contexto || document).querySelectorAll(seletor));
    }

    // ---------- Mapeamento de Elementos ----------
    var campoVeiculo = $('[name="veiculo"]', form);
    var campoValor = $('[name="valor_oferecido"]', form);
    
    // Suporte aos IDs do seu HTML e fallbacks
    var container = document.getElementById("pagamentos-container") || document.getElementById("composicao-linhas");
    var modelo = document.getElementById("pagamento-empty-form") || document.getElementById("composicao-vazia");
    var botaoAdicionar = document.getElementById("btn-add-linha");

    // Identifica o prefixo real do Formset (ex: 'pagamentos' ou 'composicao')
    var prefixoFormset = container ? (container.getAttribute("data-prefix") || "pagamentos") : "pagamentos";
    var totalForms = $('[name="' + prefixoFormset + '-TOTAL_FORMS"]', form) || $('[name$="-TOTAL_FORMS"]', form);

    // Carregamento do JSON de veículos
    var infoEl = document.getElementById("veiculos-info");
    var veiculos = {};
    try {
        veiculos = infoEl ? JSON.parse(infoEl.textContent) : {};
    } catch (e) {
        veiculos = {};
    }

    function centavos(valor) {
    if (valor === null || valor === undefined || valor === "") {
        return 0;
    }

    if (typeof valor === "number") {
        return Number.isFinite(valor)
            ? Math.round(valor * 100)
            : 0;
    }

    var texto = String(valor)
        .trim()
        .replace(/[^\d,.-]/g, "");

    if (texto.includes(",")) {
        texto = texto.replace(/\./g, "").replace(",", ".");
    } else if ((texto.match(/\./g) || []).length > 1) {
        texto = texto.replace(/\./g, "");
    }

    var numero = Number(texto);

    return Number.isFinite(numero)
        ? Math.round(numero * 100)
        : 0;
}

    function brl(c) {
        return (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
    }

    function definirTexto(id, texto) {
        var el = document.getElementById(id);
        if (el) el.textContent = texto;
    }

    // ---------- Gerenciamento das Linhas ----------
    function linhaExcluida(linha) {
        var del = $('[name$="-DELETE"]', linha);
        return linha.style.display === "none" || linha.hidden || (del && del.checked);
    }

    function linhasAtivas() {
        return $$("[data-form-row], .composicao-linha", container).filter(function (l) {
            return !linhaExcluida(l);
        });
    }

    function atualizarLinha(linha) {
        var seletorTipo = $('[name$="-tipo"]', linha);
        var tipo = seletorTipo ? seletorTipo.value.toUpperCase() : "";

        var troca = $('[data-extra="troca"], .campos-troca', linha);
        var financiamento = $('[data-extra="financiamento"], .campos-financiamento', linha);

        if (troca) {
            troca.style.display = (tipo === "TROCA" || tipo === "VEICULO_TROCA") ? "grid" : "none";
        }
        if (financiamento) {
            financiamento.style.display = (tipo === "FINANCIAMENTO") ? "grid" : "none";
        }

        var rotulo = $(".rotulo-valor", linha);
        if (rotulo) {
            rotulo.textContent = (tipo === "TROCA" || tipo === "VEICULO_TROCA") ? "Valor estimado (R$)" : "Valor (R$)";
        }
    }

    function adicionarLinha() {
        if (!modelo || !container || !totalForms) return;

        var indice = parseInt(totalForms.value, 10) || 0;
        var htmlModelo = modelo.innerHTML || modelo.content.firstElementChild.outerHTML;
        var htmlFormatado = htmlModelo.replace(/__prefix__/g, indice).trim();

        var caixa = document.createElement("div");
        caixa.innerHTML = htmlFormatado;

        var novaLinha = caixa.firstElementChild;
        if (!novaLinha) return;

        container.appendChild(novaLinha);
        totalForms.value = indice + 1;

        atualizarLinha(novaLinha);
        recalcular();
    }

    function removerLinha(linha) {
        var del = $('[name$="-DELETE"]', linha);
        if (del) {
            del.checked = true;
            linha.style.display = "none";
        } else {
            linha.remove();
        }
        recalcular();
    }

    // ---------- Recálculo dos Valores em Tempo Real ----------
    function recalcular() {
        var idVeiculo = campoVeiculo ? campoVeiculo.value : null;
        var veiculo = idVeiculo ? veiculos[idVeiculo] : null;

        // Leitura do preço de tabela do elemento HTML ou do JSON
        var elemPrecoTabela = document.getElementById("resumo-preco-tabela");
        var precoTabelaAttr = elemPrecoTabela ? elemPrecoTabela.getAttribute("data-valor") : null;
        
        var tabela = null;
        if (veiculo && veiculo.preco) {
            tabela = centavos(veiculo.preco);
        } else if (veiculo && veiculo.preco_tabela) {
            tabela = centavos(veiculo.preco_tabela);
        } else if (precoTabelaAttr && parseFloat(precoTabelaAttr) > 0) {
            tabela = centavos(precoTabelaAttr);
        }

        var oferecido = campoValor ? centavos(campoValor.value) : 0;

        var soma = 0;
        linhasAtivas().forEach(function (linha) {
            var valor = $('[name$="-valor"]', linha);
            soma += valor ? centavos(valor.value) : 0;
        });

        var diferenca = soma - oferecido;

        // Atualização de Preço de Tabela e Desconto
        definirTexto("resumo-preco-tabela", tabela !== null ? brl(tabela) : "R$ 0,00");
        definirTexto("resumo-valor-oferecido", oferecido ? brl(oferecido) : "R$ 0,00");
        definirTexto("resumo-valor-oferecido-composicao", oferecido ? brl(oferecido) : "R$ 0,00");

        if (tabela !== null && oferecido > 0) {
            var desconto = tabela - oferecido;
            var pct = tabela ? (desconto / tabela) * 100 : 0;
            definirTexto("resumo-desconto", brl(desconto));
            definirTexto(
                "resumo-desconto-pct",
                pct.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "% do preço de tabela"
            );
        } else {
            definirTexto("resumo-desconto", "R$ 0,00");
            definirTexto("resumo-desconto-pct", "0,00% do preço de tabela");
        }

        // Atualização do Resumo de Composição
        definirTexto("resumo-soma", brl(soma));
        definirTexto("resumo-diferenca", brl(diferenca));

        // Alerta de Divergência na Composição
        var aviso = document.getElementById("aviso-composicao");
        var textoAviso = document.getElementById("aviso-composicao-texto");

        if (aviso) {
            if (Math.abs(diferenca) === 0 || (oferecido === 0 && soma === 0)) {
                aviso.hidden = true;
                aviso.style.display = "none";
            } else {
                aviso.hidden = false;
                aviso.style.display = "flex";
                var mensagem = diferenca > 0
                    ? "A soma das formas de pagamento excede o valor oferecido em " + brl(diferenca) + "."
                    : "Faltam " + brl(Math.abs(diferenca)) + " na composição para atingir o valor oferecido.";
                
                if (textoAviso) {
                    textoAviso.textContent = mensagem;
                } else {
                    aviso.textContent = mensagem;
                }
            }
        }

        // Alerta de Veículo Reservado
        var avisoReserva = document.getElementById("aviso-reserva");
        if (avisoReserva) {
            var reservado = !!(veiculo && veiculo.reservado);
            avisoReserva.style.display = reservado ? "flex" : "none";
            avisoReserva.hidden = !reservado;
            definirTexto("aviso-reserva-prazo", reservado ? (veiculo.reserva_prazo || veiculo.reserva_expira || "") : "");
        }
    }

    // ---------- Eventos ----------
    form.addEventListener("input", recalcular);

    form.addEventListener("change", function (evento) {
        var alvo = evento.target;
        if (alvo && alvo.name && /-tipo$/.test(alvo.name)) {
            var linha = alvo.closest("[data-form-row], .composicao-linha");
            if (linha) atualizarLinha(linha);
        }
        recalcular();
    });

    if (container) {
        container.addEventListener("click", function (evento) {
            var botao = evento.target.closest(".btn-remover-linha, [data-remove-row]");
            if (!botao) return;
            evento.preventDefault();
            var linha = botao.closest("[data-form-row], .composicao-linha");
            if (linha) removerLinha(linha);
        });
    }

    if (botaoAdicionar) {
        botaoAdicionar.addEventListener("click", function (evento) {
            evento.preventDefault();
            adicionarLinha();
        });
    }

    // ---------- Inicialização ----------
    $$("[data-form-row], .composicao-linha", container).forEach(function (linha) {
        var del = $('[name$="-DELETE"]', linha);
        if (del && del.checked) {
            linha.style.display = "none";
        }
        atualizarLinha(linha);
    });
    
    recalcular();
})();