# 1. Biblioteca padrão do Python (Standard Library)
from datetime import timedelta
from decimal import Decimal, InvalidOperation

# 2. Django e bibliotecas de terceiros (Third-party packages)
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

# 3. Imports locais da aplicação (Local apps / Relative imports)
from .decorators import perfil_requerido
from .forms import (
    AlterarSituacaoForm,
    ClienteForm,
    ComposicaoFormSet,
    DecisaoPropostaForm,
    DespesaEditarForm,
    DespesaForm,
    LoginForm,
    PrecoVendaForm,
    PropostaFiltroForm,
    PropostaForm,
    ReservaForm,
    TelefoneClienteFormSet,
    VeiculoForm,
    VendedorCadastroForm,
    VendedorEdicaoForm,
)
from .models import (
    Cliente,
    FotoVeiculo,
    HistoricoPrecoVeiculo,
    HistoricoSituacaoVeiculo,
    LancamentoFinanceiro,
    PerfilVendedor,
    Proposta,
    ReservaVeiculo,
    TelefoneCliente,
    Usuario,
    Veiculo,
)


def adicionar_erros_de_validacao(form, erro, renomear=None):
    """
    Converte um ValidationError do model (full_clean) em erros do form.
    `renomear` troca nomes de campo do model pelos do form, ex.: {"first_name": "nome"}.
    """
    renomear = renomear or {}
    if hasattr(erro, "message_dict"):
        for campo, mensagens in erro.message_dict.items():
            campo = renomear.get(campo, campo)
            alvo = campo if campo in form.fields else None
            for mensagem in mensagens:
                form.add_error(alvo, mensagem)
    else:
        for mensagem in erro.messages:
            form.add_error(None, mensagem)


def erros_do_form_como_mensagens(request, form):
    """Para as views que só redirecionam (reservar, alterar situação)."""
    for erros in form.errors.values():
        for erro in erros:
            messages.error(request, erro)


def login_view(request):
    if request.method == "POST":
        form = LoginForm(request.POST)

        if form.is_valid():
            usuario = authenticate(
                request,
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
            )

            if usuario is None:
                messages.error(request, "Usuário ou senha inválidos.")
            elif not usuario.ativo:
                messages.error(request, "Usuário inativo. Contate o gerente.")
            else:
                login(request, usuario)
                return redirect("painel")
    else:
        form = LoginForm()

    return render(request, "core/login.html", {"form": form})


@login_required
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def painel_view(request):
    usuario = request.user

    if usuario.is_gerente():
        return redirect("painel_gerente")
    elif usuario.is_vendedor():
        return redirect("painel_vendedor")
    elif usuario.is_administrativo():
        return redirect("painel_administrativo")

    logout(request)
    messages.error(request, "Perfil de usuário inválido. Contate o gerente.")
    return redirect("login")


@perfil_requerido("GERENTE")
def painel_gerente_view(request):
    vendedores = PerfilVendedor.objects.select_related("usuario").all()

    veiculos_disponiveis = Veiculo.objects.filter(
        status=Veiculo.Status.DISPONIVEL
    ).count()

    vendas_concluidas = Veiculo.objects.filter(
        situacao__in=[
            Veiculo.Situacao.VENDIDO,
            Veiculo.Situacao.ENTREGUE,
        ]
    ).count()

    vendedores_ativos = PerfilVendedor.objects.filter(
        usuario__ativo=True
    ).count()

    return render(
        request,
        "core/gerente_painel_inicio.html",
        {
            "vendedores": vendedores,
            "veiculos_disponiveis": veiculos_disponiveis,
            "vendas_concluidas": vendas_concluidas,
            "vendedores_ativos": vendedores_ativos,
        },
    )




@perfil_requerido("ADMINISTRATIVO")
def painel_administrativo_view(request):
    return render(request, "core/administrativo_painel_inicio.html")


@perfil_requerido("ADMINISTRATIVO")
def despesas_view(request):
    veiculos = (
        Veiculo.objects.prefetch_related("fotos")
        .all()
        .order_by("marca", "modelo")
    )

    total_despesas = LancamentoFinanceiro.objects.filter(
        tipo=LancamentoFinanceiro.Tipo.DESPESA,
        excluido=False,
    ).count()

    valor_total = (
        LancamentoFinanceiro.objects.filter(
            tipo=LancamentoFinanceiro.Tipo.DESPESA, excluido=False
        ).aggregate(total=Sum("valor"))["total"]
        or 0
    )

    veiculos_com_despesas = (
        Veiculo.objects.filter(
            lancamentos__tipo=LancamentoFinanceiro.Tipo.DESPESA,
            lancamentos__excluido=False,
        )
        .distinct()
        .count()
    )

    return render(
        request,
        "core/administrativo_painel_despesas.html",
        {
            "veiculos": veiculos,
            "total_despesas": total_despesas,
            "valor_total": valor_total,
            "veiculos_com_despesas": veiculos_com_despesas,
        },
    )


@perfil_requerido("ADMINISTRATIVO")
def despesas_veiculo_view(request, veiculo_id):
    veiculo = get_object_or_404(Veiculo, pk=veiculo_id)

    despesas = veiculo.lancamentos.filter(
        tipo=LancamentoFinanceiro.Tipo.DESPESA,
        excluido=False,
    ).order_by("-data_lancamento", "-criado_em")

    total_despesas = sum(despesa.valor for despesa in despesas)
    custo_aquisicao = veiculo.custo_aquisicao or 0
    custo_total = custo_aquisicao + total_despesas

    return render(
        request,
        "core/administrativo_despesas_veiculo.html",
        {
            "veiculo": veiculo,
            "despesas": despesas,
            "total_despesas": total_despesas,
            "custo_aquisicao": custo_aquisicao,
            "custo_total": custo_total,
        },
    )


