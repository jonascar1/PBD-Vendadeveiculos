


from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models.aggregates import Sum
from django.shortcuts import render, redirect, get_object_or_404

from .decorators import perfil_requerido
from .models import HistoricoPrecoVeiculo, HistoricoSituacaoVeiculo, LancamentoFinanceiro, Usuario, PerfilVendedor, Veiculo, FotoVeiculo
from .models import (HistoricoSituacaoVeiculo,Usuario,PerfilVendedor,Veiculo,FotoVeiculo,ReservaVeiculo,)

from django.db import transaction
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        usuario = authenticate(request, username=username, password=password)

        # Erro genérico de propósito: não dizer se foi usuário ou senha
        # errada, nem se a conta está desativada — isso é informação
        # que ajuda quem está tentando invadir.
        erro_generico = "Usuário ou senha inválidos."
        erro_ativo = "Usuário inativo. Contate o gerente."

        if usuario is None or not usuario.ativo:
            if usuario and not usuario.ativo:
                messages.error(request, erro_ativo)
            else:
                messages.error(request, erro_generico)
            return render(request, "core/login.html")

        login(request, usuario)
        return redirect("painel")

    return render(request, "core/login.html")


@login_required
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def painel_view(request):
    """
    Um único ponto de entrada pós-login que redireciona (ou renderiza)
    o painel certo pro perfil do usuário. O template escolhido já
    mostra só as opções daquele perfil — não é a mesma tela com botões
    escondidos via CSS/JS.
    """
    usuario = request.user

    if usuario.is_gerente():
        return redirect("painel_gerente")
    elif usuario.is_vendedor():
        return redirect("painel_vendedor")
    elif usuario.is_administrativo():
        return redirect("painel_administrativo")

    # Perfil não reconhecido: nega por padrão, nunca libera por engano.
    logout(request)
    messages.error(request, "Perfil de usuário inválido. Contate o gerente.")
    return redirect("login")


@perfil_requerido("GERENTE")
def painel_gerente_view(request):
    vendedores = PerfilVendedor.objects.select_related("usuario").all()
    return render(request, "core/gerente_painel_inicio.html", {"vendedores": vendedores})


@perfil_requerido("VENDEDOR")
def painel_vendedor_view(request):
    dados = get_object_or_404(PerfilVendedor, usuario=request.user)

    veiculos = Veiculo.objects.all().order_by("-criado_em")

    return render(request,"core/painel_vendedor.html",{"dados": dados,"veiculos": veiculos,},)

@perfil_requerido("ADMINISTRATIVO")
def painel_administrativo_view(request):
    return render(request, "core/administrativo_painel_inicio.html")

@perfil_requerido("ADMINISTRATIVO")
def despesas_view(request):
    veiculos = (
        Veiculo.objects
        .prefetch_related("fotos")
        .all()
        .order_by("marca", "modelo")
    )

    

    total_despesas = LancamentoFinanceiro.objects.filter(
        tipo=LancamentoFinanceiro.Tipo.DESPESA,
        excluido=False,
    ).count()

    valor_total = (
        LancamentoFinanceiro.objects
        .filter(tipo=LancamentoFinanceiro.Tipo.DESPESA,
                excluido=False)
        .aggregate(total=Sum("valor"))["total"]
        or 0
    )

    veiculos_com_despesas = (
        Veiculo.objects
        .filter(
            lancamentos__tipo=LancamentoFinanceiro.Tipo.DESPESA,
            lancamentos__excluido=False
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
        }
    )

@perfil_requerido("ADMINISTRATIVO")
def despesas_veiculo_view(request, veiculo_id):
    veiculo = get_object_or_404(Veiculo, pk=veiculo_id)

    despesas = veiculo.lancamentos.filter(
        tipo=LancamentoFinanceiro.Tipo.DESPESA,
        excluido=False,
    ).order_by("-data_lancamento", "-criado_em")

    total_despesas = sum(
        despesa.valor for despesa in despesas
    )

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
        valor = request.POST.get("valor")
        data_lancamento = request.POST.get("data_lancamento")
        descricao = request.POST.get("descricao")

        LancamentoFinanceiro.objects.create(
            veiculo=veiculo,
            tipo=LancamentoFinanceiro.Tipo.DESPESA,
            valor=valor,
            data_lancamento=data_lancamento,
            descricao=descricao,
            registrado_por=request.user,
        )

        return redirect("despesas_veiculo", veiculo_id=veiculo.id)

    return render(
        request,
        "core/administrativo_adicionar_despesa.html",
        {
            "veiculo": veiculo,
        },
    )

