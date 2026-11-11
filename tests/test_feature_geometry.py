"""Single-frame geometry: centers, torso angle, confidence handling, normalization."""

import math

import pytest

import synthetic as syn
from moeen.config import FeatureConfig
from moeen.features import FeatureExtractor, PostureLabel, ScaleSource
from moeen.features.posture_features import (Vec, bbox_aspect, pair_center, posture_indicators,
                                             ramp, torso_angle_deg)
from moeen.pose import landmark_utils as lu
from moeen.types import Landmark, PoseFrame

CFG = FeatureConfig()


def lm(x, y, vis=0.9, pres=0.9):
    return Landmark(x, y, 0.0, vis, pres)


def single(pose: syn.Pose2D, **render_kw):
    """Features of one frame of a static pose."""
    return FeatureExtractor(CFG).update(syn.render(syn.keyframes((0, pose)), 0.0, **render_kw)[0])


# ---------------------------------------------------------------- torso angle
def test_torso_angle_reference_directions():
    hip = Vec(0.5, 0.5)
    assert torso_angle_deg(Vec(0.5, 0.3), hip) == pytest.approx(0.0)      # straight up
    assert torso_angle_deg(Vec(0.7, 0.5), hip) == pytest.approx(90.0)     # horizontal right
    assert torso_angle_deg(Vec(0.3, 0.5), hip) == pytest.approx(90.0)     # horizontal left
    assert torso_angle_deg(Vec(0.5, 0.7), hip) == pytest.approx(180.0)    # upside down
    assert torso_angle_deg(hip, hip) is None                              # degenerate


def test_torso_angle_increases_monotonically_with_lean():
    angles = [single(syn.Pose2D(torso_deg=d)).torso_angle_deg for d in range(0, 181, 15)]
    assert all(b > a for a, b in zip(angles, angles[1:]))
    assert angles[0] == pytest.approx(0, abs=1e-6) and angles[-1] == pytest.approx(180, abs=1e-6)


def test_torso_angle_is_symmetric_left_right():
    assert single(syn.Pose2D(torso_deg=40)).torso_angle_deg == pytest.approx(
        single(syn.Pose2D(torso_deg=-40)).torso_angle_deg)


@pytest.mark.parametrize("w,h", [(640, 480), (1280, 720), (480, 640)])
def test_angle_is_correct_for_any_frame_aspect(w, h):
    # x is normalized by width, y by height; the extractor must undo that distortion.
    f = single(syn.Pose2D(torso_deg=45, hip_x=0.5 * w / h), width=w, height=h)
    assert f.torso_angle_deg == pytest.approx(45.0, abs=0.5)


# ---------------------------------------------------------------- centers
def test_centers_are_midpoints_in_normalized_coordinates():
    f = single(syn.STAND)
    pts = syn.landmarks_for(syn.STAND)
    aspect = syn.FRAME_W / syn.FRAME_H
    exp_sx = (pts[lu.LEFT_SHOULDER][0] + pts[lu.RIGHT_SHOULDER][0]) / 2 / aspect
    exp_hy = (pts[lu.LEFT_HIP][1] + pts[lu.RIGHT_HIP][1]) / 2
    assert f.shoulder_center.x == pytest.approx(exp_sx)
    assert f.hip_center.y == pytest.approx(exp_hy)
    assert f.body_center.y == pytest.approx((f.shoulder_center.y + f.hip_center.y) / 2)
    assert f.body_center_y == pytest.approx(f.body_center.y)
    assert f.shoulder_center.y < f.hip_center.y   # shoulders above hips when upright


def test_pair_center_falls_back_to_single_visible_side():
    lms = [lm(0, 0, vis=0.0)] * 33
    lms[lu.LEFT_SHOULDER] = lm(0.4, 0.3)
    lms[lu.RIGHT_SHOULDER] = lm(0.6, 0.3, vis=0.1)       # occluded
    c = pair_center(lms, lu.LEFT_SHOULDER, lu.RIGHT_SHOULDER, CFG, aspect=1.0)
    assert (c.x, c.y) == pytest.approx((0.4, 0.3))
    lms[lu.LEFT_SHOULDER] = lm(0.4, 0.3, pres=0.1)        # out of frame
    assert pair_center(lms, lu.LEFT_SHOULDER, lu.RIGHT_SHOULDER, CFG, aspect=1.0) is None