@perfil_requerido("ADMINISTRATIVO")
def adicionar_despesa_view(request, veiculo_id):
    veiculo = get_object_or_404(Veiculo, pk=veiculo_id)

    if request.method == "POST":
        form = DespesaForm(request.POST)
        if form.is_valid():
            despesa = form.save(commit=False)
            despesa.veiculo = veiculo
            despesa.tipo = LancamentoFinanceiro.Tipo.DESPESA
            despesa.registrado_por = request.user
            despesa.save()
            return redirect("despesas_veiculo", veiculo_id=veiculo.id)
    else:
        form = DespesaForm()

    return render(
        request,
        "core/administrativo_adicionar_despesa.html",
        {"form": form, "veiculo": veiculo},
    )


@perfil_requerido("ADMINISTRATIVO")
def editar_despesa_view(request, despesa_id):
    despesa = get_object_or_404(
        LancamentoFinanceiro,
        pk=despesa_id,
        tipo=LancamentoFinanceiro.Tipo.DESPESA,
    )

    if request.method == "POST":
        form = DespesaEditarForm(request.POST, instance=despesa)
        if form.is_valid():
            despesa = form.save(commit=False)
            despesa.editado_por = request.user
            despesa.editado_em = timezone.now()
            despesa.save()
            return redirect("despesas_veiculo", veiculo_id=despesa.veiculo.id)
    else:
        form = DespesaEditarForm(instance=despesa)

    return render(
        request,
        "core/administrativo_editar_despesa.html",
        {"form": form, "despesa": despesa, "veiculo": despesa.veiculo},
    )


@perfil_requerido("ADMINISTRATIVO")
def excluir_despesa_view(request, despesa_id):
    despesa = get_object_or_404(
        LancamentoFinanceiro,
        pk=despesa_id,
        tipo=LancamentoFinanceiro.Tipo.DESPESA,
        excluido=False,
    )

    if request.method == "POST":
        despesa.excluido = True
        despesa.excluido_por = request.user
        despesa.excluido_em = timezone.now()
        despesa.save(
            update_fields=[
                "excluido",
                "excluido_por",
                "excluido_em",
            ]
        )

        return redirect("despesas_veiculo", veiculo_id=despesa.veiculo.id)

    return render(
        request,
        "core/administrativo_excluir_despesa.html",
        {
            "despesa": despesa,
            "veiculo": despesa.veiculo,
        },
    )


@perfil_requerido("ADMINISTRATIVO")
def despesas_excluidas_veiculo_view(request, veiculo_id):
    veiculo = get_object_or_404(Veiculo, pk=veiculo_id)

    despesas = veiculo.lancamentos.filter(
        tipo=LancamentoFinanceiro.Tipo.DESPESA,
        excluido=True,
    ).order_by("-excluido_em")

    return render(
        request,
        "core/administrativo_despesas_excluidas_veiculo.html",
        {
            "veiculo": veiculo,
            "despesas": despesas,
        },
    )


@perfil_requerido("GERENTE")
def editar_vendedor_view(request, vendedor_id):
    dados = get_object_or_404(
        PerfilVendedor.objects.select_related("usuario"),
        pk=vendedor_id,
    )
    usuario = dados.usuario

    if request.method == "POST":
        form = VendedorEdicaoForm(request.POST)

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with transaction.atomic():
                    usuario.first_name = cd["nome"]
                    usuario.email = cd["email"]
                    usuario.ativo = cd["ativo"]
                    usuario.save()

                    dados.tipo_alcada = cd["tipo_alcada"]
                    dados.valor_alcada = cd["valor_alcada"]
                    dados.percentual_comissao = cd["percentual_comissao"]
                    dados.editado_por = request.user

                    dados.full_clean()
                    dados.save()

                messages.success(request, "Dados do vendedor atualizados com sucesso.")
                return redirect("vendedores")

            except ValidationError as erro:
                usuario.refresh_from_db()
                adicionar_erros_de_validacao(form, erro)
    else:
        form = VendedorEdicaoForm(
            initial={
                "nome": usuario.first_name,
                "email": usuario.email,
                "ativo": "true" if usuario.ativo else "false",
                "tipo_alcada": dados.tipo_alcada,
                "valor_alcada": dados.valor_alcada,
                "percentual_comissao": dados.percentual_comissao,
            }
        )

    return render(
        request,
        "core/gerente_editar_vendedor.html",
        {"dados": dados, "form": form},
    )


@perfil_requerido("GERENTE")
def vendedores_view(request):
    busca = request.GET.get("busca", "").strip()
    status = request.GET.get("status", "")

    vendedores = PerfilVendedor.objects.select_related("usuario").all()

    if busca:
        vendedores = vendedores.filter(
            Q(usuario__first_name__icontains=busca)
            | Q(usuario__last_name__icontains=busca)
            | Q(usuario__username__icontains=busca)
            | Q(usuario__email__icontains=busca)
        )

    if status == "ativo":
        vendedores = vendedores.filter(usuario__ativo=True)
    elif status == "inativo":
        vendedores = vendedores.filter(usuario__ativo=False)
    else:
        status = ""

    return render(
        request,
        "core/gerente_painel_vendedores.html",
        {
            "vendedores": vendedores,
            "busca": busca,
            "status_selecionado": status,
        },
    )


