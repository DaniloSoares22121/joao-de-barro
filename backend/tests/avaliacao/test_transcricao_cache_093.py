"""ORDEM 093-5: o mesmo áudio (mesma impressão digital) é transcrito uma vez só; outro áudio é transcrito."""
from types import SimpleNamespace

from lovable.avaliacao import db, transcricao as T


def test_mesmo_audio_nao_transcreve_de_novo(tmp_path, monkeypatch):
    db.init()
    chamadas = []

    class Modelo:
        def transcribe(self, caminho, **kw):
            chamadas.append(caminho)
            return [SimpleNamespace(text=" casa de festas na quadra ")], SimpleNamespace(duration=12.5)
    monkeypatch.setattr(T, "_carregar", lambda: Modelo())
    a = tmp_path / "PTT-0001.opus"
    a.write_bytes(b"audio-1" * 1000)
    copia = tmp_path / "outra-importacao" / "PTT-0001.opus"       # o mesmo zip importado de novo
    copia.parent.mkdir()
    copia.write_bytes(a.read_bytes())
    assert T.transcrever(a)[:2] == ("casa de festas na quadra", 12.5)
    assert T.transcrever(copia)[:2] == ("casa de festas na quadra", 12.5)
    assert len(chamadas) == 1                                      # a 2ª veio guardada
    b = tmp_path / "PTT-0002.opus"
    b.write_bytes(b"audio-2" * 1000)
    T.transcrever(b)
    assert len(chamadas) == 2
