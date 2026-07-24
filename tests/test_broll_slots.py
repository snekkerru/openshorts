from saasshorts import classify_broll_slot


def _seg(**kw):
    base = {"visual": "broll", "broll_prompt": "a cat", "start": 5, "end": 9}
    base.update(kw)
    return base


class TestClassifyBrollSlot:
    def test_missing_source_defaults_to_ai(self):
        r = classify_broll_slot(_seg())
        assert r["source"] == "ai"
        assert r["prompt"] == "a cat"
        assert r["asset_path"] is None
        assert r["audio_mode"] == "voiceover"

    def test_invalid_source_falls_back_to_ai(self):
        assert classify_broll_slot(_seg(broll_source="banana"))["source"] == "ai"

    def test_image_source_uses_asset_path(self):
        r = classify_broll_slot(_seg(broll_source="image", broll_asset_path="/x/y.png"))
        assert r["source"] == "image"
        assert r["asset_path"] == "/x/y.png"
        assert r["audio_mode"] == "voiceover"  # images never mix

    def test_image_without_asset_falls_back_to_ai(self):
        # No usable file -> don't silently render nothing; fall back to AI.
        assert classify_broll_slot(_seg(broll_source="image", broll_asset_path=None))["source"] == "ai"

    def test_video_mute_true_is_voiceover(self):
        r = classify_broll_slot(_seg(broll_source="video", broll_asset_path="/x/y.mp4", broll_mute_audio=True))
        assert r["source"] == "video"
        assert r["audio_mode"] == "voiceover"

    def test_video_mute_false_is_mix(self):
        r = classify_broll_slot(_seg(broll_source="video", broll_asset_path="/x/y.mp4", broll_mute_audio=False))
        assert r["audio_mode"] == "mix"

    def test_video_mute_defaults_true(self):
        r = classify_broll_slot(_seg(broll_source="video", broll_asset_path="/x/y.mp4"))
        assert r["audio_mode"] == "voiceover"