@perfil_requerido("GERENTE")
def cadastrar_vendedor_view(request):
    if request.method == "POST":
        form = VendedorCadastroForm(request.POST)

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with transaction.atomic():
                    usuario = Usuario(
                        username=cd["username"],
                        email=cd["email"],
                        perfil=Usuario.Perfil.VENDEDOR,
                        ativo=True,
                    )
                    usuario.set_password(cd["senha"])
                    usuario.first_name = cd["nome"]

                    usuario.full_clean()
                    usuario.save()

                    PerfilVendedor.objects.create(
                        usuario=usuario,
                        tipo_alcada=cd["tipo_alcada"],
                        valor_alcada=cd["valor_alcada"],
                        percentual_comissao=cd["percentual_comissao"],
                        editado_por=request.user,
                    )

                messages.success(request, "Vendedor cadastrado com sucesso.")
                return redirect("vendedores")

            except ValidationError as erro:
                adicionar_erros_de_validacao(form, erro, renomear={"first_name": "nome"})
            except IntegrityError:
                form.add_error("username", "Esse usuário já está cadastrado.")
    else:
        form = VendedorCadastroForm()

    return render(request, "core/gerente_cadastrar_vendedor.html", {"form": form})


@perfil_requerido("GERENTE")
def cadastrar_veiculo_view(request):
    if request.method == "POST":
        form = VeiculoForm(request.POST, request.FILES)

        if form.is_valid():
            try:
                with transaction.atomic():
                    veiculo = form.save(commit=False)
                    veiculo.criado_por = request.user
                    veiculo.save()

                    for ordem, imagem in enumerate(form.cleaned_data["fotos"]):
                        FotoVeiculo.objects.create(
                            veiculo=veiculo,
                            imagem=imagem,
                            ordem=ordem,
                            principal=(ordem == 0),
                        )

                messages.success(request, "Veículo cadastrado com sucesso.")
                return redirect("veiculos")

            except IntegrityError:
                form.add_error(
                    None,
                    "Já existe um veículo com essa placa ou chassi no estoque.",
                )
    else:
        form = VeiculoForm()

    return render(request, "core/gerente_cadastrar_veiculo.html", {"form": form})


@perfil_requerido("GERENTE")
def veiculos_view(request):
    for reserva in ReservaVeiculo.objects.filter(
        cancelada=False, expira_em__lte=timezone.now()
    ):
        reserva.expirar()

    busca = request.GET.get("busca", "").strip()
    situacao = request.GET.get("situacao", "")
    origem = request.GET.get("origem", "")
    ano_fabricacao = request.GET.get("ano_fabricacao", "")

    veiculos = Veiculo.objects.prefetch_related("fotos").all()

    if busca:
        veiculos = veiculos.filter(
            Q(marca__icontains=busca)
            | Q(modelo__icontains=busca)
            | Q(placa__icontains=busca)
        )

    situacoes_validas = dict(Veiculo.Situacao.choices)
    if situacao in situacoes_validas:
        veiculos = veiculos.filter(situacao=situacao)
    else:
        situacao = ""

    origens_validas = dict(Veiculo.Origem.choices)
    if origem in origens_validas:
        veiculos = veiculos.filter(origem=origem)
    else:
        origem = ""

    if ano_fabricacao:
        try:
            ano = int(ano_fabricacao)
            if 1900 <= ano <= 2100:
                veiculos = veiculos.filter(ano_fabricacao=ano)
            else:
                ano_fabricacao = ""
        except ValueError:
            ano_fabricacao = ""

    veiculos = veiculos.order_by("-criado_em")

    anos = (
        Veiculo.objects.order_by("-ano_fabricacao")
        .values_list("ano_fabricacao", flat=True)
        .distinct()
    )

    return render(
        request,
        "core/gerente_painel_veiculos.html",
        {
            "veiculos": veiculos,
            "busca": busca,
            "situacoes": Veiculo.Situacao.choices,
            "origens": Veiculo.Origem.choices,
            "situacao_selecionada": situacao,
            "origem_selecionada": origem,
            "ano_fabricacao_selecionado": ano_fabricacao,
            "anos": anos,
        },
    )


@perfil_requerido("GERENTE")
def detalhes_veiculo_view(request, veiculo_id):
    veiculo = get_object_or_404(
        Veiculo.objects.prefetch_related("fotos"), pk=veiculo_id
    )

    fotos = veiculo.fotos.all()
    reserva = None

    if veiculo.situacao == Veiculo.Situacao.RESERVADO:
        reserva = ReservaVeiculo.objects.filter(
            veiculo=veiculo,
            cancelada=False,
        ).first()

        if reserva:
            reserva.expirar()
            reserva.refresh_from_db()
            if reserva.cancelada:
                veiculo.refresh_from_db()
                reserva = None

    despesas = veiculo.lancamentos.filter(
        tipo=LancamentoFinanceiro.Tipo.DESPESA, excluido=False
    ).order_by("-data_lancamento", "-criado_em")

    total_despesas = despesas.aggregate(total=Sum("valor"))["total"] or 0
    custo_aquisicao = veiculo.custo_aquisicao or 0
    custo_total = custo_aquisicao + total_despesas
    ultimo_lancamento = despesas.first()

    ultimo_historico_preco = (
        veiculo.historico_precos.order_by("-alterado_em").first()
    )

    return render(
        request,
        "core/gerente_detalhes_veiculo.html",
        {
            "veiculo": veiculo,
            "fotos": fotos,
            "despesas": despesas,
            "total_despesas": total_despesas,
            "custo_total": custo_total,
            "ultimo_lancamento": ultimo_lancamento,
            "ultimo_historico_preco": ultimo_historico_preco,
            "reserva": reserva,
        
    "clientes_list": Cliente.objects.filter(ativo=True).order_by("nome", "razao_social"),}
    )


