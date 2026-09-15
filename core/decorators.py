"""
Checagem de permissão por perfil — SEMPRE no servidor.
Esconder botão no template não é permissão (critério de aceite do T01).
Estes decorators são a barreira real: qualquer view sensível passa por aqui.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def perfil_requerido(*perfis_permitidos):
    """
    Uso: @perfil_requerido("GERENTE")
         @perfil_requerido("GERENTE", "ADMINISTRATIVO")

    Bloqueia no servidor, não importa como a rota foi acessada
    (menu, digitando a URL direto, etc.) — resolve o critério
    "abrir pelo endereço uma rota de outro perfil é recusado no servidor".
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            usuario = request.user

            if not usuario.ativo:
                # Vendedor (ou qualquer perfil) desativado não entra,
                # mesmo que a sessão ainda esteja "logada".
                from django.contrib.auth import logout
                logout(request)
                return redirect("login")

            if usuario.perfil not in perfis_permitidos:
                raise PermissionDenied("Seu perfil não tem acesso a esta rota.")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator