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


from saasshorts import build_ken_burns_cmd


class TestKenBurnsCmd:
    def test_cmd_loops_image_and_sets_duration(self):
        cmd = build_ken_burns_cmd("/tmp/in.png", "/tmp/out.mp4", 5)
        assert cmd[0] == "ffmpeg"
        assert "-loop" in cmd and "1" in cmd
        assert "/tmp/in.png" in cmd
        assert cmd[-1] == "/tmp/out.mp4"
        # duration honored
        i = cmd.index("-t")
        assert cmd[i + 1] == "5"

    def test_cmd_contains_zoompan_ken_burns(self):
        cmd = build_ken_burns_cmd("/tmp/in.png", "/tmp/out.mp4", 4)
        vf = cmd[cmd.index("-vf") + 1]
        assert "zoompan" in vf
        assert "s=1080x1920" in vf
        # 4s * 30fps = 120 frames drives the zoom denominator
        assert "120" in vf


from saasshorts import build_prepare_video_cmd


class TestPrepareVideoCmd:
    def test_silent_fallback_when_source_has_no_audio(self):
        cmd = build_prepare_video_cmd("/tmp/in.mp4", "/tmp/slot.mp4", has_audio=False)
        assert cmd[0] == "ffmpeg"
        assert "/tmp/in.mp4" in cmd
        assert cmd[-1] == "/tmp/slot.mp4"
        # a silent anullsrc input guarantees an audio stream even if src has none
        assert "anullsrc=r=44100:cl=stereo" in cmd
        assert "1:a" in cmd          # audio mapped from the silent source
        assert "-shortest" in cmd

    def test_uses_real_audio_when_present(self):
        cmd = build_prepare_video_cmd("/tmp/in.mp4", "/tmp/slot.mp4", has_audio=True)
        assert "anullsrc=r=44100:cl=stereo" not in cmd
        assert "0:a" in cmd          # audio mapped from the real input
        assert "0:v" in cmd
