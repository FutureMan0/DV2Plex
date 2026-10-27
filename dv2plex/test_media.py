from fractions import Fraction
from pathlib import Path

import pytest

from dv2plex import media
from dv2plex.media import VideoInfo, audio_args_for_mp4, display_geometry
from dv2plex.merge import find_split_files, sort_splits, timestamp_from_filename
from dv2plex.upscale import UpscaleEngine, deinterlace_filter


@pytest.mark.parametrize("dar,box,expected", [
    (Fraction(4, 3), (3840, 2160), (2880, 2160)),
    (Fraction(16, 9), (3840, 2160), (3840, 2160)),
    (Fraction(4, 3), (1920, 1080), (1440, 1080)),
    (Fraction(16, 9), (1920, 1080), (1920, 1080)),
    (Fraction(21, 9), (3840, 2160), (3840, 1646)),
])
def test_display_geometry_keeps_the_aspect_with_square_pixels(dar, box, expected):
    assert display_geometry(dar, *box) == expected


def test_dv_pixel_aspect_gives_the_tape_aspect():
    pal_4_3 = VideoInfo(width=720, height=576, sar=Fraction(16, 15))
    ntsc_4_3 = VideoInfo(width=720, height=480, sar=Fraction(8, 9))
    pal_16_9 = VideoInfo(width=720, height=576, sar=Fraction(64, 45))
    assert pal_4_3.dar == Fraction(4, 3)
    assert ntsc_4_3.dar == Fraction(4, 3)
    assert pal_16_9.dar == Fraction(16, 9)


@pytest.mark.parametrize("codec,expected", [
    ("aac", ["-c:a", "copy"]),
    ("pcm_s16le", ["-c:a", "aac", "-b:a", "192k"]),
    (None, ["-an"]),
])
def test_dv_audio_is_converted_for_mp4(codec, expected):
    assert audio_args_for_mp4(VideoInfo(audio_codec=codec)) == expected


def test_deinterlacing_applies_to_dv_bottom_field_first():
    dv = VideoInfo(width=720, height=576)
    hd = VideoInfo(width=1920, height=1080, field_order="progressive")
    tff = VideoInfo(width=1920, height=1080, field_order="tt")
    assert "parity=bff" in deinterlace_filter(dv)
    assert deinterlace_filter(hd) is None
    assert "parity=tff" in deinterlace_filter(tff)
    assert deinterlace_filter(dv, False) is None


def test_upscale_filters_square_the_pixels():
    engine = UpscaleEngine(Path("missing.py"), ffmpeg_path=Path("ffmpeg"))
    filters = engine._scale_filters(VideoInfo(width=720, height=576, sar=Fraction(16, 15)), 4, True)
    assert filters[0].startswith("bwdif")
    assert "scale=2880:2160:flags=lanczos" in filters
    assert filters[-1] == "setsar=1"


def test_encoder_args_always_use_4_2_0():
    engine = UpscaleEngine(Path("missing.py"), ffmpeg_path=Path("ffmpeg"))
    args = engine._encoder_args({"encoder": "libx264", "encoder_options": {"crf": 17, "preset": "slow", "tune": "film"}})
    assert args[:2] == ["-c:v", "libx264"]
    assert ["-preset", "slow"] == args[2:4] and ["-crf", "17"] == args[4:6]
    assert "-tune" in args and args[-2:] == ["-pix_fmt", "yuv420p"]


def test_each_clip_is_found_once(tmp_path):
    for name in ("dvgrab-2003.06.14_15-47-11.avi", "dvgrab-2003.06.14_15-30-00.AVI", "notes.txt", ".hidden.avi"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "empty.avi").write_bytes(b"")

    found = sorted(p.name for p in find_split_files(tmp_path))

    assert found == ["dvgrab-2003.06.14_15-30-00.AVI", "dvgrab-2003.06.14_15-47-11.avi"]


def test_clips_are_sorted_by_recording_time(tmp_path):
    names = ["dvgrab-2003.06.14_16-04-22.avi", "dvgrab-2003.06.14_15-30-00.avi", "dvgrab2003.06.14_15-47-11.dv"]
    for name in names:
        (tmp_path / name).write_bytes(b"x")

    ordered = [p.name for p, _ in sort_splits(find_split_files(tmp_path))]

    assert ordered == [names[1], names[2], names[0]]
    assert timestamp_from_filename(names[2]).hour == 15


def test_escape_filter_path_for_windows_fonts():
    assert media.escape_filter_path(r"C:\Windows\Fonts\arial.ttf") == r"C\:/Windows/Fonts/arial.ttf"
