

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Usuario(AbstractUser):
    """
    Usuário base do sistema. A senha já vem cifrada automaticamente pelo
    Django (AbstractUser usa PBKDF2 por padrão) — não reinventar isso.
    """

    class Perfil(models.TextChoices):
        GERENTE = "GERENTE", "Gerente"
        VENDEDOR = "VENDEDOR", "Vendedor"
        ADMINISTRATIVO = "ADMINISTRATIVO", "Administrativo"

    perfil = models.CharField(max_length=20, choices=Perfil.choices)

    # Soft delete: nunca apagar o usuário, só desativar.
    # Isso resolve o critério "vendedor desativado não entra, mas as vendas
    # dele continuam no sistema" — o registro nunca some, só perde acesso.
    ativo = models.BooleanField(default=True)

    def is_gerente(self):
        return self.perfil == self.Perfil.GERENTE

    def is_vendedor(self):
        return self.perfil == self.Perfil.VENDEDOR

    def is_administrativo(self):
        return self.perfil == self.Perfil.ADMINISTRATIVO

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_perfil_display()})"


class PerfilVendedor(models.Model):
    """
    Dados extras de quem é vendedor: alçada de desconto e comissão.
    Fica em tabela separada (não direto no Usuario) porque só vendedor
    tem esses dois campos — administrativo e gerente não.
    """

    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.PROTECT,  # nunca deletar em cascata: histórico de vendas depende disso
        related_name="dados_vendedor",
        limit_choices_to={"perfil": Usuario.Perfil.VENDEDOR},
    )

    alcada_desconto = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Percentual máximo de desconto que este vendedor pode aplicar sem aprovação.",
    )

    percentual_comissao = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Percentual de comissão do vendedor sobre a margem da venda.",
    )

    # Quem foi o último a editar estes dois campos sensíveis — auditoria simples.
    editado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edicoes_alcada_comissao",
    )
    editado_em = models.DateTimeField(auto_now=True)

    def clean(self):
        # Regra de negócio: só quem estiver marcado como GERENTE pode
        # ser o autor de uma edição destes campos. A validação de "quem
        # está logado" acontece na view/form; aqui garantimos que o campo
        # `editado_por`, se preenchido, é de fato um gerente.
        if self.editado_por_id and not self.editado_por.is_gerente():
            raise ValidationError(
                "Alçada de desconto e comissão só podem ser editadas por um gerente."
            )

    def __str__(self):
        return f"Vendedor: {self.usuario} — alçada {self.alcada_desconto}% / comissão {self.percentual_comissao}%"
    
    """
T02 - O veículo: ficha, fotos, custo de aquisição e origem
+ requisitos da rubrica: unicidade do veículo, reserva exclusiva com prazo,
  troca virando estoque, margem derivada dos lançamentos.
"""

import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


PLACA_REGEX = re.compile(r"^[A-Z]{3}-?\d{4}$|^[A-Z]{3}\d[A-Z]\d{2}$")  # antiga e Mercosul
CHASSI_REGEX = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # 17 chars, sem I/O/Q (padrão VIN)


