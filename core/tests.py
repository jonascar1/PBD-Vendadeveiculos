"""
Testes automatizados completos para o fluxo de negociações e aprovação de desconto (T09)
da aplicação `core` do sistema VENDACERTA.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Cliente,
    DecisaoProposta,
    HistoricoProposta,
    PerfilVendedor,
    Proposta,
    Veiculo,
)

Usuario = get_user_model()


class BaseNegociacoesTestCase(TestCase):
    """
    Classe base de testes com massa de dados comum inicializada via `setUpTestData`.
    """

    @classmethod
    def setUpTestData(cls):
        # 1. Usuários e perfis
        cls.gerente = Usuario.objects.create_user(
            username="gerente1",
            password="password123",
            first_name="Gerente",
            last_name="Silva",
            perfil=Usuario.Perfil.GERENTE,
            ativo=True,
        )

        cls.vendedor = Usuario.objects.create_user(
            username="vendedor1",
            password="password123",
            first_name="Vendedor",
            last_name="Santos",
            perfil=Usuario.Perfil.VENDEDOR,
            ativo=True,
        )
        cls.perfil_vendedor = PerfilVendedor.objects.create(
            usuario=cls.vendedor,
            tipo_alcada=PerfilVendedor.TipoAlcada.PERCENTUAL,
            valor_alcada=Decimal("4.50"),  # Alçada de 4,5%
            percentual_comissao=Decimal("2.00"),
        )

        cls.outro_vendedor = Usuario.objects.create_user(
            username="vendedor2",
            password="password123",
            first_name="Outro Vendedor",
            last_name="Oliveira",
            perfil=Usuario.Perfil.VENDEDOR,
            ativo=True,
        )
        cls.perfil_outro_vendedor = PerfilVendedor.objects.create(
            usuario=cls.outro_vendedor,
            tipo_alcada=PerfilVendedor.TipoAlcada.VALOR,
            valor_alcada=Decimal("2000.00"),  # Alçada em R$ 2.000,00
            percentual_comissao=Decimal("2.00"),
        )

        cls.administrativo = Usuario.objects.create_user(
            username="admin1",
            password="password123",
            first_name="Admin",
            last_name="Souza",
            perfil=Usuario.Perfil.ADMINISTRATIVO,
            ativo=True,
        )

        cls.gerente_vendedor = Usuario.objects.create_user(
            username="gerente_vendedor",
            password="password123",
            first_name="Gerente Vendedor",
            last_name="Ferreira",
            perfil=Usuario.Perfil.GERENTE,
            ativo=True,
        )

        # 2. Cliente pessoa física ativo
        cls.cliente = Cliente.objects.create(
            tipo=Cliente.Tipo.PESSOA_FISICA,
            nome="Cliente Teste",
            cpf="12345678901",
            data_nascimento="1990-01-01",
            ativo=True,
        )

        # 3. Veículo principal em estoque (Preço de tabela: R$ 100.000,00)
       # 3. Veículo principal em estoque (Preço de tabela: R$ 100.000,00)
        cls.veiculo = Veiculo.objects.create(
            placa="ABC1D23",
            chassi="9BWCA111111111111",
            renavam="12345678901",
            marca="Toyota",
            modelo="Corolla",
            ano_fabricacao=2022,
            ano_modelo=2023,
            cor="Preto",
            combustivel="Flex",
            quilometragem=15000,
            origem=Veiculo.Origem.COMPRADO,
            custo_aquisicao=Decimal("80000.00"),
            preco_venda=Decimal("100000.00"),
            situacao=Veiculo.Situacao.DISPONIVEL,  # <-- ALTERADO DE RESERVADO PARA DISPONIVEL
            status=Veiculo.Status.DISPONIVEL,      # <-- ALTERADO DE RESERVADO PARA DISPONIVEL
            criado_por=cls.gerente,
        )

    # --- Funções auxiliares para evitar duplicação de código ---

    def _criar_proposta(self, vendedor=None, valor_oferecido=96000, veiculo=None, cliente=None):
        """Cria uma proposta padrão no banco."""
        return Proposta.objects.create(
            cliente=cliente or self.cliente,
            veiculo=veiculo or self.veiculo,
            vendedor=vendedor or self.vendedor,
            valor_oferecido=Decimal(str(valor_oferecido)),
        )

    def _criar_proposta_pendente(self, vendedor=None, valor_oferecido=90000, veiculo=None):
        """Cria uma proposta com desconto acima da alçada (status_aprovacao = PENDENTE)."""
        proposta = self._criar_proposta(
            vendedor=vendedor or self.vendedor,
            valor_oferecido=valor_oferecido,
            veiculo=veiculo,
        )
        self.assertEqual(proposta.status_aprovacao, Proposta.StatusAprovacao.PENDENTE)
        return proposta


class PermissoesTests(BaseNegociacoesTestCase):
    """Verifica permissões de segurança e bloqueios de acesso por perfil e estado do usuário."""

    def test_vendedor_desativado_redireciona_para_login(self):
        self.vendedor.ativo = False
        self.vendedor.save()

        self.client.login(username="vendedor1", password="password123")
        response = self.client.get(reverse("propostas"))
        self.assertRedirects(response, reverse("login"))

    def test_vendedor_nao_pode_decidir_proposta_no_model(self):
        proposta = self._criar_proposta_pendente()
        with self.assertRaises(PermissionDenied):
            proposta.decidir(self.vendedor, DecisaoProposta.Tipo.APROVACAO)

    def test_administrativo_nao_pode_decidir_proposta_no_model(self):
        proposta = self._criar_proposta_pendente()
        with self.assertRaises(PermissionDenied):
            proposta.decidir(self.administrativo, DecisaoProposta.Tipo.APROVACAO)

    def test_vendedor_nao_pode_acessar_view_de_decidir_proposta(self):
        proposta = self._criar_proposta_pendente()
        self.client.login(username="vendedor1", password="password123")
        url = reverse("decidir_proposta", kwargs={"proposta_id": proposta.pk})
        
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        
        response_post = self.client.post(url, data={"acao": DecisaoProposta.Tipo.APROVACAO})
        self.assertEqual(response_post.status_code, 403)

    def test_gerente_nao_pode_decidir_propria_proposta_no_model(self):
        # Gerente criando a proposta (como vendedor da operação)
        proposta = self._criar_proposta(vendedor=self.gerente_vendedor, valor_oferecido=90000)
        # Força o status pendente para simular o teste
        Proposta.objects.filter(pk=proposta.pk).update(status_aprovacao=Proposta.StatusAprovacao.PENDENTE)
        proposta.refresh_from_db()

        with self.assertRaises(PermissionDenied):
            proposta.decidir(self.gerente_vendedor, DecisaoProposta.Tipo.APROVACAO)

    def test_gerente_inativo_nao_pode_decidir_proposta_no_model(self):
        proposta = self._criar_proposta_pendente()
        self.gerente.ativo = False
        self.gerente.save()

        with self.assertRaises(PermissionDenied):
            proposta.decidir(self.gerente, DecisaoProposta.Tipo.APROVACAO)


class AlcadaTests(BaseNegociacoesTestCase):
    """Testa o cálculo de alçada e geração automática do pedido de aprovação."""

    def test_desconto_dentro_da_alcada_percentual_fica_nao_necessaria(self):
        # Preço: 100.000,00 | Alçada: 4,5% | Valor: 96.000,00 (4,0% de desconto)
        proposta = self._criar_proposta(self.vendedor, 96000)
        self.assertEqual(proposta.status_aprovacao, Proposta.StatusAprovacao.NAO_NECESSARIA)
        self.assertFalse(proposta.decisoes.filter(tipo=DecisaoProposta.Tipo.PEDIDO).exists())

    def test_desconto_acima_da_alcada_percentual_fica_pendente_e_gera_pedido(self):
        # Preço: 100.000,00 | Alçada: 4,5% | Valor: 90.000,00 (10,0% de desconto)
        proposta = self._criar_proposta(self.vendedor, 90000)
        self.assertEqual(proposta.status_aprovacao, Proposta.StatusAprovacao.PENDENTE)

        # Valida trilha de auditoria criada
        decisao = proposta.decisoes.filter(tipo=DecisaoProposta.Tipo.PEDIDO).first()
        self.assertIsNotNone(decisao)
        self.assertEqual(decisao.valor_referencia, Decimal("90000.00"))
        self.assertEqual(decisao.desconto_percentual_no_momento, Decimal("10.00"))

    def test_desconto_dentro_e_fora_da_alcada_tipo_valor(self):
        # Alçada do outro vendedor é R$ 2.000,00
        # 1. Dentro: R$ 1.500,00 de desconto (98.500,00)
        p1 = self._criar_proposta(self.outro_vendedor, 98500)
        self.assertEqual(p1.status_aprovacao, Proposta.StatusAprovacao.NAO_NECESSARIA)

        # 2. Fora: R$ 3.000,00 de desconto (97.000,00) em outro veículo
        veiculo2 = Veiculo.objects.create(
            placa="XYZ9876",
            chassi="9BWCA111111111112",
            renavam="12345678902",
            marca="Honda",
            modelo="Civic",
            ano_fabricacao=2022,
            ano_modelo=2023,
            cor="Branco",
            combustivel="Flex",
            quilometragem=10000,
            origem=Veiculo.Origem.COMPRADO,
            custo_aquisicao=Decimal("80000.00"),
            preco_venda=Decimal("100000.00"),
            situacao=Veiculo.Situacao.DISPONIVEL,
            status=Veiculo.Status.DISPONIVEL,
            criado_por=self.gerente,
        )
        p2 = self._criar_proposta(self.outro_vendedor, 97000, veiculo=veiculo2)
        self.assertEqual(p2.status_aprovacao, Proposta.StatusAprovacao.PENDENTE)

    def test_proposta_com_valor_igual_ou_maior_que_tabela_nao_requer_aprovacao(self):
        p_igual = self._criar_proposta(self.vendedor, 100000)
        self.assertEqual(p_igual.status_aprovacao, Proposta.StatusAprovacao.NAO_NECESSARIA)

        p_maior = self._criar_proposta(self.vendedor, 105000)
        self.assertEqual(p_maior.status_aprovacao, Proposta.StatusAprovacao.NAO_NECESSARIA)

    def test_gerente_criando_proposta_nao_requer_aprovacao(self):
        proposta = self._criar_proposta(self.gerente, 80000)
        self.assertEqual(proposta.status_aprovacao, Proposta.StatusAprovacao.NAO_NECESSARIA)


class DecisaoGerenteTests(BaseNegociacoesTestCase):
    """Testa os métodos de decisão do gerente sobre propostas pendentes."""

    def setUp(self):
        self.proposta = self._criar_proposta_pendente(self.vendedor, 90000)

    def test_gerente_aprova_proposta_pendente(self):
        decisao = self.proposta.decidir(self.gerente, DecisaoProposta.Tipo.APROVACAO)

        self.assertEqual(self.proposta.status_aprovacao, Proposta.StatusAprovacao.APROVADA)
        self.assertEqual(decisao.tipo, DecisaoProposta.Tipo.APROVACAO)
        self.assertEqual(decisao.feito_por, self.gerente)

    def test_gerente_recusa_proposta_exige_parecer_e_cancela_proposta(self):
        # Validação de parecer obrigatório
        with self.assertRaises(ValidationError):
            self.proposta.decidir(self.gerente, DecisaoProposta.Tipo.RECUSA, parecer="")

        decisao = self.proposta.decidir(
            self.gerente, DecisaoProposta.Tipo.RECUSA, parecer="Desconto muito alto para a margem"
        )
        self.assertEqual(self.proposta.status_aprovacao, Proposta.StatusAprovacao.RECUSADA)
        self.assertEqual(self.proposta.situacao, Proposta.Situacao.CANCELADA)
        self.assertEqual(decisao.parecer, "Desconto muito alto para a margem")

    def test_gerente_faz_contraproposta_validacoes(self):
        # Exige parecer
        with self.assertRaises(ValidationError):
            self.proposta.decidir(
                self.gerente, DecisaoProposta.Tipo.CONTRAPROPOSTA, novo_valor=94000, parecer=""
            )

        # Novo valor deve ser MAIOR que o oferecido (oferecido foi 90.000)
        with self.assertRaises(ValidationError):
            self.proposta.decidir(
                self.gerente,
                DecisaoProposta.Tipo.CONTRAPROPOSTA,
                novo_valor=89000,
                parecer="Faço por menos",
            )

        # Sucesso
        decisao = self.proposta.decidir(
            self.gerente,
            DecisaoProposta.Tipo.CONTRAPROPOSTA,
            novo_valor=94000,
            parecer="Fechamos em R$ 94.000,00",
        )
        self.assertEqual(self.proposta.status_aprovacao, Proposta.StatusAprovacao.CONTRAPROPOSTA)
        self.assertEqual(decisao.valor_referencia, Decimal("94000.00"))

    def test_nao_pode_decidir_proposta_ja_decidida_ou_cancelada(self):
        self.proposta.decidir(self.gerente, DecisaoProposta.Tipo.APROVACAO)
        with self.assertRaises(ValidationError):
            self.proposta.decidir(self.gerente, DecisaoProposta.Tipo.APROVACAO)

        # Proposta cancelada
        p2 = self._criar_proposta(self.outro_vendedor, 98500)
        p2.cancelar()
        with self.assertRaises(ValidationError):
            p2.decidir(self.gerente, DecisaoProposta.Tipo.APROVACAO)


class ContrapropostaVendedorTests(BaseNegociacoesTestCase):
    """Testa o aceite e recusa de contrapropostas pelo vendedor responsável."""

    def setUp(self):
        self.proposta = self._criar_proposta_pendente(self.vendedor, 90000)
        self.proposta.decidir(
            self.gerente,
            DecisaoProposta.Tipo.CONTRAPROPOSTA,
            novo_valor=94000,
            parecer="Valor mínimo aprovado",
        )

    def test_vendedor_dono_aceita_contraproposta(self):
        decisao = self.proposta.aceitar_contraproposta(self.vendedor)

        self.assertEqual(self.proposta.valor_oferecido, Decimal("94000.00"))
        self.assertEqual(self.proposta.status_aprovacao, Proposta.StatusAprovacao.APROVADA)
        self.assertEqual(decisao.tipo, DecisaoProposta.Tipo.ACEITE_CONTRAPROPOSTA)

        # Registra histórico de alteração do valor
        historico = HistoricoProposta.objects.filter(proposta=self.proposta).first()
        self.assertEqual(historico.valor_novo, Decimal("94000.00"))

    def test_outro_vendedor_ou_gerente_nao_pode_aceitar_contraproposta(self):
        with self.assertRaises(PermissionDenied):
            self.proposta.aceitar_contraproposta(self.outro_vendedor)

        with self.assertRaises(PermissionDenied):
            self.proposta.aceitar_contraproposta(self.gerente)

    def test_vendedor_dono_recusa_contraproposta(self):
        decisao = self.proposta.recusar_contraproposta(self.vendedor)

        self.assertEqual(self.proposta.status_aprovacao, Proposta.StatusAprovacao.RECUSADA)
        self.assertEqual(self.proposta.situacao, Proposta.Situacao.CANCELADA)
        self.assertEqual(decisao.tipo, DecisaoProposta.Tipo.RECUSA_CONTRAPROPOSTA)


class FilaDeEsperaTests(BaseNegociacoesTestCase):
    """Testa o gerenciamento e avanço da fila de propostas em espera no veículo."""

    def test_propostas_subsequentes_ficam_aguardando_e_ativam_na_ordem(self):
        # 1ª Proposta fica ATIVA (Alçada 4,5% -> 96.000 = 4% desc)
        p1 = self._criar_proposta(self.vendedor, 96000)
        self.assertEqual(p1.situacao, Proposta.Situacao.ATIVA)

        # 2ª Proposta para o mesmo veículo fica AGUARDANDO
        # (Valor R$ 98.500,00 está dentro da alçada de R$ 2.000,00 do outro_vendedor -> NAO_NECESSARIA)
        p2 = self._criar_proposta(self.outro_vendedor, 98500)
        self.assertEqual(p2.situacao, Proposta.Situacao.AGUARDANDO)
        self.assertEqual(p2.status_aprovacao, Proposta.StatusAprovacao.NAO_NECESSARIA)

        # Cancelar a primeira ativa a segunda da fila
        p1.cancelar()
        p2.refresh_from_db()
        self.assertEqual(p2.situacao, Proposta.Situacao.ATIVA)


class AuditoriaTests(BaseNegociacoesTestCase):
    """Garante a imutabilidade do registro de auditoria DecisaoProposta."""

    def test_decisao_proposta_nao_pode_ser_editada_nem_excluida(self):
        proposta = self._criar_proposta_pendente(self.vendedor, 90000)
        decisao = proposta.decisoes.first()

        # Edição direta no model deve falhar
        decisao.parecer = "Tentando alterar parecer"
        with self.assertRaises(ValidationError):
            decisao.save()

        # Exclusão direta no model deve falhar
        with self.assertRaises(ValidationError):
            decisao.delete()


class BloqueioVendaTests(BaseNegociacoesTestCase):
    """Testa o bloqueio de transição para VENDIDO caso haja pendências no fluxo de aprovação."""

    def test_bloqueia_venda_veiculo_com_proposta_pendente_ou_contraproposta(self):
        self._criar_proposta_pendente(self.vendedor, 90000)  # Proposta PENDENTE

        # Tenta mudar a situação do veículo para VENDIDO
        self.client.login(username="gerente1", password="password123")
        url = reverse("alterar_situacao_veiculo", kwargs={"veiculo_id": self.veiculo.pk})

        response = self.client.post(
            url,
            data={
                "situacao": Veiculo.Situacao.VENDIDO,
                "motivo": "Tentativa de venda rápida",
                "cliente": self.cliente.pk,
            },
        )

        self.veiculo.refresh_from_db()
        self.assertNotEqual(self.veiculo.situacao, Veiculo.Situacao.VENDIDO)


class ViewsNegociacoesTests(BaseNegociacoesTestCase):
    """Testes de rotas e navegação via cliente HTTP para as views do módulo de negociações."""

    def test_negociacoes_view_acesso_e_indicadores(self):
        # 1. Bloqueia vendedor e administrativo com 403
        self.client.login(username="vendedor1", password="password123")
        response = self.client.get(reverse("negociacoes_gerente"))
        self.assertEqual(response.status_code, 403)

        self.client.login(username="admin1", password="password123")
        response = self.client.get(reverse("negociacoes_gerente"))
        self.assertEqual(response.status_code, 403)

        # 2. Gerente acessa com sucesso (200) e verifica contexto
        self.client.login(username="gerente1", password="password123")
        self.create_propostas_para_indicadores()

        response = self.client.get(reverse("negociacoes_gerente"))
        self.assertEqual(response.status_code, 200)

        indicadores = response.context["indicadores"]
        self.assertEqual(indicadores["total"], 4)
        self.assertEqual(indicadores["aguardando"], 1)
        self.assertEqual(indicadores["aprovadas"], 1)
        self.assertEqual(indicadores["recusadas"], 1)
        self.assertEqual(indicadores["contrapropostas"], 1)

    def create_propostas_para_indicadores(self):
        """Auxiliar para popular propostas em diversos estados de aprovação."""
        def _novo_veiculo(placa, chassi):
            return Veiculo.objects.create(
                placa=placa,
                chassi=chassi,
                renavam="12345678901",
                marca="Toyota",
                modelo="Corolla",
                ano_fabricacao=2022,
                ano_modelo=2023,
                cor="Preto",
                combustivel="Flex",
                quilometragem=15000,
                origem=Veiculo.Origem.COMPRADO,
                custo_aquisicao=Decimal("80000.00"),
                preco_venda=Decimal("100000.00"),
                situacao=Veiculo.Situacao.DISPONIVEL,
                status=Veiculo.Status.DISPONIVEL,
                criado_por=self.gerente,
            )

        # 1. Pendente
        v1 = _novo_veiculo("AAA1111", "9BWCA111111111113")
        self._criar_proposta_pendente(self.vendedor, 90000, veiculo=v1)

        # 2. Aprovada
        v2 = _novo_veiculo("BBB2222", "9BWCA111111111114")
        p2 = self._criar_proposta_pendente(self.vendedor, 89000, veiculo=v2)
        p2.decidir(self.gerente, DecisaoProposta.Tipo.APROVACAO)

        # 3. Recusada
        v3 = _novo_veiculo("CCC3333", "9BWCA111111111115")
        p3 = self._criar_proposta_pendente(self.vendedor, 88000, veiculo=v3)
        p3.decidir(self.gerente, DecisaoProposta.Tipo.RECUSA, parecer="Recusada")

        # 4. Contraproposta
        v4 = _novo_veiculo("DDD4444", "9BWCA111111111116")
        p4 = self._criar_proposta_pendente(self.vendedor, 87000, veiculo=v4)
        p4.decidir(self.gerente, DecisaoProposta.Tipo.CONTRAPROPOSTA, novo_valor=92000, parecer="Contra")

    def test_decidir_proposta_view_post_valido_e_invalidacao(self):
        proposta = self._criar_proposta_pendente(self.vendedor, 90000)
        self.client.login(username="gerente1", password="password123")

        url = reverse("decidir_proposta", kwargs={"proposta_id": proposta.pk})

        # POST de aprovação
        response = self.client.post(
            url,
            data={"acao": DecisaoProposta.Tipo.APROVACAO, "parecer": "", "novo_valor": ""},
        )
        self.assertRedirects(response, reverse("negociacoes_gerente"))

        proposta.refresh_from_db()
        self.assertEqual(proposta.status_aprovacao, Proposta.StatusAprovacao.APROVADA)

    def test_aceitar_e_recusar_contraproposta_view_regras_http(self):
        proposta = self._criar_proposta_pendente(self.vendedor, 90000)
        proposta.decidir(
            self.gerente,
            DecisaoProposta.Tipo.CONTRAPROPOSTA,
            novo_valor=95000,
            parecer="Contraproposta teste",
        )

        url_aceitar = reverse("aceitar_contraproposta", kwargs={"proposta_id": proposta.pk})

        # GET redireciona para propostas
        self.client.login(username="vendedor1", password="password123")
        response_get = self.client.get(url_aceitar)
        self.assertRedirects(response_get, reverse("propostas"))

        # POST efetuado pelo vendedor dono aceita a contraproposta
        response_post = self.client.post(url_aceitar)
        self.assertRedirects(
            response_post,
            reverse("detalhes_proposta", kwargs={"proposta_id": proposta.pk}),
        )

        proposta.refresh_from_db()
        self.assertEqual(proposta.status_aprovacao, Proposta.StatusAprovacao.APROVADA)

    def test_visitante_anonimo_redirecionado_para_login(self):
        url = reverse("negociacoes_gerente")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('login')}?next={url}")