def test_low_confidence_torso_gives_unknown_not_crash():
    hidden = (lu.LEFT_SHOULDER, lu.RIGHT_SHOULDER)
    f = single(syn.STAND, hidden=hidden)
    assert f.pose_present
    assert f.shoulder_center is None and f.body_center is None
    assert f.torso_angle_deg is None and f.posture is PostureLabel.UNKNOWN
    assert not f.is_upright and not f.is_low_or_horizontal
    assert f.hip_center is not None          # what *is* visible is still reported
    assert f.landmark_quality == pytest.approx(0.5)


def test_non_finite_landmarks_are_ignored():
    frame = syn.render(syn.standing(), 0.0)[0]
    lms = list(frame.landmarks)
    lms[lu.LEFT_HIP] = Landmark(float("nan"), 0.5, 0.0, 0.9, 0.9)
    f = FeatureExtractor(CFG).update(PoseFrame(0, 640, 480, tuple(lms)))
    assert f.hip_center is not None and math.isfinite(f.hip_center.x)   # right hip only
    assert f.landmark_quality == pytest.approx(0.75)


def test_no_pose_frame_is_safe():
    f = FeatureExtractor(CFG).update(PoseFrame(0, 640, 480, None))
    assert not f.pose_present and f.posture is PostureLabel.UNKNOWN
    assert f.body_center_velocity is None and f.motion_magnitude is None


# ---------------------------------------------------------------- scale normalization
def test_scale_source_progression():
    ex = FeatureExtractor(CFG)
    assert ex.update(PoseFrame(0, 640, 480, None)).scale_source is ScaleSource.DEFAULT
    first = ex.update(syn.render(syn.standing(), 0.0, start_ms=33)[0])
    assert first.scale_source is ScaleSource.CURRENT          # no reference before this frame
    second = ex.update(syn.render(syn.standing(), 0.0, start_ms=66)[0])
    assert second.scale_source is ScaleSource.REFERENCE
    assert second.scale == pytest.approx(syn.STAND.torso, rel=0.02)


def test_torso_normalized_values_do_not_depend_on_camera_distance():
    near = single(syn.Pose2D(torso_deg=0))
    far = single(syn.scaled(syn.standing(), 0.5)(0))
    assert far.torso_length == pytest.approx(near.torso_length * 0.5, rel=0.01)
    assert far.torso_angle_deg == pytest.approx(near.torso_angle_deg, abs=1e-6)
    assert far.bbox_aspect == pytest.approx(near.bbox_aspect, rel=0.01)


# ---------------------------------------------------------------- helpers
def test_bbox_aspect_wide_vs_tall():
    tall = [Vec(0, 0), Vec(0.1, 0), Vec(0, 1), Vec(0.1, 1)]
    wide = [Vec(0, 0), Vec(1, 0), Vec(0, 0.1), Vec(1, 0.1)]
    assert bbox_aspect(tall) < 1 < bbox_aspect(wide)
    assert bbox_aspect(tall[:3]) is None


def test_ramp():
    assert [ramp(v, 1, 3) for v in (0, 1, 2, 3, 4)] == [0, 0, 0.5, 1, 1]


@pytest.mark.parametrize("angle,drop,aspect,label", [
    (5, 0.0, 0.3, PostureLabel.UPRIGHT),
    (5, 0.9, 0.5, PostureLabel.UPRIGHT),      # sitting on a chair
    (45, 0.0, 0.5, PostureLabel.TILTED),       # bending
    (85, 0.05, 0.4, PostureLabel.TILTED),      # deep bend: torso flat but hips stay high
    (10, 1.6, 0.6, PostureLabel.LOW),          # sitting on the floor
    (90, 1.6, 4.0, PostureLabel.HORIZONTAL),   # lying
    (90, None, 4.0, PostureLabel.HORIZONTAL),  # lying, no standing reference yet
    (None, 0.0, 0.3, PostureLabel.UNKNOWN),
])
def test_posture_label_table(angle, drop, aspect, label):
    assert posture_indicators(angle, drop, aspect, CFG).label is label


def test_scores_move_in_the_right_direction():
    lean = [posture_indicators(a, 0.0, 0.4, CFG) for a in (0, 20, 40, 60, 80)]
    assert all(b.tilt_score >= a.tilt_score for a, b in zip(lean, lean[1:]))
    assert all(b.upright_score <= a.upright_score for a, b in zip(lean, lean[1:]))
    drops = [posture_indicators(10, d, 0.5, CFG) for d in (0.0, 0.5, 0.9, 1.2, 2.0)]
    assert all(b.drop_score >= a.drop_score for a, b in zip(drops, drops[1:]))
    assert all(b.low_posture_score >= a.low_posture_score for a, b in zip(drops, drops[1:]))
    assert drops[0].low_posture_score == 0.0 and drops[-1].low_posture_score == 1.0
