"""
Todas as validações dos formulários ficam aqui (e nos models), nunca no HTML.
"""

import re
from datetime import date

from django import forms
from django.core.validators import MaxLengthValidator
from django.forms import inlineformset_factory
from django.utils import timezone

from .models import (
    Cliente,
    LancamentoFinanceiro,
    PerfilVendedor,
    TelefoneCliente,
    Usuario,
    Veiculo,
)


# ======================================================================
# BASE: vale para todos os formulários
# ======================================================================
class BaseForm:
    """
    Herde sempre desta classe ANTES de forms.Form / forms.ModelForm.

    - Tira o `required` do HTML.
    - Tira `maxlength`, `minlength`, `min` e `max` dos widgets (o Django
      continua validando tudo no servidor).
    - Usa o NOME do campo como id (id="valor" em vez de id="id_valor"),
      assim o seu CSS e seus scripts continuam funcionando.
    """

    use_required_attribute = False

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "%s")
        super().__init__(*args, **kwargs)

        for campo in self.fields.values():
            for atributo in ("required", "maxlength", "minlength", "min", "max"):
                campo.widget.attrs.pop(atributo, None)

    def add_error(self, field, error):
        """Marca com a classe `input-erro` todo campo que tiver erro (borda vermelha)."""
        super().add_error(field, error)
        for nome in self._errors:
            if nome in self.fields:
                widget = self.fields[nome].widget
                classes = widget.attrs.get("class", "").split()
                if "input-erro" not in classes:
                    widget.attrs["class"] = " ".join(classes + ["input-erro"])


# ======================================================================
# LOGIN
# ======================================================================
class LoginForm(BaseForm, forms.Form):
    username = forms.CharField(
        label="Usuário",
        error_messages={"required": "Informe o usuário."},
        widget=forms.TextInput(
            attrs={"placeholder": "Digite seu usuário", "autocomplete": "username"}
        ),
    )
    password = forms.CharField(
        label="Senha",
        strip=False,  # a senha não pode ter espaços cortados
        error_messages={"required": "Informe a senha."},
        widget=forms.PasswordInput(
            attrs={"placeholder": "Digite sua senha", "autocomplete": "current-password"}
        ),
    )


