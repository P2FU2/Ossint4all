from monitor_jus.sources.judit.webhooks import build_delivery_key, classify_webhook_event_type


def test_delivery_key_stable_with_delivery_id():
    payload = {"delivery_id": "d-1", "foo": 1}
    k1 = build_delivery_key(payload, {})
    k2 = build_delivery_key({"delivery_id": "d-1", "foo": 2}, {})
    assert k1 == k2


def test_classify_djen():
    assert classify_webhook_event_type({"type": "djen_publication"}) == "PUBLICACAO_DJEN"