@perfil_requerido("ADMINISTRATIVO")
def editar_despesa_view(request, despesa_id):
    despesa = get_object_or_404(
        LancamentoFinanceiro,
        pk=despesa_id,
        tipo=LancamentoFinanceiro.Tipo.DESPESA,
    )

    if request.method == "POST":
        despesa.valor = request.POST.get("valor")
        despesa.data_lancamento = request.POST.get("data_lancamento")
        despesa.descricao = request.POST.get("descricao")

        despesa.editado_por = request.user
        despesa.editado_em = timezone.now()

        despesa.save()

        return redirect(
            "despesas_veiculo",
            veiculo_id=despesa.veiculo.id
        )

    return render(
        request,
        "core/administrativo_editar_despesa.html",
        {
            "despesa": despesa,
            "veiculo": despesa.veiculo,
        },
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

        return redirect(
            "despesas_veiculo",
            veiculo_id=despesa.veiculo.id
        )

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
        pk=vendedor_id
    )


    usuario = dados.usuario

    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        email = request.POST.get("email", "").strip()
        ativo = request.POST.get("ativo") == "true"

        tipo_alcada = request.POST.get(
            "tipo_alcada",
            dados.tipo_alcada
        )

        valor_alcada = request.POST.get(
            "valor_alcada",
            dados.valor_alcada
        )

        percentual_comissao = request.POST.get(
            "percentual_comissao",
            dados.percentual_comissao
        )

        if not nome:
            messages.error(
                request,
                "O nome do vendedor é obrigatório."
            )

            return render(
                request,
                "core/gerente_editar_vendedor.html",
                {"dados": dados}
            )

        try:
            # ==========================
            # DADOS DA CONTA
            # ==========================

            usuario.first_name = nome
            usuario.email = email
            usuario.ativo = ativo
            usuario.save()

            # ==========================
            # DADOS COMERCIAIS
            # ==========================

            dados.tipo_alcada = tipo_alcada
            dados.valor_alcada = valor_alcada
            dados.percentual_comissao = percentual_comissao
            dados.editado_por = request.user

            dados.full_clean()
            dados.save()

            messages.success(
                request,
                "Dados do vendedor atualizados com sucesso."
            )

            return redirect("vendedores")

        except ValidationError:
            messages.error(
                request,
                "Verifique os valores informados."
            )
    

    return render(
    request,
    "core/gerente_editar_vendedor.html",
    {"dados": dados}
)

@perfil_requerido("GERENTE")
def vendedores_view(request):
    vendedores = PerfilVendedor.objects.select_related("usuario").all()

    return render(
        request,
        "core/gerente_painel_vendedores.html",
        {"vendedores": vendedores}
    )

@perfil_requerido("GERENTE")
def cadastrar_vendedor_view(request):

    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        senha = request.POST.get("senha", "")

        tipo_alcada = request.POST.get(
            "tipo_alcada",
            PerfilVendedor.TipoAlcada.PERCENTUAL
        )

        valor_alcada = request.POST.get(
            "valor_alcada",
            "0"
        )

        percentual_comissao = request.POST.get(
            "percentual_comissao",
            "0"
        )

        if not nome or not username or not senha:
            messages.error(request, "Preencha os campos obrigatórios.")
            return render(
                request,
                "core/gerente_cadastrar_vendedor.html"
            )

        if Usuario.objects.filter(username=username).exists():
            messages.error(request, "Esse usuário já está cadastrado.")
            return render(
                request,
                "core/gerente_cadastrar_vendedor.html"
            )

        try:
            with transaction.atomic():

                usuario = Usuario(
                    username=username,
                    email=email,
                    perfil=Usuario.Perfil.VENDEDOR,
                    ativo=True
                )

                usuario.set_password(senha)
                usuario.first_name = nome

                usuario.full_clean()
                usuario.save()

                PerfilVendedor.objects.create(
                    usuario=usuario,
                    tipo_alcada=tipo_alcada,
                    valor_alcada=valor_alcada,
                    percentual_comissao=percentual_comissao,
                    editado_por=request.user
                )

            messages.success(
                request,
                "Vendedor cadastrado com sucesso."
            )

            return redirect("vendedores")

        except Exception:
            messages.error(
                request,
                "Não foi possível cadastrar o vendedor. Verifique os dados."
            )

    return render(
        request,
        "core/gerente_cadastrar_vendedor.html"
    )
