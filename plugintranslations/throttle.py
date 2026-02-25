import time
from functools import wraps


class Throttle(object):
    """
    Decorator that prevents a function from being called more than once every time period.
    """

    def __init__(self, seconds: float = 0.5):
        time.monotonic()
        self.throttle_period = seconds
        self.time_of_last_call = 0.0

    def __call__(self, fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            now = time.monotonic()
            time_since_last_call = now - self.time_of_last_call

            if time_since_last_call > self.throttle_period:
                self.time_of_last_call = now
            else:
                wait_seconds = self.throttle_period - time_since_last_call
                time.sleep(wait_seconds)
                self.time_of_last_call = time.monotonic()

            return fn(*args, **kwargs)

        return wrapper
