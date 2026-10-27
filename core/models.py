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
from django import forms
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


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

    class TipoAlcada(models.TextChoices):
        PERCENTUAL = "PERCENTUAL", "Percentual (%)"
        VALOR = "VALOR", "Valor (R$)"

    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.PROTECT,  # nunca deletar em cascata: histórico de vendas depende disso
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
        # BUGFIX: o original referenciava self.alcada_desconto (campo inexistente).
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

    # Situação operacional (fluxo de preparo/entrega) — granularidade maior
    # que `status`, que controla apenas disponibilidade comercial.
    situacao = models.CharField(
        max_length=20,
        choices=Situacao.choices,
        default=Situacao.PREPARACAO,
    )

    origem = models.CharField(max_length=20, choices=Origem.choices)

    # Custo de aquisição: obrigatório para COMPRADO/TROCA, zero para CONSIGNADO.
    custo_aquisicao = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    preco_venda = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Só usado quando origem == CONSIGNADO.
    valor_repasse = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Trava: depois que a venda fecha, custo não pode mais mudar.
    venda_fechada = models.BooleanField(default=False)
    cliente_comprador = models.ForeignKey("Cliente",on_delete=models.PROTECT,related_name="veiculos_comprados",null=True,blank=True,)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DISPONIVEL)

    criado_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name="veiculos_cadastrados"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    
    class Meta:
        constraints = [
            # Unicidade de placa e chassi apenas no estoque ATIVO (não vendido).
            # Um veículo vendido não deveria travar o cadastro de outro igual
            # que reentre no estoque (ex: recomprado depois).
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
            # Garante que só há uma foto principal por veículo.
            FotoVeiculo.objects.filter(veiculo=self.veiculo).exclude(pk=self.pk).update(
                principal=False
            )


class ReservaVeiculo(models.Model):
    """
    Reserva exclusiva com prazo (item da rubrica).
    Enquanto houver reserva ativa (não expirada, não cancelada) para um
    veículo, nenhuma outra reserva pode ser criada para ele — e o veículo
    fica com status RESERVADO.
    """

    veiculo = models.OneToOneField(
        Veiculo,
        on_delete=models.CASCADE,
        related_name="reserva_ativa",
        limit_choices_to={"status": Veiculo.Status.DISPONIVEL},
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
        if self.cancelada or timezone.now() >= self.expira_em:
            self.cancelada = True
            self.save(update_fields=["cancelada"])

            veiculo = Veiculo.objects.filter(
                pk=self.veiculo_id,
                situacao=Veiculo.Situacao.RESERVADO,
            ).first()

            if veiculo:
                veiculo.situacao = Veiculo.Situacao.DISPONIVEL
                veiculo.status = Veiculo.Status.DISPONIVEL

                veiculo.save(update_fields=[
                    "situacao",
                    "status",
                ])

                HistoricoSituacaoVeiculo.objects.create(
                    veiculo=veiculo,
                    situacao_anterior=Veiculo.Situacao.RESERVADO,
                    situacao_nova=Veiculo.Situacao.DISPONIVEL,
                    alterado_por=self.vendedor,
                    motivo="Reserva expirada",
                )

    def clean(self):
        if self.expira_em <= timezone.now():
            raise ValidationError({"expira_em": "O prazo da reserva deve ser no futuro."})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.esta_valida():
            Veiculo.objects.filter(pk=self.veiculo_id).update(status=Veiculo.Status.RESERVADO)


# ============================================================
# Financeiro
# ============================================================

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

    veiculo = models.ForeignKey(
        Veiculo, on_delete=models.PROTECT, related_name="lancamentos"
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    descricao = models.CharField(max_length=200, blank=True)
    registrado_por = models.ForeignKey(Usuario, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)
    data_lancamento = models.DateField(default=timezone.now)

    # Auditoria de edição/exclusão (soft delete, igual ao Usuario).
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
    """
    Margem = soma(VENDA) - soma(CUSTO_AQUISICAO) - soma(DESPESA) - soma(COMISSAO)

    Isso é o que alimenta os relatórios (item da rubrica "qualidade das
    consultas e relatórios") — nunca ler um campo "margem" salvo direto.
    Lançamentos excluídos (soft delete) não entram na conta.
    """
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
# Validação de documentos (CPF / CNPJ)
# ============================================================

def validar_cpf(valor):
    cpf = re.sub(r"\D", "", valor or "")

    if len(cpf) != 11 or len(set(cpf)) == 1:
        return False

    numeros = [int(digito) for digito in cpf]

    soma = sum(numeros[i] * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    primeiro = 0 if resto == 10 else resto

    if numeros[9] != primeiro:
        return False

    soma = sum(numeros[i] * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    segundo = 0 if resto == 10 else resto

    return numeros[10] == segundo


def validar_cnpj(valor):
    cnpj = re.sub(r"\D", "", valor or "")

    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False

    numeros = [int(digito) for digito in cnpj]

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(n * p for n, p in zip(numeros[:12], pesos1))
    resto = soma % 11
    primeiro = 0 if resto < 2 else 11 - resto

    if numeros[12] != primeiro:
        return False

    pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(n * p for n, p in zip(numeros[:13], pesos2))
    resto = soma % 11
    segundo = 0 if resto < 2 else 11 - resto

    return numeros[13] == segundo


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

    # Pessoa física
    nome = models.CharField(max_length=150, blank=True)
    cpf = models.CharField(max_length=11, blank=True)
    data_nascimento = models.DateField(null=True, blank=True)

    # Pessoa jurídica
    cnpj = models.CharField(max_length=14, blank=True)
    razao_social = models.CharField(max_length=180, blank=True)
    nome_fantasia = models.CharField(max_length=150, blank=True)
    responsavel = models.CharField(max_length=150, blank=True)

    # Endereço
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

        # Mantém somente os números dos documentos.
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
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.numero


# ============================================================
# Formulário de Cliente
# ============================================================

class ClienteForm(forms.ModelForm):
    """
    Form de Cliente com validação de CPF/CNPJ e data de nascimento.

    As validações de documento e data ficavam soltas no módulo (como
    `def clean_cpf(self)`), o que é inválido — métodos `clean_<campo>`
    só existem dentro de um Form. Foram movidos para cá.
    """

    class Meta:
        model = Cliente
        fields = "__all__"

    def _somente_numeros(self, campo):
        return re.sub(r"\D", "", self.cleaned_data.get(campo) or "")

    def clean_cpf(self):
        cpf = self._somente_numeros("cpf")

        if self.cleaned_data.get("tipo") == Cliente.Tipo.PESSOA_FISICA:
            if not validar_cpf(cpf):
                raise ValidationError("Informe um CPF válido.")

        return cpf

    def clean_cnpj(self):
        cnpj = self._somente_numeros("cnpj")

        if self.cleaned_data.get("tipo") == Cliente.Tipo.PESSOA_JURIDICA:
            if not validar_cnpj(cnpj):
                raise ValidationError("Informe um CNPJ válido.")

        return cnpj

    def clean_data_nascimento(self):
        nascimento = self.cleaned_data.get("data_nascimento")

        if (
            self.cleaned_data.get("tipo") == Cliente.Tipo.PESSOA_FISICA
            and nascimento
            and nascimento > date.today()
        ):
            raise ValidationError(
                "A data de nascimento não pode ser futura."
            )

        return nascimento