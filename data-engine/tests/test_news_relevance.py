from app.services.news_relevance import company_is_central


def test_company_in_headline_is_central():
    assert company_is_central("MSFT", "Microsoft Corp", headline="Microsoft lanza nuevo Copilot", text="x")


def test_feed_ticker_prefix_is_not_evidence():
    text = "MSFT The Bet Behind Tieto's Rally. Tieto deepened its AI partnership with Microsoft."
    assert not company_is_central("MSFT", "Microsoft Corp", headline="MSFT The Bet Behind Tieto's Rally", text=text)


def test_passing_mention_is_not_central_but_repeated_mentions_are():
    one = "Donor list of the White House ballroom reveals Nvidia, Apple and Google among top tech contributors."
    assert not company_is_central("AAPL", "Apple Inc", headline="Trump's $330 Million Ballroom Donor List", text=one)
    many = "Analysts say Apple will... " + "Apple " * 3 + "reported."
    assert company_is_central("AAPL", "Apple Inc", headline="Tech earnings preview", text=many)


def test_ticker_like_words_use_word_boundaries():
    assert not company_is_central("ZS", "Zscaler", headline="Pizzas for all", text="pizzas")