@perfil_requerido("GERENTE")
def alterar_preco_veiculo_view(request, veiculo_id):
    veiculo = get_object_or_404(Veiculo, pk=veiculo_id)

    if veiculo.venda_fechada:
        return redirect("detalhes_veiculo", veiculo_id=veiculo.id)

    despesas = veiculo.lancamentos.filter(
        tipo=LancamentoFinanceiro.Tipo.DESPESA,
        excluido=False,
    )
    total_despesas = despesas.aggregate(total=Sum("valor"))["total"] or 0
    custo_total = (veiculo.custo_aquisicao or 0) + total_despesas

    if request.method == "POST":
        if veiculo.situacao in [Veiculo.Situacao.VENDIDO, Veiculo.Situacao.ENTREGUE]:
            messages.error(
                request, "O preço não pode ser alterado após a venda do veículo."
            )
            return redirect("detalhes_veiculo", veiculo_id=veiculo.id)

        form = PrecoVendaForm(request.POST)

        if form.is_valid():
            novo_preco = form.cleaned_data["preco_venda"]
            valor_anterior = veiculo.preco_venda or 0
            abaixo_do_custo = novo_preco < custo_total

            veiculo.preco_venda = novo_preco
            veiculo.save(update_fields=["preco_venda"])

            HistoricoPrecoVeiculo.objects.create(
                veiculo=veiculo,
                valor_anterior=valor_anterior,
                valor_novo=novo_preco,
                custo_total_no_momento=custo_total,
                abaixo_do_custo=abaixo_do_custo,
                alterado_por=request.user,
            )

            if abaixo_do_custo:
                messages.warning(
                    request,
                    "Atenção: o preço de venda está abaixo do custo total acumulado.",
                )

            return redirect("detalhes_veiculo", veiculo_id=veiculo.id)
    else:
        form = PrecoVendaForm(initial={"preco_venda": veiculo.preco_venda})

    return render(
        request,
        "core/gerente_alterar_preco.html",
        {"veiculo": veiculo, "custo_total": custo_total, "form": form},
    )



@perfil_requerido("GERENTE")
def reservar_veiculo_view(request, veiculo_id):
    if request.method != "POST":
        return redirect("detalhes_veiculo", veiculo_id=veiculo_id)

    form = ReservaForm(request.POST)

    if not form.is_valid():
        erros_do_form_como_mensagens(request, form)
        return redirect("detalhes_veiculo", veiculo_id=veiculo_id)

    cliente_nome = form.cleaned_data["cliente_nome"]
    cliente_contato = form.cleaned_data["cliente_contato"]

    try:
        with transaction.atomic():
            # Bloqueia o veículo durante a operação.
            veiculo = Veiculo.objects.select_for_update().get(pk=veiculo_id)

            # Primeiro, expira as reservas vencidas.
            reservas_vencidas = veiculo.reservas.filter(
                cancelada=False,
                expira_em__lte=timezone.now(),
            )

            for antiga in reservas_vencidas:
                antiga.expirar()

            veiculo.refresh_from_db()

            # Verifica se ainda existe uma reserva válida.
            reserva_existente = veiculo.reservas.filter(
                cancelada=False,
                expira_em__gt=timezone.now(),
            ).exists()

            if (
                veiculo.situacao != Veiculo.Situacao.DISPONIVEL
                or reserva_existente
            ):
                messages.error(
                    request,
                    "Apenas veículos disponíveis e sem reserva ativa podem ser reservados."
                )
                return redirect(
                    "detalhes_veiculo",
                    veiculo_id=veiculo.id,
                )

            # Cria a reserva.
            ReservaVeiculo.objects.create(
                veiculo=veiculo,
                cliente=form.cleaned_data.get("cliente"),
                cliente_nome=cliente_nome,
                cliente_contato=cliente_contato,
                vendedor=request.user,
                expira_em=timezone.now() + timedelta(hours=24),
            )

            # Atualiza a situação operacional.
            situacao_anterior = veiculo.situacao
            veiculo.situacao = Veiculo.Situacao.RESERVADO
            veiculo.save(update_fields=["situacao"])

            # Registra a alteração no histórico.
            HistoricoSituacaoVeiculo.objects.create(
                veiculo=veiculo,
                situacao_anterior=situacao_anterior,
                situacao_nova=Veiculo.Situacao.RESERVADO,
                alterado_por=request.user,
                motivo="Reserva do veículo",
            )

    except Veiculo.DoesNotExist:
        return redirect("lista_veiculos")

    except IntegrityError:
        messages.error(
            request,
            "Este veículo já possui uma reserva ativa."
        )
        return redirect(
            "detalhes_veiculo",
            veiculo_id=veiculo_id,
        )

    messages.success(request, "Veículo reservado com sucesso.")

    return redirect("detalhes_veiculo", veiculo_id=veiculo_id)