class Veiculo(models.Model):
    class Origem(models.TextChoices):
        COMPRADO = "COMPRADO", "Comprado de terceiro"
        TROCA = "TROCA", "Recebido em troca"
        CONSIGNADO = "CONSIGNADO", "Consignado"

    class Status(models.TextChoices):
        DISPONIVEL = "DISPONIVEL", "Disponível"
        RESERVADO = "RESERVADO", "Reservado"
        VENDIDO = "VENDIDO", "Vendido"
    
    class Situacao(models.TextChoices):
        PREPARACAO = "PREPARACAO", "Em preparação"
        DISPONIVEL = "DISPONIVEL", "Disponível"
        RESERVADO = "RESERVADO", "Reservado"
        VENDIDO = "VENDIDO", "Vendido"
        ENTREGUE = "ENTREGUE", "Entregue"


    # --- Identificação única no estoque ativo ---
    placa = models.CharField(max_length=8)
    chassi = models.CharField(max_length=17)
    renavam = models.CharField(max_length=11)
    marca = models.CharField(max_length=60)
    modelo = models.CharField(max_length=60)
    ano_fabricacao = models.PositiveSmallIntegerField()
    ano_modelo = models.PositiveSmallIntegerField()
    cor = models.CharField(max_length=30)
    combustivel = models.CharField(max_length=30)
    quilometragem = models.PositiveIntegerField()
    opcionais = models.TextField(blank=True)
    
    
    situacao = models.CharField(max_length=20,choices=Situacao.choices,default=Situacao.PREPARACAO,)

    origem = models.CharField(max_length=20, choices=Origem.choices)

    # Custo de aquisição: obrigatório para COMPRADO/TROCA, zero para CONSIGNADO.
    custo_aquisicao = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    preco_venda = models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True,)
    # Só usado quando origem == CONSIGNADO.
    valor_repasse = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    # Trava: depois que a venda fecha, custo não pode mais mudar.
    venda_fechada = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DISPONIVEL)

    criado_por = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="veiculos_cadastrados")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Unicidade de placa e chassi apenas no estoque ATIVO (não vendido).
            # Um veículo vendido não deveria travar o cadastro de outro igual
            # que reentre no estoque (ex: recomprado depois).
            models.UniqueConstraint(fields=["placa"],condition=models.Q(status__in=["DISPONIVEL", "RESERVADO"]),name="placa_unica_estoque_ativo",),
            
            models.UniqueConstraint(fields=["chassi"],condition=models.Q(status__in=["DISPONIVEL", "RESERVADO"]),name="chassi_unico_estoque_ativo",),
        ]

    def clean(self):
        erros = {}

        placa_normalizada = self.placa.upper().replace(" ", "")
        if not PLACA_REGEX.match(placa_normalizada):
            erros["placa"] = "Placa inválida. Use o formato antigo (ABC1234) ou Mercosul (ABC1D23)."
        self.placa = placa_normalizada

        chassi_normalizado = self.chassi.upper().replace(" ", "")
        if not CHASSI_REGEX.match(chassi_normalizado):
            erros["chassi"] = "Chassi inválido. Deve ter 17 caracteres, sem I, O ou Q."
        self.chassi = chassi_normalizado

        if self.origem in (self.Origem.COMPRADO, self.Origem.TROCA):
            if not self.custo_aquisicao or self.custo_aquisicao <= 0:
                erros["custo_aquisicao"] = "Custo de aquisição é obrigatório para essa origem."
        elif self.origem == self.Origem.CONSIGNADO:
            self.custo_aquisicao = Decimal("0")
            if self.valor_repasse is None:
                erros["valor_repasse"] = "Valor de repasse é obrigatório para consignado."

        # Trava de edição pós-venda: se já existe no banco e a venda estava
        # fechada, custo_aquisicao não pode ter mudado.
        if self.pk:
            original = Veiculo.objects.filter(pk=self.pk).first()
            if original and original.venda_fechada and original.custo_aquisicao != self.custo_aquisicao:
                erros["custo_aquisicao"] = "Não é possível alterar o custo após o fechamento da venda."

        if erros:
            raise ValidationError(erros)

    def __str__(self):
        return f"{self.marca} {self.modelo} — {self.placa}"

class HistoricoSituacaoVeiculo(models.Model):
    veiculo = models.ForeignKey(Veiculo, on_delete=models.PROTECT,related_name="historico_situacoes",)

    situacao_anterior = models.CharField(max_length=20,blank=True,null=True,)

    situacao_nova = models.CharField(max_length=20,)

    alterado_por = models.ForeignKey(Usuario,on_delete=models.PROTECT,related_name="alteracoes_situacao_veiculo",)

    alterado_em = models.DateTimeField(auto_now_add=True,)

    motivo = models.CharField(max_length=255,blank=True,null=True,)

    def __str__(self):
        return (
            f"{self.veiculo} — "
            f"{self.situacao_anterior} → {self.situacao_nova}"
        )