@perfil_requerido("GERENTE")
def cadastrar_veiculo_view(request):

    if request.method == "POST":

        placa = request.POST.get("placa", "").strip()
        chassi = request.POST.get("chassi", "").strip()
        renavam = request.POST.get("renavam", "").strip()

        marca = request.POST.get("marca", "").strip()
        modelo = request.POST.get("modelo", "").strip()

        ano_fabricacao = request.POST.get("ano_fabricacao", "").strip()
        ano_modelo = request.POST.get("ano_modelo", "").strip()

        cor = request.POST.get("cor", "").strip()
        combustivel = request.POST.get("combustivel", "").strip()
        quilometragem = request.POST.get("quilometragem", "").strip()

        opcionais = request.POST.get("opcionais", "").strip()

        origem = request.POST.get("origem", "").strip()

        custo_aquisicao = request.POST.get("custo_aquisicao","").strip()

        valor_repasse = request.POST.get("valor_repasse","").strip()
        
        preco_venda = request.POST.get("preco_venda","").strip()
        
        


        # CAMPOS OBRIGATÓRIOS

        if not all([
            placa,
            chassi,
            renavam,
            marca,
            modelo,
            ano_fabricacao,
            ano_modelo,
            cor,
            combustivel,
            quilometragem,
            origem
        ]):

            messages.error(
                request,
                "Preencha todos os campos obrigatórios."
            )

            return render(
                request,
                "core/gerente_cadastrar_veiculo.html"
            )


        try:

            veiculo = Veiculo(
                placa=placa,
                chassi=chassi,
                renavam=renavam,
                marca=marca,
                modelo=modelo,
                ano_fabricacao=ano_fabricacao,
                ano_modelo=ano_modelo,
                cor=cor,
                combustivel=combustivel,
                quilometragem=quilometragem,
                opcionais=opcionais,
                origem=origem,
                custo_aquisicao=custo_aquisicao or None,
                valor_repasse=valor_repasse or None,
                preco_venda=preco_venda or None,
                criado_por=request.user
            )

            veiculo.full_clean()
            veiculo.save()

            fotos = request.FILES.getlist("fotos")

            for ordem, imagem in enumerate(fotos):
                FotoVeiculo.objects.create(
                    veiculo=veiculo,
                    imagem=imagem,
                    ordem=ordem,
                    principal=(ordem == 0)
                )


            messages.success(
                request,
                "Veículo cadastrado com sucesso."
            )

            return redirect("painel_gerente")


        except ValidationError as erro:

            if hasattr(erro, "message_dict"):

                for campo, erros in erro.message_dict.items():

                    for mensagem in erros:

                        messages.error(
                            request,
                            mensagem
                        )

            else:

                messages.error(
                    request,
                    "Verifique os dados informados."
                )


        except IntegrityError:

            messages.error(
                request,
                "Já existe um veículo com essa placa ou chassi no estoque."
            )


    return render(
        request,
        "core/gerente_cadastrar_veiculo.html"
    )
    
@perfil_requerido("GERENTE")
def veiculos_view(request):
    for reserva in ReservaVeiculo.objects.filter(cancelada=False,expira_em__lte=timezone.now(),):
        reserva.expirar()
    veiculos = Veiculo.objects.prefetch_related("fotos").all().order_by("-criado_em")

    return render(
        request,
        "core/gerente_painel_veiculos.html",
        {"veiculos": veiculos}
    )

@perfil_requerido("GERENTE")
def detalhes_veiculo_view(request, veiculo_id):
    veiculo = get_object_or_404(
        Veiculo.objects.prefetch_related("fotos"),
        pk=veiculo_id
    )

    fotos = veiculo.fotos.all()

    despesas = veiculo.lancamentos.filter(
        tipo=LancamentoFinanceiro.Tipo.DESPESA,
        excluido=False
        ).order_by("-data_lancamento", "-criado_em")

    total_despesas = despesas.aggregate(total=Sum("valor"))["total"] or 0

    custo_aquisicao = veiculo.custo_aquisicao or 0

    custo_total = custo_aquisicao + total_despesas

    ultimo_lancamento = despesas.first()

    ultimo_historico_preco = (
    veiculo.historico_precos
    .order_by("-alterado_em")
    .first()
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
        }
    )

@perfil_requerido("GERENTE")
def alterar_preco_veiculo_view(request, veiculo_id):
    veiculo = get_object_or_404(Veiculo, pk=veiculo_id)

    if veiculo.venda_fechada:
        return redirect("detalhes_veiculo",veiculo_id=veiculo.id,)

    despesas = veiculo.lancamentos.filter(tipo=LancamentoFinanceiro.Tipo.DESPESA,excluido=False,)

    total_despesas = (
        despesas.aggregate(total=Sum("valor"))["total"]or 0)

    custo_total = ((veiculo.custo_aquisicao or 0)+ total_despesas)

    if request.method == "POST":

        if veiculo.situacao in [
        Veiculo.Situacao.VENDIDO,
        Veiculo.Situacao.ENTREGUE,]:
            messages.error(request,"O preço não pode ser alterado após a venda do veículo.")
            
            return redirect("detalhes_veiculo",veiculo_id=veiculo.id,)

    novo_preco = request.POST.get("preco_venda")
    
    if novo_preco:
            try:
                novo_preco = Decimal(novo_preco)
            except (InvalidOperation, TypeError):
                return render(
                    request,
                    "core/gerente_alterar_preco.html",
                    {
                        "veiculo": veiculo,
                        "erro_preco": "Informe um preço válido.",
                    },
                )

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
                    "Atenção: o preço de venda está abaixo do custo total acumulado."
                )

            return redirect(
                "detalhes_veiculo",
                veiculo_id=veiculo.id,
            )

    return render(
        request,
        "core/gerente_alterar_preco.html",
        {
            "veiculo": veiculo,
            "custo_total": custo_total,
        },
    )
