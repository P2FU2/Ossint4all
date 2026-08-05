from monitor_jus.pipeline.identity import communication_key, movement_key


def test_movement_key_prefers_source_event_id():
    k1 = movement_key(
        source_name="djen",
        source_event_id="abc",
        numero_cnj="0000832-35.2018.4.01.3202",
        codigo_movimento_tpu="123",
        data_hora="2024-01-01T00:00:00",
        complemento="x",
        orgao_julgador="vara",
    )
    k2 = movement_key(
        source_name="djen",
        source_event_id="abc",
        numero_cnj="outro",
        codigo_movimento_tpu="999",
        data_hora=None,
        complemento="y",
        orgao_julgador="outra",
    )
    assert k1 == k2


def test_movement_key_composite_differs():
    a = movement_key(
        source_name="djen",
        source_event_id=None,
        numero_cnj="1",
        codigo_movimento_tpu="1",
        data_hora="2024-01-01",
        complemento="a",
        orgao_julgador="o",
    )
    b = movement_key(
        source_name="djen",
        source_event_id=None,
        numero_cnj="1",
        codigo_movimento_tpu="2",
        data_hora="2024-01-01",
        complemento="a",
        orgao_julgador="o",
    )
    assert a != b


def test_communication_key():
    k = communication_key(
        source_name="djen",
        source_event_id="pub-1",
        communication_type="PUBLICACAO_DJEN",
        numero_cnj=None,
        published_at="2024-01-01",
        body="texto",
    )
    assert len(k) == 64