@perfil_requerido("GERENTE", "ADMINISTRATIVO")
def alterar_situacao_veiculo_view(request, veiculo_id):
    veiculo = get_object_or_404(Veiculo, pk=veiculo_id)

    if request.method != "POST":
        return redirect("detalhes_veiculo", veiculo_id=veiculo.id)

    form = AlterarSituacaoForm(request.POST)

    if not form.is_valid():
        erros_do_form_como_mensagens(request, form)
        return redirect("detalhes_veiculo", veiculo_id=veiculo.id)

    nova_situacao = form.cleaned_data["situacao"]
    motivo = form.cleaned_data["motivo"]
    cliente = form.cleaned_data.get("cliente")

    transicoes_permitidas = {
        Veiculo.Situacao.PREPARACAO: [Veiculo.Situacao.DISPONIVEL],
        Veiculo.Situacao.DISPONIVEL: [Veiculo.Situacao.RESERVADO],
        Veiculo.Situacao.RESERVADO: [
            Veiculo.Situacao.DISPONIVEL,
            Veiculo.Situacao.VENDIDO,
        ],
        Veiculo.Situacao.VENDIDO: [Veiculo.Situacao.ENTREGUE],
        Veiculo.Situacao.ENTREGUE: [],
    }
    if nova_situacao == Veiculo.Situacao.VENDIDO:
        aprovacao_em_aberto = veiculo.propostas.filter(
            status_aprovacao__in=[
                Proposta.StatusAprovacao.PENDENTE,
                Proposta.StatusAprovacao.CONTRAPROPOSTA,
            ],
        ).exclude(situacao=Proposta.Situacao.CANCELADA).exists()

        if aprovacao_em_aberto:
            messages.error(
                request,
                "Há proposta aguardando decisão do gerente ou resposta do vendedor. "
                "Resolva antes de registrar a venda.",
            )
            return redirect("detalhes_veiculo", veiculo_id=veiculo.id)
    if nova_situacao not in transicoes_permitidas.get(veiculo.situacao, []):
        messages.error(request, "Essa transição de situação não é permitida.")
        return redirect("detalhes_veiculo", veiculo_id=veiculo.id)

    situacao_anterior = veiculo.situacao
    veiculo.situacao = nova_situacao

    update_fields = ["situacao", "status", "venda_fechada"]

    if nova_situacao in [Veiculo.Situacao.PREPARACAO, Veiculo.Situacao.DISPONIVEL]:
        veiculo.status = Veiculo.Status.DISPONIVEL
    elif nova_situacao == Veiculo.Situacao.RESERVADO:
        veiculo.status = Veiculo.Status.RESERVADO
    elif nova_situacao in [Veiculo.Situacao.VENDIDO, Veiculo.Situacao.ENTREGUE]:
        veiculo.status = Veiculo.Status.VENDIDO
        veiculo.venda_fechada = True

    if nova_situacao == Veiculo.Situacao.VENDIDO:
        veiculo.cliente_comprador = cliente
        update_fields.append("cliente_comprador")

    veiculo.save(update_fields=update_fields)

    HistoricoSituacaoVeiculo.objects.create(
        veiculo=veiculo,
        situacao_anterior=situacao_anterior,
        situacao_nova=nova_situacao,
        alterado_por=request.user,
        motivo=motivo or None,
    )

    messages.success(request, "Situação do veículo alterada com sucesso.")
    return redirect("detalhes_veiculo", veiculo_id=veiculo.id)


def vitrine_view(request):
    estoque = Veiculo.objects.filter(
        situacao=Veiculo.Situacao.DISPONIVEL,
        status=Veiculo.Status.DISPONIVEL,
    )

    marca = request.GET.get("marca", "").strip()
    preco = request.GET.get("preco", "").strip()
    ano = request.GET.get("ano", "").strip()
    combustivel = request.GET.get("combustivel", "").strip()

    veiculos = (
        estoque.only(
            "id",
            "marca",
            "modelo",
            "ano_fabricacao",
            "ano_modelo",
            "cor",
            "combustivel",
            "quilometragem",
            "preco_venda",
            "criado_em",
        )
        .prefetch_related("fotos")
        .order_by("-criado_em")
    )

    if marca:
        veiculos = veiculos.filter(marca__icontains=marca)

    if preco:
        try:
            preco_maximo = Decimal(preco.replace(",", "."))
            if preco_maximo >= 0:
                veiculos = veiculos.filter(preco_venda__lte=preco_maximo)
        except (InvalidOperation, ValueError):
            preco = ""

    if ano:
        try:
            ano_filtro = int(ano)
            if 1900 <= ano_filtro <= 2100:
                veiculos = veiculos.filter(
                    Q(ano_fabricacao=ano_filtro) | Q(ano_modelo=ano_filtro)
                )
        except (ValueError, TypeError):
            ano = ""

    if combustivel:
        veiculos = veiculos.filter(combustivel__icontains=combustivel)

    marcas = (
        estoque.order_by()
        .values_list("marca", flat=True)
        .distinct()
        .order_by("marca")
    )

    combustiveis = (
        estoque.order_by()
        .values_list("combustivel", flat=True)
        .distinct()
        .order_by("combustivel")
    )

    anos = sorted(
        set(estoque.values_list("ano_fabricacao", flat=True))
        | set(estoque.values_list("ano_modelo", flat=True)),
        reverse=True,
    )

    contexto = {
        "veiculos": veiculos,
        "marcas": marcas,
        "anos": anos,
        "combustiveis": combustiveis,
        "filtros": {
            "marca": marca,
            "preco": preco,
            "ano": ano,
            "combustivel": combustivel,
        },
    }

    return render(request, "core/vitrine.html", contexto)


def vitrine_veiculo_detalhe_view(request, pk):
    campos_publicos = (
        "id",
        "marca",
        "modelo",
        "ano_fabricacao",
        "ano_modelo",
        "cor",
        "combustivel",
        "quilometragem",
        "preco_venda",
        "opcionais",
    )

    veiculo = get_object_or_404(
        Veiculo.objects.filter(
            situacao=Veiculo.Situacao.DISPONIVEL,
            status=Veiculo.Status.DISPONIVEL,
        ).values(*campos_publicos),
        pk=pk,
    )

    fotos = Veiculo.objects.get(pk=veiculo["id"]).fotos.all()

    return render(
        request,
        "core/vitrine_veiculo_detalhe.html",
        {
            "veiculo": veiculo,
            "fotos": fotos,
        },
    )


