from rest_framework import serializers

from models import Usuario, PerfilVendedor


class PerfilVendedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerfilVendedor
        fields = ["id", "usuario", "alcada_desconto", "percentual_comissao", "editado_em"]
        read_only_fields = ["editado_em"]


class UsuarioSerializer(serializers.ModelSerializer):
    dados_vendedor = PerfilVendedorSerializer(read_only=True)

    class Meta:
        model = Usuario
        fields = ["id", "username", "first_name", "perfil", "ativo", "dados_vendedor"]


class CadastroVendedorSerializer(serializers.Serializer):
    """
    Serializer de escrita: recebe os dados pra criar Usuario + PerfilVendedor
    juntos numa única chamada de API.
    """

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    alcada_desconto = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)
    percentual_comissao = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)

    def validate_username(self, value):
        if Usuario.objects.filter(username=value).exists():
            raise serializers.ValidationError("Já existe um usuário com esse nome.")
        return value

    def create(self, validated_data):
        gerente = self.context["request"].user

        usuario = Usuario.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            first_name=validated_data.get("first_name", ""),
            perfil=Usuario.Perfil.VENDEDOR,
        )
        perfil = PerfilVendedor.objects.create(
            usuario=usuario,
            alcada_desconto=validated_data["alcada_desconto"],
            percentual_comissao=validated_data["percentual_comissao"],
            editado_por=gerente,
        )
        return perfil


class EditarAlcadaComissaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerfilVendedor
        fields = ["alcada_desconto", "percentual_comissao"]

    def update(self, instance, validated_data):
        instance.alcada_desconto = validated_data.get("alcada_desconto", instance.alcada_desconto)
        instance.percentual_comissao = validated_data.get("percentual_comissao", instance.percentual_comissao)
        instance.editado_por = self.context["request"].user
        instance.full_clean()  # dispara a regra "só gerente edita" do model
        instance.save()
        return instance
