"""ORDEM 183: o cliente apagado vai para a Lixeira (aparece lá, restaura) e só sai de vez ao esvaziar."""
from lovable.avaliacao import conversa as C, db
from tests.avaliacao.test_controle import API, dono  # noqa: F401 (fixture)


def test_cliente_na_lixeira_restaura_e_esvazia(client, dono):  # noqa: F811
    h, _ = dono
    cid = client.post(f"{API}/clientes", json={"nome": "Cliente Teste 183"}, headers=h).json()["id"]
    assert client.post(f"{API}/clientes/{cid}/lixeira", headers=h).status_code == 200
    itens = client.get(f"{API}/lixeira", headers=h).json()
    assert any(i["id"] == cid and i["tipo"] == "cliente" for i in itens)
    assert client.post(f"{API}/clientes/{cid}/restaurar", headers=h).status_code == 200
    assert not any(i["id"] == cid for i in client.get(f"{API}/lixeira", headers=h).json())
    client.post(f"{API}/clientes/{cid}/lixeira", headers=h)
    client.post(f"{API}/lixeira/esvaziar", headers=h)
    assert C.obter(cid) is None                                     # esvaziar apaga de vez
    assert not db.setting(f"lixeira_cliente:{cid}")
