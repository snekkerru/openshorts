"""Disposable-domain blocking and email alias normalization."""
from cloud import email_policy as ep


class TestDisposable:
    def test_known_temp_mail_blocked(self):
        assert ep.is_disposable("x@mailinator.com") is True
        assert ep.is_disposable("y@10minutemail.com") is True

    def test_db_observed_domains_blocked(self):
        assert ep.is_disposable("a@luckfeed.com") is True
        assert ep.is_disposable("b@web-library.net") is True

    def test_real_providers_allowed(self):
        for e in ("real@gmail.com", "u@outlook.com", "u@icloud.com", "u@yandex.ru"):
            assert ep.is_disposable(e) is False

    def test_case_insensitive(self):
        assert ep.is_disposable("X@MailInator.CoM") is True

    def test_list_loaded(self):
        assert ep.disposable_count() > 50


class TestNormalize:
    def test_gmail_dots_and_tags_stripped(self):
        assert ep.normalize_email("Foo.Bar+promo@gmail.com") == "foobar@gmail.com"
        assert ep.normalize_email("a.b.c@googlemail.com") == "abc@googlemail.com"

    def test_other_providers_strip_tag_keep_dots(self):
        assert ep.normalize_email("user+tag@outlook.com") == "user@outlook.com"
        # Dots are significant outside Gmail — must be preserved.
        assert ep.normalize_email("first.last@outlook.com") == "first.last@outlook.com"

    def test_non_aliasing_provider_untouched(self):
        assert ep.normalize_email("normal@yahoo.com") == "normal@yahoo.com"
        assert ep.normalize_email("a.b@protonmail.com") == "a.b@protonmail.com"

    def test_lowercased(self):
        assert ep.normalize_email("USER@Example.COM") == "user@example.com"
