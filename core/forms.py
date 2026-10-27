
import re

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from .models import Cliente, TelefoneCliente


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = [
            "tipo",
            "nome",
            "cpf",
            "data_nascimento",
            "cnpj",
            "razao_social",
            "nome_fantasia",
            "responsavel",
            "cep",
            "logradouro",
            "numero",
            "complemento",
            "bairro",
            "cidade",
            "estado",
        ]

        widgets = {
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "data_nascimento": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
        }

        labels = {
            "tipo": "Tipo de cliente",
            "nome": "Nome completo",
            "cpf": "CPF",
            "data_nascimento": "Data de nascimento",
            "cnpj": "CNPJ",
            "razao_social": "Razão social",
            "nome_fantasia": "Nome fantasia",
            "responsavel": "Responsável",
            "cep": "CEP",
            "logradouro": "Logradouro",
            "numero": "Número",
            "complemento": "Complemento",
            "bairro": "Bairro",
            "cidade": "Cidade",
            "estado": "Estado",
        }

    def clean_cpf(self):
        return re.sub(r"\D", "", self.cleaned_data.get("cpf") or "")

    def clean_cnpj(self):
        return re.sub(r"\D", "", self.cleaned_data.get("cnpj") or "")

    def clean(self):
        cleaned_data = super().clean()
        tipo = cleaned_data.get("tipo")
        cpf = cleaned_data.get("cpf")
        cnpj = cleaned_data.get("cnpj")

        if tipo == Cliente.Tipo.PESSOA_FISICA and cpf:
            duplicado = Cliente.objects.filter(cpf=cpf)
            if self.instance.pk:
                duplicado = duplicado.exclude(pk=self.instance.pk)
            if duplicado.exists():
                self.add_error(
                    "cpf",
                    "Este CPF já está cadastrado no sistema.",
                )

        if tipo == Cliente.Tipo.PESSOA_JURIDICA and cnpj:
            duplicado = Cliente.objects.filter(cnpj=cnpj)
            if self.instance.pk:
                duplicado = duplicado.exclude(pk=self.instance.pk)
            if duplicado.exists():
                self.add_error(
                    "cnpj",
                    "Este CNPJ já está cadastrado no sistema.",
                )

        return cleaned_data


class TelefoneClienteForm(forms.ModelForm):
    class Meta:
        model = TelefoneCliente
        fields = ["numero", "tipo", "principal"]
        labels = {
            "numero": "Telefone com DDD",
            "tipo": "Tipo de telefone",
            "principal": "Telefone principal",
        }


TelefoneClienteFormSet = inlineformset_factory(
    Cliente,
    TelefoneCliente,
    form=TelefoneClienteForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)