@login_required
def clientes_view(request):
    busca = request.GET.get("busca", "").strip()

    clientes = Cliente.objects.prefetch_related("telefones")

    if busca:
        clientes = clientes.filter(
            Q(nome__icontains=busca)
            | Q(razao_social__icontains=busca)
            | Q(nome_fantasia__icontains=busca)
            | Q(cpf__icontains=busca)
            | Q(cnpj__icontains=busca)
            | Q(telefones__numero__icontains=busca)
        ).distinct()

    clientes = clientes.order_by("nome", "razao_social")

    return render(
        request,
        "core/vendedor_painel_clientes.html",
        {
            "clientes": clientes,
            "busca": busca,
        },
    )

@login_required
def cadastrar_cliente_view(request):
    cliente = Cliente()

    if request.method == "POST":
        form = ClienteForm(request.POST, instance=cliente)
        formset = TelefoneClienteFormSet(request.POST, instance=cliente)

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    cliente = form.save()
                    formset.instance = cliente
                    formset.save()

                messages.success(request, "Cliente cadastrado com sucesso.")
                # ALTERE AQUI: redireciona para a lista de clientes em vez dos detalhes
                return redirect("clientes")

            except IntegrityError:
                form.add_error(
                    None,
                    "Não foi possível cadastrar: o CPF ou CNPJ informado já está registrado.",
                )
    else:
        form = ClienteForm(instance=cliente)
        formset = TelefoneClienteFormSet(instance=cliente)

    return render(
        request,
        "core/vendedor_cliente_form.html",
        {
            "form": form,
            "formset": formset,
            "titulo": "Cadastrar cliente",
        },
    )

@login_required
def detalhes_cliente_view(request, cliente_id):
    cliente = get_object_or_404(
        Cliente.objects.prefetch_related("telefones"),
        pk=cliente_id,
    )

    # 1. Veículos que este cliente comprou
    veiculos_comprados = Veiculo.objects.filter(
        cliente_comprador=cliente
    ).prefetch_related("fotos").order_by("-criado_em")

    propostas = (
        cliente.propostas.select_related("veiculo", "vendedor")
        .order_by("-criada_em")
    )
    return render(
    request,
    "core/vendedor_cliente_detalhes.html",
    {
        "cliente": cliente,
        "veiculos_comprados": veiculos_comprados,
        "propostas": propostas,  # <- Altere apenas esta linha!
    },
)

@login_required
def editar_cliente_view(request, cliente_id):
    cliente = get_object_or_404(Cliente, pk=cliente_id)

    if request.method == "POST":
        form = ClienteForm(request.POST, instance=cliente)
        formset = TelefoneClienteFormSet(request.POST, instance=cliente)

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    cliente = form.save()
                    formset.instance = cliente
                    formset.save()

                messages.success(request, "Cliente atualizado com sucesso.")
                return redirect("detalhes_cliente", cliente_id=cliente.pk)

            except IntegrityError:
                form.add_error(
                    None,
                    "Não foi possível atualizar: o CPF ou CNPJ informado já está registrado.",
                )
    else:
        form = ClienteForm(instance=cliente)
        formset = TelefoneClienteFormSet(instance=cliente)

    return render(
        request,
        "core/vendedor_cliente_form.html",
        {
            "form": form,
            "formset": formset,
            "titulo": "Editar cliente",
        },
    )


@login_required
def desativar_cliente_view(request, cliente_id):
    cliente = get_object_or_404(Cliente, pk=cliente_id)

    if request.method == "POST":
        cliente.desativar()
        messages.success(request, "Cliente desativado com sucesso.")
        return redirect("clientes")

    return render(
        request,
        "core/vendedor_cliente_confirmar_desativacao.html",
        {"cliente": cliente},
    )


@login_required
def deletar_cliente_view(request, cliente_id):
    cliente = get_object_or_404(Cliente, pk=cliente_id)

    if request.method == "POST":
        try:
            cliente.delete()
            messages.success(request, "Cliente excluído com sucesso.")
            return redirect("clientes")
        except ProtectedError:
            messages.error(
                request,
                "Não é possível excluir este cliente pois ele possui veículos com vendas registradas. "
                "Para inativá-lo, utilize a opção de desativação.",
            )
            return redirect("detalhes_cliente", cliente_id=cliente.id)

    return render(
        request,
        "core/vendedor_cliente_confirmar_exclusao.html",
        {"cliente": cliente},
    )
    



def expirar_reservas_vencidas():
    """
    Fecha as reservas vencidas. Não existe agendador: a expiração acontece
    quando alguém abre uma tela. Por isso as telas de proposta chamam isto
    antes de decidir se uma proposta ainda está "aguardando".
    (Você pode trocar o `for` de veiculos_view por uma chamada a esta função.)
    """
    for reserva in ReservaVeiculo.objects.filter(
        cancelada=False, expira_em__lte=timezone.now()
    ):
        reserva.expirar()
 
 
def _propostas_visiveis(usuario):
    """Vendedor enxerga só as próprias propostas. Quando o gerente for liberado, vê todas."""
    propostas = Proposta.objects.select_related("cliente", "veiculo", "vendedor")
    if usuario.is_vendedor():
        propostas = propostas.filter(vendedor=usuario)
    return propostas
 
 
def _dados_veiculos_para_js(veiculos):
    """
    {id_do_veiculo: {preco, reservado, reserva_expira}} para o JavaScript
    mostrar o preço de tabela e o aviso de reserva ao escolher o veículo.
    """
    reservas = {
        r.veiculo_id: r
        for r in ReservaVeiculo.objects.filter(
            veiculo__in=veiculos,
            cancelada=False,
            expira_em__gt=timezone.now(),
        )
    }
    dados = {}
    for veiculo in veiculos:
        reserva = reservas.get(veiculo.pk)
        dados[str(veiculo.pk)] = {
            "preco": str(veiculo.preco_venda),
            "reservado": reserva is not None,
            "reserva_expira": (
                timezone.localtime(reserva.expira_em).strftime("%d/%m/%Y %H:%M")
                if reserva
                else ""
            ),
        }
    return dados
 
 
