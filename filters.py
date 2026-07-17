import math


class LowPassFilter:
    def __init__(self, alpha=1.0):
        self._y = None
        self.alpha = alpha

    def filter(self, value, alpha=None):
        if alpha is not None:
            self.alpha = alpha
        if self._y is None:
            self._y = value
        else:
            self._y = self._y + self.alpha * (value - self._y)
        return self._y

    def reset(self):
        self._y = None


class OneEuroFilter:
    """1Euro filter for low-latency cursor smoothing.
    Reference: G. Casiez, N. Roussel, D. Vogel. CHI 2012.
    """
    def __init__(self, freq=60, fc_min=1.0, beta=0.007, dc_cutoff=1.0):
        self.freq = freq
        self.fc_min = fc_min
        self.beta = beta
        self.dc_cutoff = dc_cutoff
        self._x = LowPassFilter(alpha=self._alpha(dc_cutoff))
        self._dx = LowPassFilter(alpha=self._alpha(dc_cutoff))
        self._last_t = None
        self._last_val = None

    def _alpha(self, cutoff):
        tau = 1.0 / (2 * math.pi * cutoff)
        te = 1.0 / self.freq
        return 1.0 / (1.0 + tau / te)

    def filter(self, value, timestamp):
        if self._last_val is None or self._last_t is None:
            self._last_val = value
            self._last_t = timestamp
            return value

        dt = max(timestamp - self._last_t, 1e-6)
        dx = (value - self._last_val) / dt

        edx = self._dx.filter(dx, alpha=self._alpha(self.dc_cutoff))
        cutoff = self.fc_min + self.beta * abs(edx)
        result = self._x.filter(value, alpha=self._alpha(cutoff))

        self._last_val = value
        self._last_t = timestamp
        return result

    def reset(self):
        self._x.reset()
        self._dx.reset()
        self._last_t = None
        self._last_val = None
