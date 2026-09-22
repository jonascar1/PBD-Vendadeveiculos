


from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from .decorators import perfil_requerido
from .models import HistoricoSituacaoVeiculo, Usuario, PerfilVendedor, Veiculo, FotoVeiculo
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
    return render(request, "core/painel_vendedor.html", {"dados": dados})


@perfil_requerido("ADMINISTRATIVO")
def painel_administrativo_view(request):
    return render(request, "core/painel_administrativo.html")


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

        alcada_desconto = request.POST.get(
            "alcada_desconto",
            dados.alcada_desconto
        )

        percentual_comissao = request.POST.get(
            "percentual_comissao",
            dados.percentual_comissao
        )

        if not nome:
            messages.error(request, "O nome do vendedor é obrigatório.")
            return render(
                request,
                "core/gerente_editar_vendedor.html",
                {"dados": dados}
            )

        try:
            # Dados da conta
            usuario.first_name = nome
            usuario.email = email
            usuario.ativo = ativo
            usuario.save()

            # Dados comerciais
            dados.alcada_desconto = alcada_desconto
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
        alcada_desconto = request.POST.get("alcada_desconto", "0")
        percentual_comissao = request.POST.get("percentual_comissao", "0")

        if not nome or not username or not senha:
            messages.error(request, "Preencha os campos obrigatórios.")
            return render(request, "core/gerente_cadastrar_vendedor.html")

        if Usuario.objects.filter(username=username).exists():
            messages.error(request, "Esse usuário já está cadastrado.")
            return render(request, "core/gerente_cadastrar_vendedor.html")


        try:
            with transaction.atomic():

                usuario = Usuario(
                    username=username,
                    email=email,
                    perfil=Usuario.Perfil.VENDEDOR,
                    ativo=True
                )

                # O Django faz a criptografia da senha
                usuario.set_password(senha)

                # Coloca o nome no first_name
                usuario.first_name = nome

                usuario.full_clean()
                usuario.save()

                PerfilVendedor.objects.create(
                    usuario=usuario,
                    alcada_desconto=alcada_desconto,
                    percentual_comissao=percentual_comissao,
                    editado_por=request.user
                )

            messages.success(request, "Vendedor cadastrado com sucesso.")
            return redirect("vendedores")

        except Exception:
            messages.error(
                request,
                "Não foi possível cadastrar o vendedor. Verifique os dados."
            )

    return render(request, "core/gerente_cadastrar_vendedor.html")

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

        custo_aquisicao = request.POST.get(
            "custo_aquisicao",
            ""
        ).strip()

        valor_repasse = request.POST.get(
            "valor_repasse",
            ""
        ).strip()


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

    return render(
        request,
        "core/gerente_detalhes_veiculo.html",
        {
            "veiculo": veiculo,
            "fotos": fotos,
        }
        
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

    reserva = ReservaVeiculo.objects.create(
        veiculo=veiculo,
        cliente_nome=cliente_nome,
        cliente_contato=cliente_contato,
        vendedor=request.user,
        expira_em=timezone.now() + timedelta(hours=24),
    )

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