# ---------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------
 
@perfil_requerido("VENDEDOR")
def propostas_view(request):
    expirar_reservas_vencidas()

    filtros_form = PropostaFiltroForm(request.GET or None)
    propostas = _propostas_visiveis(request.user)

    if filtros_form.is_valid():
        cliente = filtros_form.cleaned_data.get("cliente")
        veiculo = filtros_form.cleaned_data.get("veiculo")
        situacao = filtros_form.cleaned_data.get("situacao")
        vendedor = filtros_form.cleaned_data.get("vendedor")

        if cliente:
            propostas = propostas.filter(cliente=cliente)

        if veiculo:
            propostas = propostas.filter(veiculo=veiculo)

        if situacao:
            propostas = propostas.filter(situacao=situacao)

        if vendedor:
            propostas = propostas.filter(vendedor=vendedor)

    propostas = propostas.order_by("-criada_em")

    return render(
        request,
        "core/vendedor_painel_propostas.html",
        {
            "propostas": propostas,
            "filtros_form": filtros_form,
        },
    )
 
# ---------------------------------------------------------------------
# Criar / editar (mesma tela)
# ---------------------------------------------------------------------
 
def _proposta_form_view(request, proposta, titulo):
    editando = proposta.pk is not None
 
    if request.method == "POST":
        form = PropostaForm(request.POST, instance=proposta)
        formset = ComposicaoFormSet(request.POST, instance=proposta)
 
        # Ordem importa: o formset precisa saber o valor oferecido ANTES de
        # validar, para conferir se a soma da composição fecha.
        form_valido = form.is_valid()
        formset.valor_oferecido = form.cleaned_data.get("valor_oferecido")
 
        if form_valido and formset.is_valid():
            with transaction.atomic():
                proposta = form.save(commit=False)
                if not editando:
                    proposta.vendedor = request.user
                proposta.save(usuario=request.user)  # grava o histórico de valor
 
                formset.instance = proposta
                formset.save()
 
            if proposta.situacao == Proposta.Situacao.AGUARDANDO:

                if proposta.reserva_aguardada:
                    prazo = timezone.localtime(proposta.reserva_aguardada.expira_em)

                    messages.warning(
                        request,
                        "Proposta registrada como AGUARDANDO: o veículo está reservado "
                        f"até {prazo:%d/%m/%Y %H:%M}. Ela só será ativada se a reserva vencer.",
                    )

                else:
                    messages.warning(
                        request,
                        "Proposta registrada como AGUARDANDO: já existe outra proposta ativa "
                        "para este veículo. Ela será ativada quando chegar sua vez na fila.",
                    )

            else:
                messages.success(
                    request,
                    "Proposta atualizada com sucesso."
                    if editando
                    else "Proposta registrada com sucesso.",
                )
            return redirect("detalhes_proposta", proposta_id=proposta.pk)
    else:
        initial = {}
        if not editando:
            # Permite abrir a tela já preenchida: ?cliente=3&veiculo=7
            for campo in ("cliente", "veiculo"):
                valor = request.GET.get(campo, "")
                if valor.isdigit():
                    initial[campo] = int(valor)
 
        form = PropostaForm(instance=proposta, initial=initial)
        formset = ComposicaoFormSet(instance=proposta)
 
    return render(
        request,
        "core/vendedor_painel_proposta_formulario.html",
        {
            "form": form,
            "formset": formset,
            "titulo": titulo,
            "proposta": proposta if editando else None,
            "veiculos_info": _dados_veiculos_para_js(form.fields["veiculo"].queryset),
        },
    )
 
 
@perfil_requerido("VENDEDOR")
def nova_proposta_view(request):
    expirar_reservas_vencidas()
    return _proposta_form_view(request, Proposta(), "Nova proposta")
 
 
@perfil_requerido("VENDEDOR")
def editar_proposta_view(request, proposta_id):
    expirar_reservas_vencidas()
    proposta = get_object_or_404(_propostas_visiveis(request.user), pk=proposta_id)
 
    if proposta.situacao == Proposta.Situacao.CANCELADA:
        messages.error(request, "Proposta cancelada não pode ser editada.")
        return redirect("detalhes_proposta", proposta_id=proposta.pk)
 
    if proposta.veiculo.situacao in (
        Veiculo.Situacao.VENDIDO,
        Veiculo.Situacao.ENTREGUE,
    ):
        messages.error(
            request,
            "O veículo desta proposta já foi vendido; a proposta não pode mais ser editada.",
        )
        return redirect("detalhes_proposta", proposta_id=proposta.pk)
 
    return _proposta_form_view(request, proposta, "Editar proposta")
 
 
# ---------------------------------------------------------------------
# Detalhes
# ---------------------------------------------------------------------
 
@perfil_requerido("VENDEDOR")
def detalhes_proposta_view(request, proposta_id):
    expirar_reservas_vencidas()
    proposta = get_object_or_404(_propostas_visiveis(request.user), pk=proposta_id)
 
    return render(
        request,
        "core/vendedor_painel_proposta_detalhe.html",
        {
            "proposta": proposta,
            "composicao": proposta.composicao.all(),
            "historico": proposta.historico.select_related("alterado_por"),
            "reserva": (
                proposta.reserva_aguardada
                if proposta.situacao == Proposta.Situacao.AGUARDANDO
                else None
            ),
        },
    )
 
 
# ---------------------------------------------------------------------
# Painel inicial do vendedor: SUBSTITUA a painel_vendedor_view existente por esta
# ---------------------------------------------------------------------
 
