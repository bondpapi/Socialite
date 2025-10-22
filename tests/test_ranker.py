from services.recommend import score_event

def test_scoring_pref_match():
    e = {"title": "Indie Concert", "category": "music", "min_price": 20}
    s = score_event(e, ["indie"])
    assert s > 0
