"""
T01 - Perfis, vendedores e o painel de cada um
T02 - O veículo: ficha, fotos, custo de aquisição e origem

Cobre os critérios de aceite:
- Login com usuário/senha (senha cifrada via AbstractUser do Django)
- Três perfis: gerente, vendedor, administrativo
- Vendedor tem alçada de desconto e percentual de comissão
- Só gerente edita alçada/comissão (regra fica no lado de permissões/views, aqui
  deixamos o campo protegido por um método de validação)
- Vendedor desativado não entra, mas vendas dele continuam no sistema
  (usamos soft delete: campo `ativo`, nunca deletamos o registro)
- Unicidade do veículo (placa/chassi) no estoque ativo
- Reserva exclusiva com prazo, com expiração automática
- Histórico de situação e de preço do veículo
- Margem derivada dos lançamentos financeiros (nunca um campo digitado)
- Auditoria simples de edição/exclusão de lançamentos financeiros
"""

# --- stdlib ---
import re
from datetime import date
from decimal import Decimal

# --- django ---
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.aggregates import Sum
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from django.core.exceptions import PermissionDenied, ValidationError

# ============================================================
# Constantes / regex
# ============================================================

PLACA_REGEX = re.compile(r"^[A-Z]{3}-?\d{4}$|^[A-Z]{3}\d[A-Z]\d{2}$")  # antiga e Mercosul
CHASSI_REGEX = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # 17 chars, sem I/O/Q (padrão VIN)