@perfil_requerido("VENDEDOR")
def painel_vendedor_view(request):
    expirar_reservas_vencidas()
 
    dados = get_object_or_404(PerfilVendedor, usuario=request.user)
    veiculos = Veiculo.objects.all().order_by("-criado_em")
    propostas = _propostas_visiveis(request.user).order_by("-criada_em")[:5]
 
    return render(
        request,
        "core/vendedor_painel_inicio.html",
        {"dados": dados, "veiculos": veiculos, "propostas": propostas},
    )
# ---------------------------------------------------------------------
# T09: aprovação de desconto pelo gerente
# ---------------------------------------------------------------------

@perfil_requerido("GERENTE")
def aprovacoes_view(request):
    propostas = (
        Proposta.objects.filter(
            status_aprovacao=Proposta.StatusAprovacao.PENDENTE
        )
        .select_related(
            "cliente",
            "veiculo",
            "vendedor",
            "vendedor__dados_vendedor",
        )
        .order_by("criada_em")
    )

    return render(
        request,
        "core/gerente_painel_aprovacoes.html",
        {"propostas": propostas},
    )

@perfil_requerido("GERENTE")
def decidir_proposta_view(request, proposta_id):
    proposta = get_object_or_404(
        Proposta.objects.select_related(
            "cliente",
            "veiculo",
            "vendedor",
            "vendedor__dados_vendedor",
        ),
        pk=proposta_id,
    )

    if request.method == "POST":
        form = DecisaoPropostaForm(request.POST)

        if form.is_valid():
            cd = form.cleaned_data

            try:
                with transaction.atomic():
                    # Busca novamente e bloqueia a proposta durante a decisão.
                    proposta = (
                        Proposta.objects
                        .select_for_update()
                        .get(pk=proposta_id)
                    )

                    # Impede que uma proposta já decidida seja decidida novamente.
                    if (
                        proposta.status_aprovacao
                        != Proposta.StatusAprovacao.PENDENTE
                    ):
                        messages.error(
                            request,
                            "Esta proposta já foi decidida.",
                        )
                        return redirect("negociacoes_gerente")

                    proposta.decidir(
                        request.user,
                        cd["acao"],
                        parecer=cd["parecer"],
                        novo_valor=cd["novo_valor"],
                    )

                messages.success(
                    request,
                    "Decisão registrada com sucesso.",
                )
                return redirect("negociacoes_gerente")

            except ValidationError as erro:
                adicionar_erros_de_validacao(form, erro)
            
            
            except PermissionDenied as erro:
                messages.error(request, str(erro))
                return redirect("negociacoes_gerente")

    else:
        form = DecisaoPropostaForm()

    proposta = get_object_or_404(
        Proposta.objects.select_related(
            "cliente",
            "veiculo",
            "vendedor",
            "vendedor__dados_vendedor",
        ),
        pk=proposta_id,
    )

    return render(
        request,
        "core/gerente_decidir_proposta.html",
        {
            "proposta": proposta,
            "perfil": proposta.alcada_vendedor,
            "decisoes": proposta.decisoes.select_related("feito_por"),
            "historico": proposta.historico.select_related("alterado_por"),
            "form": form,
        },
    )

@perfil_requerido("GERENTE")
def negociacoes_view(request):
    expirar_reservas_vencidas()

    propostas = (
        Proposta.objects
        .select_related(
            "cliente",
            "veiculo",
            "vendedor",
        )
        .order_by("-criada_em")
    )

    situacao = request.GET.get("situacao", "")

    situacoes_validas = [
        valor for valor, rotulo in Proposta.Situacao.choices
    ]

    if situacao in situacoes_validas:
        propostas = propostas.filter(situacao=situacao)
    else:
        situacao = ""

    indicadores = {
        "total": Proposta.objects.count(),
        "aguardando": Proposta.objects.filter(
            situacao=Proposta.Situacao.AGUARDANDO_GERENTE
        ).count(),
        "aprovadas": Proposta.objects.filter(
            situacao=Proposta.Situacao.APROVADA
        ).count(),
        "recusadas": Proposta.objects.filter(
            situacao=Proposta.Situacao.RECUSADA
        ).count(),
        "contrapropostas": Proposta.objects.filter(
            situacao=Proposta.Situacao.CONTRAPROPOSTA
        ).count(),
    }

    return render(
        request,
        "core/gerente_painel_negociacoes.html",
        {
            "propostas": propostas,
            "situacoes": Proposta.Situacao.choices,
            "situacao_selecionada": situacao,
            "indicadores": indicadores,
        },
    )
@perfil_requerido("VENDEDOR")
def aceitar_contraproposta_view(request, proposta_id):
    if request.method != "POST":
        return redirect("propostas")

    proposta = get_object_or_404(
        Proposta,
        pk=proposta_id,
    )

    try:
        proposta.aceitar_contraproposta(request.user)

    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))

    except PermissionDenied as erro:
        messages.error(request, str(erro))

    else:
        messages.success(
            request,
            "Contraproposta aceita com sucesso!",
        )

    return redirect(
        "detalhes_proposta",
        proposta_id=proposta.pk,
    )
    
    
@perfil_requerido("VENDEDOR")
def recusar_contraproposta_view(request, proposta_id):
    if request.method != "POST":
        return redirect("propostas")

    proposta = get_object_or_404(
        _propostas_visiveis(request.user),
        pk=proposta_id,
    )

    try:
        proposta.recusar_contraproposta(request.user)

    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))

    except PermissionDenied as erro:
        messages.error(request, str(erro))

    else:
        messages.success(
            request,
            "Contraproposta recusada. Se quiser, registre uma nova proposta.",
        )

    return redirect("detalhes_proposta", proposta_id=proposta.pk)