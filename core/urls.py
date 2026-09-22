from django.urls import path

from . import views

urlpatterns = [
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("painel/", views.painel_view, name="painel"),

    path("painel/vendedor/", views.painel_vendedor_view, name="painel_vendedor"),

    path("painel/administrativo/inicio/", views.painel_administrativo_view, name="painel_administrativo"),
    path("painel/administrativo/despesas/", views.despesas_view, name="despesas"),
    path("painel/administrativo/despesas/<int:veiculo_id>/", views.despesas_veiculo_view, name="despesas_veiculo"),
    path("painel/administrativo/despesas/<int:veiculo_id>/cadastrar/", views.adicionar_despesa_view, name="adicionar_despesa"),
    path("painel/administrativo/despesas/<int:despesa_id>/editar/", views.editar_despesa_view, name="editar_despesa"),
    path("painel/administrativo/despesas/<int:despesa_id>/excluir/", views.excluir_despesa_view, name="excluir_despesa"),
    path("painel/administrativo/despesas/veiculo/<int:veiculo_id>/excluidas/", views.despesas_excluidas_veiculo_view, name="despesas_excluidas_veiculo"),

    
    path("painel/gerente/inicio/", views.painel_gerente_view, name="painel_gerente"),
    path("painel/gerente/vendedores/", views.vendedores_view, name="vendedores"),
    path("painel/gerente/vendedores/cadastrar/", views.cadastrar_vendedor_view, name="cadastrar_vendedor"),
    path("painel/gerente/vendedores/<int:vendedor_id>/editar/", views.editar_vendedor_view, name="editar_vendedor"),
    path("painel/gerente/veiculos/cadastrar/", views.cadastrar_veiculo_view, name="cadastrar_veiculo"),
    path("painel/gerente/veiculos/", views.veiculos_view, name="veiculos"),
    path("painel/gerente/veiculos/<int:veiculo_id>/", views.detalhes_veiculo_view, name="detalhes_veiculo"),
    path("veiculos/<int:veiculo_id>/situacao/",views.alterar_situacao_veiculo_view,name="alterar_situacao_veiculo",),
    path("veiculos/<int:veiculo_id>/reservar/",views.reservar_veiculo_view, name="reservar_veiculo",),
    path("painel/gerente/veiculos/<int:veiculo_id>/preco/", views.alterar_preco_veiculo_view, name="alterar_preco_veiculo"),

]