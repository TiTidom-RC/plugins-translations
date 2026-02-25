import time
from functools import wraps
from typing import Any


class Throttle(object):
    """
    Decorator that prevents a function from being called more than once every time period.
    Works for both standalone functions and instance methods (per-instance throttle state).
    """

    def __init__(self, seconds: float = 0.5):
        self.throttle_period = seconds
        self.time_of_last_call: float = 0.0
        self._fn: Any = None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._fn is None:
            # Being used as a decorator: @Throttle(seconds=x)
            fn = args[0]
            self._fn = fn
            wraps(fn)(self)
            return self
        # Being called as a standalone function (not a method — __get__ handles methods)
        fn = self._fn
        now = time.monotonic()
        time_since_last_call = now - self.time_of_last_call
        if time_since_last_call > self.throttle_period:
            self.time_of_last_call = now
        else:
            wait_seconds = self.throttle_period - time_since_last_call
            time.sleep(wait_seconds)
            self.time_of_last_call = time.monotonic()
        return fn(*args, **kwargs)

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Descriptor protocol: returns a bound wrapper with per-instance throttle state."""
        if obj is None:
            return self
        fn = self._fn
        if fn is None:
            raise RuntimeError("Throttle descriptor used before decorating a function")
        attr = f'_throttle_{fn.__name__}_last_call'
        throttle_period = self.throttle_period

        @wraps(fn)
        def bound_wrapper(*args: Any, **kwargs: Any) -> Any:
            now = time.monotonic()
            last: float = getattr(obj, attr, 0.0)
            time_since_last_call = now - last
            if time_since_last_call > throttle_period:
                setattr(obj, attr, now)
            else:
                wait_seconds = throttle_period - time_since_last_call
                time.sleep(wait_seconds)
                setattr(obj, attr, time.monotonic())
            return fn(obj, *args, **kwargs)

        return bound_wrapper