class FotoVeiculo(models.Model):
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name="fotos")
    imagem = models.ImageField(upload_to="veiculos/%Y/%m/")
    ordem = models.PositiveSmallIntegerField(default=0)
    principal = models.BooleanField(default=False)

    class Meta:
        ordering = ["ordem"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.principal:
            # Garante que só há uma foto principal por veículo.
            FotoVeiculo.objects.filter(veiculo=self.veiculo).exclude(pk=self.pk).update(principal=False)


class ReservaVeiculo(models.Model):
    """
    Reserva exclusiva com prazo (item da rubrica).
    Enquanto houver reserva ativa (não expirada, não cancelada) para um
    veículo, nenhuma outra reserva pode ser criada para ele — e o veículo
    fica com status RESERVADO.
    """

    veiculo = models.OneToOneField(Veiculo, on_delete=models.CASCADE, related_name="reserva_ativa",limit_choices_to={"status": Veiculo.Status.DISPONIVEL},)
    cliente_nome = models.CharField(max_length=120)
    cliente_contato = models.CharField(max_length=60)
    vendedor = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="reservas_feitas")

    criada_em = models.DateTimeField(auto_now_add=True)
    expira_em = models.DateTimeField()

    cancelada = models.BooleanField(default=False)

    def esta_valida(self):
        return not self.cancelada and timezone.now() < self.expira_em
    
    def expirar(self):
        if self.cancelada or timezone.now() >= self.expira_em:
            self.cancelada = True
            self.save(update_fields=["cancelada"])

            veiculo = Veiculo.objects.filter(pk=self.veiculo_id,situacao=Veiculo.Situacao.RESERVADO,).first()

            if veiculo:
                veiculo.situacao = Veiculo.Situacao.DISPONIVEL
                veiculo.save(update_fields=["situacao"])

                HistoricoSituacaoVeiculo.objects.create(
                    veiculo=veiculo,
                    situacao_anterior=Veiculo.Situacao.RESERVADO,
                    situacao_nova=Veiculo.Situacao.DISPONIVEL,
                    alterado_por=self.vendedor,
                    motivo="Reserva expirada",)
            
    def clean(self):
        if self.expira_em <= timezone.now():
            raise ValidationError({"expira_em": "O prazo da reserva deve ser no futuro."})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.esta_valida():
            Veiculo.objects.filter(pk=self.veiculo_id).update(status=Veiculo.Status.RESERVADO)


class LancamentoFinanceiro(models.Model):
    """
    Toda entrada/saída ligada a um veículo (custo extra, despesa de preparo,
    valor de venda, comissão paga, etc.) vira um lançamento aqui.

    A margem NUNCA é um campo digitado — ela é sempre calculada a partir
    da soma destes lançamentos (item explícito da rubrica: "margem
    derivada dos lançamentos").
    """

    class Tipo(models.TextChoices):
        CUSTO_AQUISICAO = "CUSTO_AQUISICAO", "Custo de aquisição"
        DESPESA = "DESPESA", "Despesa (preparo, documentação, etc.)"
        VENDA = "VENDA", "Valor de venda"
        COMISSAO = "COMISSAO", "Comissão paga"

    veiculo = models.ForeignKey(Veiculo, on_delete=models.PROTECT, related_name="lancamentos")
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    descricao = models.CharField(max_length=200, blank=True)
    registrado_por = models.ForeignKey(Usuario, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_tipo_display()}: R$ {self.valor} — {self.veiculo}"


def calcular_margem(veiculo: Veiculo) -> Decimal:
    """
    Margem = soma(VENDA) - soma(CUSTO_AQUISICAO) - soma(DESPESA) - soma(COMISSAO)

    Isso é o que alimenta os relatórios (item da rubrica "qualidade das
    consultas e relatórios") — nunca ler um campo "margem" salvo direto.
    """
    lancamentos = veiculo.lancamentos.all()

    entradas = sum(
        l.valor for l in lancamentos if l.tipo == LancamentoFinanceiro.Tipo.VENDA
    )
    saidas = sum(
        l.valor
        for l in lancamentos
        if l.tipo in (
            LancamentoFinanceiro.Tipo.CUSTO_AQUISICAO,
            LancamentoFinanceiro.Tipo.DESPESA,
            LancamentoFinanceiro.Tipo.COMISSAO,
        )
    )
    return Decimal(entradas) - Decimal(saidas)