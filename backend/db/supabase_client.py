"""
Conexao com o Supabase.

Usa a chave secreta do backend -- a que ignora Row Level Security pra
poder escrever. O frontend usa a chave publica (so leitura, ver
supabase/schema.sql).

## Dois nomes para a mesma chave

O Supabase renomeou o formato das chaves de API: o que era
`service_role` (um JWT longo) virou `sb_secret_...`, e o `anon` virou
`sb_publishable_...`. Os paineis novos entregam os nomes novos, os
projetos antigos ainda tem os velhos, e as duas convencoes convivem.

Por isso a leitura aceita as duas, na ordem "novo primeiro". Amarrar a
um nome so significa que copiar o snippet do painel do Supabase --
que e o caminho natural -- quebra a conexao com um KeyError que nao
explica nada.
"""

import os

from supabase import Client, create_client

NOMES_DA_CHAVE_SECRETA = ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")


def get_supabase_client() -> Client:
    url = _exigir(("SUPABASE_URL",), "a URL do projeto (https://<ref>.supabase.co)")
    chave = _exigir(
        NOMES_DA_CHAVE_SECRETA,
        "a chave secreta do backend (sb_secret_... ou a service_role antiga)",
    )
    return create_client(url, chave)


def _exigir(nomes: tuple[str, ...], descricao: str) -> str:
    for nome in nomes:
        valor = os.environ.get(nome)
        if valor:
            return valor
    raise KeyError(
        f"nenhuma de {list(nomes)} definida no ambiente -- esperado {descricao}. "
        f"Veja backend/.env.example."
    )