@perfil_requerido("GERENTE")
def reservar_veiculo_view(request, veiculo_id):
    veiculo = get_object_or_404(Veiculo, pk=veiculo_id)

    if request.method != "POST":
        return redirect(
            "detalhes_veiculo",
            veiculo_id=veiculo.id,
        )

    cliente_nome = request.POST.get("cliente_nome", "").strip()
    cliente_contato = request.POST.get("cliente_contato", "").strip()

    if not cliente_nome or not cliente_contato:
        messages.error(
            request,
            "Informe o nome e o contato do cliente."
        )
        return redirect(
            "detalhes_veiculo",
            veiculo_id=veiculo.id,
        )

    if veiculo.situacao != Veiculo.Situacao.DISPONIVEL:
        messages.error(
            request,
            "Apenas veículos disponíveis podem ser reservados."
        )
        return redirect(
            "detalhes_veiculo",
            veiculo_id=veiculo.id,
        )

    reserva, criada = ReservaVeiculo.objects.get_or_create(
    veiculo=veiculo,
    defaults={
        "cliente_nome": cliente_nome,
        "cliente_contato": cliente_contato,
        "vendedor": request.user,
        "expira_em": timezone.now() + timedelta(hours=24),
    },
)

    if not criada:
        reserva.cliente_nome = cliente_nome
        reserva.cliente_contato = cliente_contato
        reserva.vendedor = request.user
        reserva.expira_em = timezone.now() + timedelta(hours=24)
        reserva.cancelada = False
        reserva.save()

        veiculo.situacao = Veiculo.Situacao.RESERVADO
        veiculo.save(update_fields=["situacao"])

    HistoricoSituacaoVeiculo.objects.create(
        veiculo=veiculo,
        situacao_anterior=Veiculo.Situacao.DISPONIVEL,
        situacao_nova=Veiculo.Situacao.RESERVADO,
        alterado_por=request.user,
        motivo="Reserva do veículo",
    )

    messages.success(
        request,
        "Veículo reservado com sucesso."
    )

    return redirect(
        "detalhes_veiculo",
        veiculo_id=veiculo.id,
    )
    
@perfil_requerido("GERENTE", "ADMINISTRATIVO")
def alterar_situacao_veiculo_view(request, veiculo_id):
    veiculo = get_object_or_404(Veiculo, pk=veiculo_id)

    if request.method != "POST":
        return redirect("detalhes_veiculo", veiculo_id=veiculo.id)

    nova_situacao = request.POST.get("situacao")
    motivo = request.POST.get("motivo", "").strip()

    transicoes_permitidas = {
        Veiculo.Situacao.PREPARACAO: [
            Veiculo.Situacao.DISPONIVEL,
        ],
        Veiculo.Situacao.DISPONIVEL: [
            Veiculo.Situacao.RESERVADO,
        ],
        Veiculo.Situacao.RESERVADO: [
            Veiculo.Situacao.DISPONIVEL,
            Veiculo.Situacao.VENDIDO,
        ],
        Veiculo.Situacao.VENDIDO: [
            Veiculo.Situacao.ENTREGUE,
        ],
        Veiculo.Situacao.ENTREGUE: [],
    }

    situacoes_permitidas = transicoes_permitidas.get(
        veiculo.situacao,
        []
    )

    if nova_situacao not in situacoes_permitidas:
        messages.error(
            request,
            "Essa transição de situação não é permitida."
        )
        return redirect(
            "detalhes_veiculo",
            veiculo_id=veiculo.id,
        )

    situacao_anterior = veiculo.situacao

    veiculo.situacao = nova_situacao
    veiculo.save(update_fields=["situacao"])

    HistoricoSituacaoVeiculo.objects.create(
        veiculo=veiculo,
        situacao_anterior=situacao_anterior,
        situacao_nova=nova_situacao,
        alterado_por=request.user,
        motivo=motivo or None,)

    messages.success(
        request,
        "Situação do veículo alterada com sucesso."
    )

    return redirect(
        "detalhes_veiculo",
        veiculo_id=veiculo.id,
    )