# ============================================================
# Usuários e perfis
# ============================================================

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
    """

    class TipoAlcada(models.TextChoices):
        PERCENTUAL = "PERCENTUAL", "Percentual (%)"
        VALOR = "VALOR", "Valor (R$)"

    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.PROTECT,
        related_name="dados_vendedor",
        limit_choices_to={"perfil": Usuario.Perfil.VENDEDOR},
    )

    tipo_alcada = models.CharField(
        max_length=20,
        choices=TipoAlcada.choices,
        default=TipoAlcada.PERCENTUAL,
    )

    valor_alcada = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Limite máximo de desconto permitido ao vendedor.",
    )

    percentual_comissao = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Percentual de comissão do vendedor sobre a margem da venda.",
    )

    editado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edicoes_alcada_comissao",
    )
    editado_em = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.editado_por_id and not self.editado_por.is_gerente():
            raise ValidationError(
                "Alçada de desconto e comissão só podem ser editadas por um gerente."
            )

    def __str__(self):
        return (
            f"Vendedor: {self.usuario} — "
            f"alçada {self.valor_alcada} ({self.get_tipo_alcada_display()}) / "
            f"comissão {self.percentual_comissao}%"
        )


# ============================================================
# Veículos
# ============================================================

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

    situacao = models.CharField(
        max_length=20,
        choices=Situacao.choices,
        default=Situacao.PREPARACAO,
    )

    origem = models.CharField(max_length=20, choices=Origem.choices)

    custo_aquisicao = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    preco_venda = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valor_repasse = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    venda_fechada = models.BooleanField(default=False)
    cliente_comprador = models.ForeignKey(
        "Cliente",
        on_delete=models.PROTECT,
        related_name="veiculos_comprados",
        null=True,
        blank=True,
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DISPONIVEL)

    criado_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name="veiculos_cadastrados"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["placa"],
                condition=models.Q(status__in=["DISPONIVEL", "RESERVADO"]),
                name="placa_unica_estoque_ativo",
            ),
            models.UniqueConstraint(
                fields=["chassi"],
                condition=models.Q(status__in=["DISPONIVEL", "RESERVADO"]),
                name="chassi_unico_estoque_ativo",
            ),
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

        if self.pk:
            original = Veiculo.objects.filter(pk=self.pk).first()
            if original and original.venda_fechada and original.custo_aquisicao != self.custo_aquisicao:
                erros["custo_aquisicao"] = "Não é possível alterar o custo após o fechamento da venda."

        if erros:
            raise ValidationError(erros)

    def __str__(self):
        return f"{self.marca} {self.modelo} — {self.placa}"

    @property
    def reserva_ativa(self):
        """Reserva vigente (não cancelada e não vencida), ou None."""
        return self.reservas.filter(
            cancelada=False, expira_em__gt=timezone.now()
        ).first()


class HistoricoSituacaoVeiculo(models.Model):
    veiculo = models.ForeignKey(
        Veiculo, on_delete=models.PROTECT, related_name="historico_situacoes"
    )

    situacao_anterior = models.CharField(max_length=20, blank=True, null=True)
    situacao_nova = models.CharField(max_length=20)

    alterado_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name="alteracoes_situacao_veiculo"
    )
    alterado_em = models.DateTimeField(auto_now_add=True)

    motivo = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.veiculo} — {self.situacao_anterior} → {self.situacao_nova}"


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
            FotoVeiculo.objects.filter(veiculo=self.veiculo).exclude(pk=self.pk).update(
                principal=False
            )


class ReservaVeiculo(models.Model):
    veiculo = models.ForeignKey(
        Veiculo,
        on_delete=models.PROTECT,
        related_name="reservas",
        limit_choices_to={"status": Veiculo.Status.DISPONIVEL},
    )
    cliente = models.ForeignKey(
        "Cliente",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reservas",
    )
    cliente_nome = models.CharField(max_length=120)
    cliente_contato = models.CharField(max_length=60)
    vendedor = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name="reservas_feitas"
    )

    criada_em = models.DateTimeField(auto_now_add=True)
    expira_em = models.DateTimeField()

    cancelada = models.BooleanField(default=False)

    def esta_valida(self):
        return not self.cancelada and timezone.now() < self.expira_em

    def expirar(self):
        if self.cancelada or timezone.now() < self.expira_em:
            return

        self.cancelada = True
        self.save(update_fields=["cancelada"])

        veiculo = Veiculo.objects.filter(
            pk=self.veiculo_id,
            situacao=Veiculo.Situacao.RESERVADO,
        ).first()

        if veiculo:
            veiculo.situacao = Veiculo.Situacao.DISPONIVEL
            veiculo.status = Veiculo.Status.DISPONIVEL
            veiculo.save(update_fields=["situacao", "status"])

            HistoricoSituacaoVeiculo.objects.create(
                veiculo=veiculo,
                situacao_anterior=Veiculo.Situacao.RESERVADO,
                situacao_nova=Veiculo.Situacao.DISPONIVEL,
                alterado_por=self.vendedor,
                motivo="Reserva expirada",
            )

        Proposta.ativar_aguardando(self.veiculo_id)

    def clean(self):
        if self.expira_em and self.expira_em <= timezone.now():
            raise ValidationError({"expira_em": "O prazo da reserva deve ser no futuro."})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.esta_valida():
            Veiculo.objects.filter(pk=self.veiculo_id).update(status=Veiculo.Status.RESERVADO)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["veiculo"],
                condition=models.Q(cancelada=False),
                name="uma_reserva_ativa_por_veiculo",
            )
        ]


# ============================================================
# Financeiro
# ============================================================

class LancamentoFinanceiro(models.Model):
    class Tipo(models.TextChoices):
        CUSTO_AQUISICAO = "CUSTO_AQUISICAO", "Custo de aquisição"
        DESPESA = "DESPESA", "Despesa (preparo, documentação, etc.)"
        VENDA = "VENDA", "Valor de venda"
        COMISSAO = "COMISSAO", "Comissão paga"

    veiculo = models.ForeignKey(
        Veiculo, on_delete=models.PROTECT, related_name="lancamentos"
    )
    tipo = models.CharField(max_length=30, choices=Tipo.choices)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    descricao = models.CharField(max_length=200, blank=True)
    registrado_por = models.ForeignKey(Usuario, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)
    data_lancamento = models.DateField(default=timezone.now)

    editado_por = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="despesas_editadas",
    )
    editado_em = models.DateTimeField(null=True, blank=True)
    excluido = models.BooleanField(default=False)
    excluido_por = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="despesas_excluidas",
    )
    excluido_em = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.get_tipo_display()}: R$ {self.valor} — {self.veiculo}"


def calcular_margem(veiculo: Veiculo) -> Decimal:
    lancamentos = veiculo.lancamentos.filter(excluido=False)

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


class HistoricoPrecoVeiculo(models.Model):
    veiculo = models.ForeignKey(
        Veiculo, on_delete=models.PROTECT, related_name="historico_precos"
    )

    valor_anterior = models.DecimalField(max_digits=12, decimal_places=2)
    valor_novo = models.DecimalField(max_digits=12, decimal_places=2)

    custo_total_no_momento = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    abaixo_do_custo = models.BooleanField(default=False)

    alterado_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name="alteracoes_preco_veiculo"
    )
    alterado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.veiculo} — R$ {self.valor_anterior} → R$ {self.valor_novo}"



# ============================================================
# Clientes
# ============================================================

class Cliente(models.Model):
    class Tipo(models.TextChoices):
        PESSOA_FISICA = "PF", "Pessoa Física"
        PESSOA_JURIDICA = "PJ", "Pessoa Jurídica"

    tipo = models.CharField(
        max_length=2,
        choices=Tipo.choices,
    )

    nome = models.CharField(max_length=150, blank=True)
    cpf = models.CharField(max_length=11, blank=True)
    data_nascimento = models.DateField(null=True, blank=True)

    cnpj = models.CharField(max_length=14, blank=True)
    razao_social = models.CharField(max_length=180, blank=True)
    nome_fantasia = models.CharField(max_length=150, blank=True)
    responsavel = models.CharField(max_length=150, blank=True)

    cep = models.CharField(max_length=8, blank=True)
    logradouro = models.CharField(max_length=180, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=2, blank=True)

    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome", "razao_social"]
        constraints = [
            models.UniqueConstraint(
                fields=["cpf"],
                condition=~models.Q(cpf=""),
                name="cliente_cpf_unico",
            ),
            models.UniqueConstraint(
                fields=["cnpj"],
                condition=~models.Q(cnpj=""),
                name="cliente_cnpj_unico",
            ),
        ]

    def clean(self):
        super().clean()
        erros = {}

        self.cpf = re.sub(r"\D", "", self.cpf or "")
        self.cnpj = re.sub(r"\D", "", self.cnpj or "")
        self.cep = re.sub(r"\D", "", self.cep or "")

        if self.tipo == self.Tipo.PESSOA_FISICA:
            if not self.nome.strip():
                erros["nome"] = "Informe o nome do cliente."
            if len(self.cpf) != 11:
                erros["cpf"] = "O CPF deve conter 11 dígitos."
            if not self.data_nascimento:
                erros["data_nascimento"] = "Informe a data de nascimento."
            self.cnpj = ""
            self.razao_social = ""
            self.nome_fantasia = ""
            self.responsavel = ""

        elif self.tipo == self.Tipo.PESSOA_JURIDICA:
            if not self.razao_social.strip():
                erros["razao_social"] = "Informe a razão social."
            if len(self.cnpj) != 14:
                erros["cnpj"] = "O CNPJ deve conter 14 dígitos."
            if not self.responsavel.strip():
                erros["responsavel"] = "Informe o responsável."
            self.cpf = ""
            self.nome = ""
            self.data_nascimento = None

        else:
            erros["tipo"] = "Selecione pessoa física ou jurídica."

        if erros:
            raise ValidationError(erros)

    @property
    def nome_exibicao(self):
        if self.tipo == self.Tipo.PESSOA_FISICA:
            return self.nome
        return self.nome_fantasia or self.razao_social

    def desativar(self):
        self.ativo = False
        self.save(update_fields=["ativo", "atualizado_em"])

    def __str__(self):
        return self.nome_exibicao


class TelefoneCliente(models.Model):
    class Tipo(models.TextChoices):
        CELULAR = "CELULAR", "Celular"
        FIXO = "FIXO", "Fixo"
        COMERCIAL = "COMERCIAL", "Comercial"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name="telefones",
    )
    numero = models.CharField(max_length=20)
    tipo = models.CharField(
        max_length=12,
        choices=Tipo.choices,
        default=Tipo.CELULAR,
    )
    principal = models.BooleanField(default=False)

    class Meta:
        ordering = ["-principal", "numero"]

    def clean(self):
        super().clean()
        self.numero = re.sub(r"\D", "", self.numero or "")

        if len(self.numero) not in (10, 11):
            raise ValidationError({
                "numero": "Informe um telefone com DDD e 10 ou 11 dígitos."
            })

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def __str__(self):
        return self.numero


class Proposta(models.Model):
    class StatusAprovacao(models.TextChoices):
        NAO_NECESSARIA = "NAO_NECESSARIA", "Não necessária"
        PENDENTE = "PENDENTE", "Pendente"
        APROVADA = "APROVADA", "Aprovada"
        RECUSADA = "RECUSADA", "Recusada"
        CONTRAPROPOSTA = "CONTRAPROPOSTA", "Contraproposta"
    class Situacao(models.TextChoices):
        AGUARDANDO = "AGUARDANDO", "Aguardando"
        ATIVA = "ATIVA", "Ativa"
        CANCELADA = "CANCELADA", "Cancelada"
        AGUARDANDO_GERENTE = "AGUARDANDO_GERENTE", "Aguardando gerente"
        APROVADA = "APROVADA", "Aprovada"
        RECUSADA = "RECUSADA", "Recusada"
        CONTRAPROPOSTA = "CONTRAPROPOSTA", "Contraproposta"

    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, related_name="propostas"
    )
    veiculo = models.ForeignKey(
        Veiculo, on_delete=models.PROTECT, related_name="propostas"
    )
    vendedor = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="propostas",
        limit_choices_to={
            "perfil__in": [Usuario.Perfil.VENDEDOR, Usuario.Perfil.GERENTE]
        },
    )

    data = models.DateField(default=timezone.localdate)
    valor_oferecido = models.DecimalField(max_digits=12, decimal_places=2)

    preco_tabela = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, editable=False
    )

    situacao = models.CharField(
        max_length=20,
        choices=Situacao.choices,
        default=Situacao.ATIVA,
        editable=False,
    )
    reserva_aguardada = models.ForeignKey(
        "ReservaVeiculo",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="propostas_aguardando",
    )
    status_aprovacao = models.CharField(
        max_length=20,
        choices=StatusAprovacao.choices,
        default=StatusAprovacao.NAO_NECESSARIA,
        editable=False,
    )

    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    _valor_original = None
    
    class Meta:
        ordering = ["-criada_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["veiculo"],
                condition=models.Q(situacao="ATIVA"),
                name="uma_proposta_ativa_por_veiculo",
            )
        ]
    

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._valor_original = instance.__dict__.get("valor_oferecido")
        return instance

    @property
    def desconto_embutido(self):
        if self.preco_tabela is None:
            return Decimal("0.00")
        return self.preco_tabela - self.valor_oferecido

    @property
    def desconto_percentual(self):
        if not self.preco_tabela:
            return Decimal("0.00")
        return (self.desconto_embutido / self.preco_tabela * 100).quantize(
            Decimal("0.01")
        )

    @property
    def soma_composicao(self):
        total = self.composicao.aggregate(total=Sum("valor"))["total"]
        return total or Decimal("0.00")

    @property
    def diferenca(self):
        return self.valor_oferecido - self.soma_composicao

    @property
    def composicao_fecha(self):
        return self.diferenca == 0

    @property
    def alcada_vendedor(self):
        """Perfil comercial do vendedor da proposta (ou None, ex.: gerente)."""
        return getattr(self.vendedor, "dados_vendedor", None)
    @property
    def fora_da_alcada(self):
        """
        Verifica se o desconto ultrapassa a alçada do vendedor.
        Gerentes não precisam de aprovação.
        """
        perfil = self.alcada_vendedor

        if perfil is None:
            if self.vendedor.is_vendedor():
                raise ValidationError(
                    "Este vendedor não possui alçada cadastrada. "
                    "Solicite ao gerente que configure seu perfil comercial."
                )
            return False

        if self.desconto_embutido <= 0:
            return False

        if perfil.tipo_alcada == PerfilVendedor.TipoAlcada.PERCENTUAL:
            return self.desconto_percentual > perfil.valor_alcada

        return self.desconto_embutido > perfil.valor_alcada
    
    def _desconto_percentual_de(self, valor):
            """Desconto sobre o preço de tabela se a venda fosse por `valor`."""
            if not self.preco_tabela:
                return Decimal("0.00")
            return ((self.preco_tabela - valor) / self.preco_tabela * 100).quantize(Decimal("0.01"))

    def _alcada_texto(self):
        """Foto da alçada em texto legível, para a trilha de auditoria."""
        perfil = self.alcada_vendedor
        if perfil is None:
            return ""
        if perfil.tipo_alcada == PerfilVendedor.TipoAlcada.PERCENTUAL:
            return f"{perfil.valor_alcada}%"
        return f"R$ {perfil.valor_alcada}"
    
    def clean(self):
        erros = {}

        if self.valor_oferecido is not None and self.valor_oferecido <= 0:
            erros["valor_oferecido"] = "O valor oferecido deve ser maior que zero."

        if self.veiculo_id:
            if not self.veiculo.preco_venda:
                erros["veiculo"] = "Este veículo ainda não tem preço de venda definido."
            elif not self.pk and self.veiculo.situacao not in (
                Veiculo.Situacao.DISPONIVEL,
                Veiculo.Situacao.RESERVADO,
            ):
                erros["veiculo"] = (
                    "Só é possível fazer proposta para veículo disponível ou reservado."
                )

        if self.cliente_id and not self.pk and not self.cliente.ativo:
            erros["cliente"] = "Cliente desativado não pode receber proposta."

        if self.pk and self.situacao == self.Situacao.CANCELADA:
            erros["__all__"] = "Proposta cancelada não pode ser editada."

        if erros:
            raise ValidationError(erros)

    def save(self, *args, usuario=None, **kwargs):
        criando = self.pk is None

        with transaction.atomic():
            veiculo = Veiculo.objects.select_for_update().get(
                pk=self.veiculo_id
            )

            if self.situacao != self.Situacao.CANCELADA and veiculo.preco_venda:
                self.preco_tabela = veiculo.preco_venda

            valor_mudou = (
                criando or self.valor_oferecido != self._valor_original
            )

            precisa_aprovacao = (
                valor_mudou
                and self.situacao != self.Situacao.CANCELADA
                and self.fora_da_alcada
            )

            # Situação inicial: respeita a reserva e a proposta ativa.
            if criando:
                reserva = veiculo.reservas.filter(
                    cancelada=False,
                    expira_em__gt=timezone.now(),
                ).exists()

                proposta_ativa = Proposta.objects.filter(
                    veiculo_id=self.veiculo_id,
                    situacao=self.Situacao.ATIVA,
                ).exists()

                if reserva or proposta_ativa:
                    self.situacao = self.Situacao.AGUARDANDO
                    self.reserva_aguardada = veiculo.reserva_ativa
                else:
                    self.situacao = self.Situacao.ATIVA
                    self.reserva_aguardada = None

            # Aprovação é independente da situação do veículo.
            if valor_mudou:
                if precisa_aprovacao:
                    self.status_aprovacao = self.StatusAprovacao.PENDENTE
                else:
                    self.status_aprovacao = (
                        self.StatusAprovacao.NAO_NECESSARIA
                    )

            super().save(*args, **kwargs)

            if valor_mudou:
                HistoricoProposta.objects.create(
                    proposta=self,
                    valor_anterior=(
                        None if criando else self._valor_original
                    ),
                    valor_novo=self.valor_oferecido,
                    alterado_por=usuario or self.vendedor,
                )

            if precisa_aprovacao:
                self.registrar_pedido(usuario or self.vendedor)

            self._valor_original = self.valor_oferecido
    def aceitar_contraproposta(self, usuario):
        """
        Permite que o vendedor responsável aceite a contraproposta
        registrada pelo gerente.
        """

        if not (
            getattr(usuario, "is_authenticated", False)
            and usuario.ativo
            and usuario.is_vendedor()
        ):
            raise PermissionDenied(
                "Somente o vendedor responsável pode aceitar a contraproposta."
            )

        with transaction.atomic():

            # Bloqueia o veículo para evitar conflitos com outras propostas.
            veiculo_id = Proposta.objects.only("veiculo_id").get(
                pk=self.pk
            ).veiculo_id

            veiculo = Veiculo.objects.select_for_update().get(
                pk=veiculo_id
            )

            proposta = Proposta.objects.select_for_update().get(
                pk=self.pk
            )

            if proposta.vendedor_id != usuario.pk:
                raise PermissionDenied(
                    "Você não pode aceitar a contraproposta de outro vendedor."
                )

            if proposta.situacao == self.Situacao.CANCELADA:
                raise ValidationError(
                    "Uma proposta cancelada não pode ser aceita."
                )

            if proposta.status_aprovacao != self.StatusAprovacao.CONTRAPROPOSTA:
                raise ValidationError(
                    "Esta proposta não possui uma contraproposta pendente de aceite."
                )

            # Recupera a contraproposta mais recente do gerente.
            decisao = proposta.decisoes.filter(
                tipo=DecisaoProposta.Tipo.CONTRAPROPOSTA
            ).order_by("-feito_em", "-id").first()

            if not decisao:
                raise ValidationError(
                    "Não foi encontrada uma contraproposta registrada."
                )

            valor_anterior = proposta.valor_oferecido
            novo_valor = decisao.valor_referencia

            # Verifica se a proposta pode sair da fila de espera.
            if proposta.situacao == self.Situacao.AGUARDANDO:

                reserva_ativa = veiculo.reservas.filter(
                    cancelada=False,
                    expira_em__gt=timezone.now(),
                ).exists()

                outra_proposta_ativa = Proposta.objects.filter(
                    veiculo_id=veiculo.pk,
                    situacao=self.Situacao.ATIVA,
                ).exclude(pk=proposta.pk).exists()

                if not reserva_ativa and not outra_proposta_ativa:
                    proposta.situacao = self.Situacao.ATIVA

                    proposta.reserva_aguardada = None

            # Registra o novo valor e a aprovação.
            proposta.valor_oferecido = novo_valor
            proposta.status_aprovacao = self.StatusAprovacao.APROVADA

            # Atualiza diretamente para não executar novamente
            # a regra de alçada do método save().
            Proposta.objects.filter(pk=proposta.pk).update(
                valor_oferecido=novo_valor,
                status_aprovacao=self.StatusAprovacao.APROVADA,
                situacao=proposta.situacao,
                reserva_aguardada=proposta.reserva_aguardada,
                atualizada_em=timezone.now(),
            )

            # Registra a alteração do valor.
            HistoricoProposta.objects.create(
                proposta=proposta,
                valor_anterior=valor_anterior,
                valor_novo=novo_valor,
                alterado_por=usuario,
            )

            # Registra o aceite na trilha de auditoria.
            aceite = DecisaoProposta.objects.create(
                    proposta=proposta,
                    tipo=DecisaoProposta.Tipo.ACEITE_CONTRAPROPOSTA,
                    valor_referencia=novo_valor,
                    desconto_percentual_no_momento=(
                        proposta._desconto_percentual_de(novo_valor)
                    ),
                    alcada_no_momento=proposta._alcada_texto(),
                    parecer="Contraproposta aceita pelo vendedor.",
                    feito_por=usuario,
                )

            self.refresh_from_db()

        return aceite
    
    def recusar_contraproposta(self, usuario):
        """
        O vendedor responsável recusa a contraproposta do gerente.
        A proposta fica RECUSADA + CANCELADA e a fila do veículo anda.
        """
        if not (
            getattr(usuario, "is_authenticated", False)
            and usuario.ativo
            and usuario.is_vendedor()
        ):
            raise PermissionDenied(
                "Somente o vendedor responsável pode recusar a contraproposta."
            )

        with transaction.atomic():
            proposta = Proposta.objects.select_for_update().get(pk=self.pk)

            if proposta.vendedor_id != usuario.pk:
                raise PermissionDenied(
                    "Você não pode recusar a contraproposta de outro vendedor."
                )

            if proposta.situacao == self.Situacao.CANCELADA:
                raise ValidationError("Uma proposta cancelada não pode ser recusada.")

            if proposta.status_aprovacao != self.StatusAprovacao.CONTRAPROPOSTA:
                raise ValidationError(
                    "Esta proposta não possui uma contraproposta pendente."
                )

            decisao_gerente = proposta.decisoes.filter(
                tipo=DecisaoProposta.Tipo.CONTRAPROPOSTA
            ).first()

            if not decisao_gerente:
                raise ValidationError(
                    "Não foi encontrada uma contraproposta registrada."
                )

            recusa = DecisaoProposta.objects.create(
                proposta=proposta,
                tipo=DecisaoProposta.Tipo.RECUSA_CONTRAPROPOSTA,
                valor_referencia=decisao_gerente.valor_referencia,
                desconto_percentual_no_momento=(
                    proposta._desconto_percentual_de(decisao_gerente.valor_referencia)
                ),
                alcada_no_momento=proposta._alcada_texto(),
                parecer="Contraproposta recusada pelo vendedor.",
                feito_por=usuario,
            )

            proposta.status_aprovacao = self.StatusAprovacao.RECUSADA
            proposta.situacao = self.Situacao.CANCELADA
            proposta.save(
                update_fields=["status_aprovacao", "situacao", "atualizada_em"]
            )

            Proposta.ativar_aguardando(proposta.veiculo_id)

            self.refresh_from_db()

        return recusa
    
    @classmethod
    def ativar_aguardando(cls, veiculo_id):
        with transaction.atomic():
            veiculo = Veiculo.objects.select_for_update().get(
                pk=veiculo_id
            )

            if veiculo.reserva_ativa:
                return None

            if cls.objects.filter(
                veiculo_id=veiculo_id,
                situacao=cls.Situacao.ATIVA,
            ).exists():
                return None

            proxima = cls.objects.select_for_update().filter(
                veiculo_id=veiculo_id,
                situacao=cls.Situacao.AGUARDANDO,
                status_aprovacao__in=[
                    cls.StatusAprovacao.NAO_NECESSARIA,
                    cls.StatusAprovacao.APROVADA,
                ],
            ).order_by("criada_em", "pk").first()

            if not proxima:
                return None

            proxima.situacao = cls.Situacao.ATIVA
            proxima.reserva_aguardada = None

            proxima.save(
                update_fields=[
                    "situacao",
                    "reserva_aguardada",
                    "atualizada_em",
                ]
            )

            return proxima
    
    def cancelar(self):
        if self.situacao == self.Situacao.CANCELADA:
            return

        with transaction.atomic():
            self.situacao = self.Situacao.CANCELADA
            self.save(update_fields=["situacao", "atualizada_em"])
            Proposta.ativar_aguardando(self.veiculo_id)
            
        
    def registrar_pedido(self, usuario):
            """Grava na trilha o pedido de aprovação (a situação já foi ajustada no save)."""
            return DecisaoProposta.objects.create(
            proposta=self,
            tipo=DecisaoProposta.Tipo.PEDIDO,
            valor_referencia=self.valor_oferecido,
            desconto_percentual_no_momento=self.desconto_percentual,
            alcada_no_momento=self._alcada_texto(),
            feito_por=usuario,
            )

    def decidir(self, usuario, tipo, parecer="", novo_valor=None):
        if not (
            getattr(usuario, "is_authenticated", False)
            and usuario.ativo
            and usuario.is_gerente()
        ):
            raise PermissionDenied(
                "Somente um gerente ativo pode decidir sobre propostas."
            )

        Tipo = DecisaoProposta.Tipo

        if tipo not in (
            Tipo.APROVACAO,
            Tipo.RECUSA,
            Tipo.CONTRAPROPOSTA,
        ):
            raise ValidationError("Tipo de decisão inválido.")

        parecer = (parecer or "").strip()

        with transaction.atomic():
            proposta = Proposta.objects.select_for_update().get(
                pk=self.pk
            )
            if proposta.situacao == self.Situacao.CANCELADA:
                raise ValidationError("Esta proposta foi cancelada.")

            if proposta.vendedor_id == usuario.pk:
                raise PermissionDenied(
                    "Ninguém pode decidir sobre a própria proposta."
                )

            if (
                proposta.status_aprovacao
                != self.StatusAprovacao.PENDENTE
            ):
                raise ValidationError(
                    "Esta proposta não está aguardando decisão do gerente."
                )

            if tipo == Tipo.APROVACAO:
                nova_aprovacao = self.StatusAprovacao.APROVADA
                valor_ref = proposta.valor_oferecido

            elif tipo == Tipo.RECUSA:
                if not parecer:
                    raise ValidationError(
                        "Informe o parecer da recusa."
                    )

                nova_aprovacao = self.StatusAprovacao.RECUSADA
                valor_ref = proposta.valor_oferecido

            else:
                if not parecer:
                    raise ValidationError(
                        "Informe o parecer da contraproposta."
                    )

                if novo_valor is None:
                    raise ValidationError(
                        "Informe o valor da contraproposta."
                    )

                try:
                    novo_valor = Decimal(novo_valor)
                except (InvalidOperation, TypeError, ValueError):
                    raise ValidationError(
                        "Valor da contraproposta inválido."
                    )

                if novo_valor <= proposta.valor_oferecido:
                    raise ValidationError(
                        "A contraproposta deve ser maior que o valor oferecido."
                    )

                nova_aprovacao = self.StatusAprovacao.CONTRAPROPOSTA
                valor_ref = novo_valor.quantize(Decimal("0.01"))

            decisao = DecisaoProposta.objects.create(
                proposta=proposta,
                tipo=tipo,
                valor_referencia=valor_ref,
                desconto_percentual_no_momento=(
                    proposta._desconto_percentual_de(valor_ref)
                ),
                alcada_no_momento=proposta._alcada_texto(),
                parecer=parecer,
                feito_por=usuario,
            )

            proposta.status_aprovacao = nova_aprovacao

            if tipo == Tipo.RECUSA:
                proposta.situacao = self.Situacao.CANCELADA

            proposta.save(
                update_fields=[
                    "status_aprovacao",
                    "situacao",
                    "atualizada_em",
                ]
            )
            
            
            if tipo in (Tipo.RECUSA, Tipo.APROVACAO):
                Proposta.ativar_aguardando(proposta.veiculo_id)
                
            self.status_aprovacao = nova_aprovacao
            self.situacao = proposta.situacao

            return decisao
    
    def __str__(self):
        return f"Proposta #{self.pk} — {self.cliente} — {self.veiculo}"


class ComposicaoPagamento(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada em dinheiro"
        TROCA = "TROCA", "Veículo na troca"
        FINANCIAMENTO = "FINANCIAMENTO", "Saldo financiado"

    proposta = models.ForeignKey(
        Proposta, on_delete=models.CASCADE, related_name="composicao"
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    troca_descricao = models.CharField(max_length=150, blank=True)

    financ_banco = models.CharField(max_length=100, blank=True)
    financ_parcelas = models.PositiveSmallIntegerField(null=True, blank=True)
    financ_valor_parcela = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    class Meta:
        ordering = ["id"]

    def clean(self):
        erros = {}

        if self.valor is not None and self.valor <= 0:
            erros["valor"] = "O valor deve ser maior que zero."

        if self.tipo == self.Tipo.TROCA:
            if not self.troca_descricao.strip():
                erros["troca_descricao"] = "Descreva o veículo recebido na troca."
            self.financ_banco = ""
            self.financ_parcelas = None
            self.financ_valor_parcela = None

        elif self.tipo == self.Tipo.FINANCIAMENTO:
            if not self.financ_banco.strip():
                erros["financ_banco"] = "Informe o banco do financiamento."
            if not self.financ_parcelas or self.financ_parcelas < 1:
                erros["financ_parcelas"] = "Informe o número de parcelas."
            if not self.financ_valor_parcela or self.financ_valor_parcela <= 0:
                erros["financ_valor_parcela"] = "Informe o valor da parcela."
            self.troca_descricao = ""

        else:
            self.troca_descricao = ""
            self.financ_banco = ""
            self.financ_parcelas = None
            self.financ_valor_parcela = None

        if erros:
            raise ValidationError(erros)

    def __str__(self):
        return f"{self.get_tipo_display()}: R$ {self.valor}"


class HistoricoProposta(models.Model):
    proposta = models.ForeignKey(
        Proposta, on_delete=models.PROTECT, related_name="historico"
    )
    valor_anterior = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    valor_novo = models.DecimalField(max_digits=12, decimal_places=2)
    alterado_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name="alteracoes_proposta"
    )
    alterado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-alterado_em", "-id"]

    def __str__(self):
        anterior = "—" if self.valor_anterior is None else f"R$ {self.valor_anterior}"
        return f"{self.proposta} — {anterior} → R$ {self.valor_novo}"
    
class DecisaoProposta(models.Model):
    """
    Trilha de auditoria da T09: um registro por evento (pedido de aprovação,
    aprovação, recusa, contraproposta). Nunca é editado nem apagado.
    """

    class Tipo(models.TextChoices):
        PEDIDO = "PEDIDO", "Pedido de aprovação"
        APROVACAO = "APROVACAO", "Aprovação"
        RECUSA = "RECUSA", "Recusa"
        CONTRAPROPOSTA = "CONTRAPROPOSTA", "Contraproposta"
        ACEITE_CONTRAPROPOSTA = ("ACEITE_CONTRAPROPOSTA","Aceite da contraproposta",)
        RECUSA_CONTRAPROPOSTA = ("RECUSA_CONTRAPROPOSTA","Recusa da contraproposta",)
        

    proposta = models.ForeignKey(
        Proposta, on_delete=models.PROTECT, related_name="decisoes"
    )
    tipo = models.CharField(
    max_length=30,
    choices=Tipo.choices,
)

    # Pedido: valor que o vendedor ofereceu. Contraproposta: novo valor do gerente.
    valor_referencia = models.DecimalField(max_digits=12, decimal_places=2)

    # Fotos do momento (o preço e a alçada podem mudar depois).
    desconto_percentual_no_momento = models.DecimalField(
        max_digits=7, decimal_places=2, default=0
    )
    alcada_no_momento = models.CharField(max_length=40, blank=True)

    parecer = models.TextField(blank=True)

    feito_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name="decisoes_proposta"
    )
    feito_em = models.DateTimeField(auto_now_add=True)
    
    

    class Meta:
        ordering = ["-feito_em", "-id"]

    def save(self, *args, **kwargs):
        # Trilha de auditoria: só se cria, nunca se edita.
        if self.pk:
            raise ValidationError("Registros de decisão não podem ser alterados.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Registros de decisão não podem ser apagados.")

    def __str__(self):
        return f"{self.proposta} — {self.get_tipo_display()} — R$ {self.valor_referencia}"
    
    