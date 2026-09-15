"""
Permissão do DRF que faz o mesmo trabalho do decorator @perfil_requerido,
mas para as views de API (baseadas em classe). Mesmo princípio: checagem
sempre no servidor, nunca confiar em o que o frontend esconde ou mostra.
"""

from rest_framework.permissions import BasePermission


class EhGerente(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.ativo
            and request.user.is_gerente()
        )


class EhVendedor(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.ativo
            and request.user.is_vendedor()
        )


class EhAdministrativo(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.ativo
            and request.user.is_administrativo()
        )