# ======================================================================
# DESPESAS (LancamentoFinanceiro)
# ======================================================================
class DespesaForm(BaseForm, forms.ModelForm):
    class Meta:
        model = LancamentoFinanceiro
        fields = ["valor", "data_lancamento", "descricao"]
        labels = {
            "valor": "Valor",
            "data_lancamento": "Data do lançamento",
            "descricao": "Descrição",
        }
        widgets = {
            "valor": forms.NumberInput(attrs={"step": "0.01"}),
            "data_lancamento": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "descricao": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Ex.: Funilaria, documentação, limpeza...",
                }
            ),
        }
        error_messages = {
            "valor": {
                "required": "Informe o valor.",
                "invalid": "Informe um valor válido.",
            },
            "data_lancamento": {
                "required": "Informe a data do lançamento.",
                "invalid": "Data inválida.",
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Data de hoje já preenchida ao abrir o formulário vazio.
        self.fields["data_lancamento"].initial = timezone.localdate

    def clean_valor(self):
        valor = self.cleaned_data["valor"]
        if valor <= 0:
            raise forms.ValidationError("O valor deve ser maior que zero.")
        return valor


class DespesaEditarForm(DespesaForm):
    """Mesma regra, mas a descrição é um campo de uma linha (como na tela atual)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["descricao"].widget = forms.TextInput()


# ======================================================================
# PREÇO DE VENDA
# ======================================================================
class PrecoVendaForm(BaseForm, forms.Form):
    preco_venda = forms.DecimalField(
        label="Novo preço de venda",
        max_digits=12,
        decimal_places=2,
        min_value=0,
        error_messages={
            "required": "Informe o preço de venda.",
            "invalid": "Informe um valor válido.",
            "min_value": "O preço não pode ser negativo.",
        },
        widget=forms.NumberInput(attrs={"step": "0.01"}),
    )

    def clean_preco_venda(self):
        preco = self.cleaned_data["preco_venda"]
        if preco <= 0:
            raise forms.ValidationError("O preço deve ser maior que zero.")
        return preco


# ======================================================================
# VENDEDORES
# ======================================================================
class _VendedorComercialMixin(forms.Form):
    """Campos comerciais compartilhados entre cadastro e edição."""

    tipo_alcada = forms.ChoiceField(
        label="Tipo de alçada",
        choices=PerfilVendedor.TipoAlcada.choices,
        initial=PerfilVendedor.TipoAlcada.PERCENTUAL,
        error_messages={
            "required": "Selecione o tipo de alçada.",
            "invalid_choice": "Tipo de alçada inválido.",
        },
        widget=forms.RadioSelect,
    )
    valor_alcada = forms.DecimalField(
        label="Limite de desconto",
        max_digits=12,
        decimal_places=2,
        min_value=0,
        initial=0,
        error_messages={
            "required": "Informe o limite de desconto.",
            "invalid": "Informe um valor válido.",
            "min_value": "O limite não pode ser negativo.",
        },
        widget=forms.NumberInput(attrs={"step": "0.01"}),
    )
    percentual_comissao = forms.DecimalField(
        label="Percentual de comissão",
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=100,
        initial=0,
        error_messages={
            "required": "Informe o percentual de comissão.",
            "invalid": "Informe um valor válido.",
            "min_value": "A comissão não pode ser negativa.",
            "max_value": "A comissão não pode passar de 100%%.",  # %% = % literal (o Django formata a mensagem)
        },
        widget=forms.NumberInput(attrs={"step": "0.01"}),
    )

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get("tipo_alcada")
        valor = cleaned.get("valor_alcada")
        if (
            tipo == PerfilVendedor.TipoAlcada.PERCENTUAL
            and valor is not None
            and valor > 100
        ):
            self.add_error(
                "valor_alcada", "O limite em percentual não pode passar de 100%."
            )
        return cleaned


class VendedorCadastroForm(BaseForm, _VendedorComercialMixin):
    nome = forms.CharField(
        label="Nome completo",
        max_length=150,
        error_messages={"required": "Informe o nome completo."},
        widget=forms.TextInput(attrs={"placeholder": "Digite o nome completo"}),
    )
    username = forms.CharField(
        label="Usuário",
        max_length=150,
        error_messages={"required": "Informe o usuário."},
        widget=forms.TextInput(attrs={"placeholder": "Digite o usuário para login"}),
    )
    email = forms.EmailField(
        label="E-mail",
        required=False,
        error_messages={"invalid": "Informe um e-mail válido."},
        widget=forms.EmailInput(attrs={"placeholder": "Digite o e-mail"}),
    )
    senha = forms.CharField(
        label="Senha",
        strip=False,  # a senha não pode ter espaços cortados
        error_messages={"required": "Informe a senha."},
        widget=forms.PasswordInput(attrs={"placeholder": "Digite a senha"}),
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        Usuario.username_validator(username)  # caracteres permitidos
        if Usuario.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Já existe um usuário com este nome.")
        return username


class VendedorEdicaoForm(BaseForm, _VendedorComercialMixin):
    nome = forms.CharField(
        label="Nome",
        max_length=150,
        error_messages={"required": "Informe o nome."},
        widget=forms.TextInput(attrs={"placeholder": "Digite o nome"}),
    )
    email = forms.EmailField(
        label="E-mail",
        required=False,
        error_messages={"invalid": "Informe um e-mail válido."},
        widget=forms.EmailInput(attrs={"placeholder": "Digite o e-mail"}),
    )
    ativo = forms.TypedChoiceField(
        label="Status",
        choices=[("true", "Ativo"), ("false", "Inativo")],
        coerce=lambda valor: valor == "true",
        error_messages={"required": "Informe o status."},
    )


# ======================================================================
# VEÍCULOS
# ======================================================================
COMBUSTIVEIS = [
    ("", "Selecione"),
    ("Gasolina", "Gasolina"),
    ("Etanol", "Etanol"),
    ("Flex", "Flex"),
    ("Diesel", "Diesel"),
    ("Elétrico", "Elétrico"),
    ("Híbrido", "Híbrido"),
]


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """Campo que aceita várias imagens de uma vez (name="fotos")."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        limpar = super().clean
        if isinstance(data, (list, tuple)):
            return [limpar(arquivo, initial) for arquivo in data if arquivo]
        return [limpar(data, initial)] if data else []


class VeiculoForm(BaseForm, forms.ModelForm):
    combustivel = forms.ChoiceField(
        label="Combustível",
        choices=COMBUSTIVEIS,
        error_messages={
            "required": "Selecione o combustível.",
            "invalid_choice": "Combustível inválido.",
        },
    )
    fotos = MultipleImageField(
        label="Fotos do veículo",
        required=False,
        error_messages={"invalid_image": "Envie apenas imagens JPG, PNG ou WEBP."},
    )

    class Meta:
        model = Veiculo
        fields = [
            "placa", "chassi", "renavam", "marca", "modelo",
            "ano_fabricacao", "ano_modelo", "cor", "combustivel",
            "quilometragem", "opcionais",
            "origem", "custo_aquisicao", "preco_venda", "valor_repasse",
        ]
        labels = {
            "placa": "Placa",
            "chassi": "Chassi",
            "renavam": "Renavam",
            "marca": "Marca",
            "modelo": "Modelo",
            "ano_fabricacao": "Ano de fabricação",
            "ano_modelo": "Ano do modelo",
            "cor": "Cor",
            "quilometragem": "Quilometragem",
            "opcionais": "Opcionais",
            "origem": "Origem do veículo",
            "custo_aquisicao": "Custo de aquisição",
            "preco_venda": "Preço de venda",
            "valor_repasse": "Valor de repasse",
        }
        widgets = {
            "placa": forms.TextInput(attrs={"placeholder": "ABC1D23 ou ABC1234"}),
            "chassi": forms.TextInput(attrs={"placeholder": "17 caracteres"}),
            "renavam": forms.TextInput(
                attrs={"inputmode": "numeric", "placeholder": "Digite o renavam"}
            ),
            "ano_fabricacao": forms.NumberInput(
                attrs={"oninput": "this.value = this.value.slice(0, 4)"}
            ),
            "ano_modelo": forms.NumberInput(
                attrs={"oninput": "this.value = this.value.slice(0, 4)"}
            ),
            "marca": forms.TextInput(attrs={"placeholder": "Ex.: Toyota"}),
            "modelo": forms.TextInput(attrs={"placeholder": "Ex.: Corolla"}),
            "cor": forms.TextInput(attrs={"placeholder": "Ex.: Branco"}),
            "opcionais": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Ex.: ar-condicionado, câmera de ré, bancos de couro...",
                }
            ),
            "custo_aquisicao": forms.NumberInput(
                attrs={"step": "0.01", "placeholder": "0,00"}
            ),
            "preco_venda": forms.NumberInput(
                attrs={"step": "0.01", "placeholder": "0,00"}
            ),
            "valor_repasse": forms.NumberInput(
                attrs={"step": "0.01", "placeholder": "0,00"}
            ),
        }
        error_messages = {
            "placa": {"required": "Informe a placa."},
            "chassi": {"required": "Informe o chassi."},
            "renavam": {"required": "Informe o renavam."},
            "marca": {"required": "Informe a marca."},
            "modelo": {"required": "Informe o modelo."},
            "ano_fabricacao": {
                "required": "Informe o ano de fabricação.",
                "invalid": "Ano inválido.",
            },
            "ano_modelo": {
                "required": "Informe o ano do modelo.",
                "invalid": "Ano inválido.",
            },
            "cor": {"required": "Informe a cor."},
            "quilometragem": {
                "required": "Informe a quilometragem.",
                "invalid": "Quilometragem inválida.",
            },
            "origem": {"required": "Selecione a origem do veículo."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["origem"].initial = Veiculo.Origem.COMPRADO

    # --- validações campo a campo ---------------------------------------
    def clean_renavam(self):
        renavam = re.sub(r"\s", "", self.cleaned_data["renavam"])
        if not renavam.isdigit():
            raise forms.ValidationError("O renavam deve conter apenas números.")
        return renavam

    def clean_ano_fabricacao(self):
        ano = self.cleaned_data["ano_fabricacao"]
        limite = date.today().year + 1
        if not 1900 <= ano <= limite:
            raise forms.ValidationError(f"Informe um ano entre 1900 e {limite}.")
        return ano

    # --- validações entre campos ----------------------------------------
    def clean(self):
        cleaned = super().clean()
        fabricacao = cleaned.get("ano_fabricacao")
        modelo = cleaned.get("ano_modelo")
        if fabricacao and modelo and not fabricacao <= modelo <= fabricacao + 1:
            self.add_error(
                "ano_modelo",
                "O ano do modelo deve ser igual ao de fabricação ou o ano seguinte.",
            )
        return cleaned
    # Obs.: placa, chassi, custo (comprado/troca), repasse (consignado) e
    # unicidade no estoque já são validados pelo Veiculo.clean() do model.


# ======================================================================
# AÇÕES NA TELA DE DETALHES DO VEÍCULO
# ======================================================================
class ReservaForm(BaseForm, forms.Form):
    cliente_nome = forms.CharField(
        label="Nome do cliente",
        max_length=120,
        error_messages={"required": "Informe o nome do cliente."},
    )
    cliente_contato = forms.CharField(
        label="Contato do cliente",
        max_length=60,
        error_messages={"required": "Informe o contato do cliente."},
    )


class AlterarSituacaoForm(BaseForm, forms.Form):
    situacao = forms.ChoiceField(
        choices=Veiculo.Situacao.choices,
        error_messages={"invalid_choice": "Situação inválida."},
    )
    motivo = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.all(),
        required=False,
        label="Cliente Comprador",
        empty_label="Selecione um cliente...",
        error_messages={"invalid_choice": "Selecione um cliente válido."},
    )

    def clean(self):
        cleaned_data = super().clean()
        situacao = cleaned_data.get("situacao")
        cliente = cleaned_data.get("cliente")

        # Exige a seleção de cliente apenas se a nova situação for VENDIDO
        if situacao == Veiculo.Situacao.VENDIDO and not cliente:
            self.add_error("cliente", "Para registrar a venda, é necessário selecionar o cliente comprador.")

        return cleaned_data

# ======================================================================
# CLIENTES
# ======================================================================

def validar_cpf(valor):
    cpf = re.sub(r"\D", "", valor or "")

    if len(cpf) != 11 or len(set(cpf)) == 1:
        return False

    numeros = [int(d) for d in cpf]

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

    numeros = [int(d) for d in cnpj]

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


class ClienteForm(BaseForm, forms.ModelForm):
    class Meta:
        model = Cliente
        exclude = ["ativo", "criado_em", "atualizado_em"]

        widgets = {
            "data_nascimento": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
        }

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "id_%s")
        super().__init__(*args, **kwargs)

        # Aceita documentos e CEP com ou sem máscara.
        for nome in ("cpf", "cnpj", "cep"):
            campo = self.fields[nome]
            campo.max_length = None
            campo.validators = [
                v for v in campo.validators
                if not isinstance(v, MaxLengthValidator)
            ]

    def _somente_numeros(self, nome):
        return re.sub(
            r"\D",
            "",
            self.cleaned_data.get(nome) or "",
        )

    def clean_cpf(self):
        cpf = self._somente_numeros("cpf")
        tipo = self.cleaned_data.get("tipo")

        if tipo == Cliente.Tipo.PESSOA_FISICA:
            if not validar_cpf(cpf):
                raise forms.ValidationError(
                    "Informe um CPF válido."
                )

        return cpf

    def clean_cnpj(self):
        cnpj = self._somente_numeros("cnpj")
        tipo = self.cleaned_data.get("tipo")

        if tipo == Cliente.Tipo.PESSOA_JURIDICA:
            if not validar_cnpj(cnpj):
                raise forms.ValidationError(
                    "Informe um CNPJ válido."
                )

        return cnpj

    def clean_cep(self):
        cep = self._somente_numeros("cep")

        if cep and len(cep) != 8:
            raise forms.ValidationError(
                "O CEP deve conter 8 dígitos."
            )

        return cep

    def clean_data_nascimento(self):
        nascimento = self.cleaned_data.get("data_nascimento")
        tipo = self.cleaned_data.get("tipo")

        if (
            tipo == Cliente.Tipo.PESSOA_FISICA
            and nascimento
            and nascimento > timezone.localdate()
        ):
            raise forms.ValidationError(
                "A data de nascimento não pode ser futura."
            )

        return nascimento

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get("tipo")

        # Limpa os campos que não pertencem ao tipo selecionado.
        # Isso evita gravar dados de PF em PJ e vice-versa.
        if tipo == Cliente.Tipo.PESSOA_FISICA:
            cleaned["cnpj"] = ""
            cleaned["razao_social"] = ""
            cleaned["nome_fantasia"] = ""
            cleaned["responsavel"] = ""

        elif tipo == Cliente.Tipo.PESSOA_JURIDICA:
            cleaned["cpf"] = ""
            cleaned["nome"] = ""
            cleaned["data_nascimento"] = None

        return cleaned


class TelefoneClienteForm(BaseForm, forms.ModelForm):
    class Meta:
        model = TelefoneCliente
        fields = ["numero", "tipo", "principal"]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "%s")
        super().__init__(*args, **kwargs)

    def clean_numero(self):
        numero = re.sub(
            r"\D",
            "",
            self.cleaned_data.get("numero") or "",
        )

        if len(numero) not in (10, 11):
            raise forms.ValidationError(
                "Informe um telefone com DDD e 10 ou 11 dígitos."
            )

        return numero


TelefoneClienteFormSet = inlineformset_factory(
    Cliente,
    TelefoneCliente,
    form=TelefoneClienteForm,
    extra=1,
    min_num=1,
    validate_min=True,
    can_delete=True,
)
