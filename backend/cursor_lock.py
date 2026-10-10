"""Contact-scoped cursor confinement, with explicit mouse and focus release."""


class CursorLock:
    def __init__(self, read_bounds, clip, anchor):
        self.read_bounds = read_bounds
        self.clip = clip
        self.anchor = anchor
        self.previous = None
        self.locked = None
        self.mouse_override = False

    def touch(self, down):
        if not down:
            self.release()
            self.mouse_override = False
        elif not self.mouse_override and self.locked is None:
            previous = self.read_bounds()
            x, y = self.anchor
            bounds = (x, y, x+1, y+1)
            self.clip(bounds)
            self.previous, self.locked = previous, bounds

    def external_mouse(self):
        self.release()
        # A mouse takes priority until the current finger contact has ended.
        self.mouse_override = True

    def release(self):
        if self.locked is not None:
            try:
                # Do not overwrite confinement installed by a different application.
                if self.read_bounds() == self.locked:
                    self.clip(self.previous)
            finally:
                self.locked = None

