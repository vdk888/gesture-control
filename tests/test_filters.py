import time
from filters import OneEuroFilter


def test_filter_converges():
    f = OneEuroFilter(freq=60, fc_min=1.0, beta=0.007)
    # Feed constant value, should converge
    ts = time.time()
    for _ in range(100):
        val = f.filter(100.0, ts)
        ts += 1 / 60
    assert abs(val - 100.0) < 1.0


def test_filter_smooths_jitter():
    f = OneEuroFilter(freq=60, fc_min=1.0, beta=0.007)
    ts = time.time()
    values = []
    for i in range(100):
        v = 100.0 + (10.0 if i % 5 == 0 else 0.0)  # jitter every 5th frame
        values.append(f.filter(v, ts))
        ts += 1 / 60
    # Smoothed values should have less variance than raw
    import statistics
    assert statistics.stdev(values) < 8.0


def test_filter_responds_to_rapid_movement():
    f = OneEuroFilter(freq=60, fc_min=1.0, beta=0.007)
    ts = time.time()
    f.filter(0.0, ts)  # settle
    ts += 1 / 60
    result = f.filter(500.0, ts)  # fast cursor flick
    # Should track rapid movement closely
    assert result > 300.0
