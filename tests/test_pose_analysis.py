from app.pose_analysis import Point, extension_ratio, count_extension_cycles, summarize_pose_samples


def test_straight_vs_bent_arm():
    points = {11: Point(0.1, 0.1), 13: Point(0.3, 0.1), 15: Point(0.5, 0.1)}
    assert extension_ratio(points, 'left') > 0.99
    points[15] = Point(0.3, 0.3)
    assert extension_ratio(points, 'left') < 0.75


def test_occlusion_rejected():
    points = {11: Point(0.1, 0.1), 13: Point(0.3, 0.1), 15: Point(0.5, 0.1, 0.1)}
    assert extension_ratio(points, 'left') is None


def test_single_cycle_and_no_double_count():
    data = [(0.0, .70), (.1, .95), (.2, .96), (.3, .70), (.4, .95), (.5, .70),
            (.7, .7), (.8, .98), (1.0, .70)]
    assert count_extension_cycles(data) == [0.3, 1.0]


def test_occlusion_does_not_complete_cycle():
    assert count_extension_cycles([(0, .7), (.1, .98), (.2, None), (.3, .7)]) == []


def test_insufficient_frames_abstains():
    result = summarize_pose_samples([(i/10, None) for i in range(20)], 'left', 20)
    assert result['extension_cycle_candidates'] is None
    assert result['quality'] == 'insufficient_pose_visibility'


def test_experimental_label_not_claiming_coaching():
    data = [(i/10, .70 if i % 5 == 0 else .96) for i in range(20)]
    result = summarize_pose_samples(data, 'left', 20)
    assert result['technique_analyzed'] is False
    assert result['analysis_type'] == 'experimental_pose_extension_v1'
