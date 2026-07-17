import math


class FakeLandmark:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def test_dist():
    from hand_tracking import _dist

    a = FakeLandmark(0, 0)
    b = FakeLandmark(3, 4)
    assert _dist(a, b) == 5.0


def test_fingers_up_all_down():
    from hand_tracking import fingers_up

    # All landmarks clustered near wrist -> no fingers extended
    lm = [FakeLandmark(0.5, 0.9) for _ in range(21)]
    up = fingers_up(lm)
    assert up == [False, False, False, False, False]


def test_fingers_up_index_only():
    from hand_tracking import fingers_up

    lm = [FakeLandmark(0.5, 0.9) for _ in range(21)]
    lm[8] = FakeLandmark(0.5, 0.1)  # index tip up
    lm[7] = FakeLandmark(0.5, 0.5)  # index PIP
    up = fingers_up(lm)
    assert up[1] is True  # index
    assert up[2] is False  # middle still down


def test_name_gesture():
    from hand_tracking import name_gesture

    assert name_gesture([False, False, False, False, False]) == "Fist"
    assert name_gesture([True, True, True, True, True]) == "Open palm"
    assert name_gesture([False, True, False, False, False]) == "Pointing"
    assert name_gesture([True, False, False, False, False]) == "Thumbs up"
    assert name_gesture([False, True, True, False, False]) == "Peace"
