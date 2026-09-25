"""Track bottom-center crossings of a configurable finite virtual line."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class NormalizedLine:
    """Line endpoints as fractions of frame width and height (0 through 1)."""

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self):
        values = (self.x1, self.y1, self.x2, self.y2)
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError("line coordinates must be finite numbers between 0 and 1")
        if (self.x1, self.y1) == (self.x2, self.y2):
            raise ValueError("line endpoints must differ")

    def pixels(self, width, height):
        return ((self.x1 * (width - 1), self.y1 * (height - 1)),
                (self.x2 * (width - 1), self.y2 * (height - 1)))


def bottom_center(box):
    """Use the ground-facing midpoint of an xyxy vehicle bounding box."""
    x1, _, x2, y2 = box
    return ((x1 + x2) / 2, y2)


class LineCrossingDetector:
    """Confirm a side change beyond a dead zone after crossing the segment."""

    def __init__(self, line, dead_zone=0.02):
        if not math.isfinite(dead_zone) or not 0 <= dead_zone < 1:
            raise ValueError("dead zone must be a finite fraction from 0 to less than 1")
        self.line = line
        self.dead_zone = dead_zone
        self.previous = {}  # track ID -> (last point, confirmed side, crossed segment)

    def update(self, track_id, point, frame_size):
        """Return a direction string for a crossing, otherwise None.

        frame_size is (width, height). A is the positive cross-product side
        of the directed line from endpoint 1 to endpoint 2; B is negative.
        The dead-zone width is a fraction of the shorter frame dimension.
        Points in that zone retain the last confirmed side. A crossing is
        emitted only after reaching the opposite side outside the zone.
        """
        start, end = self.line.pixels(*frame_size)
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length == 0:
            raise ValueError("frame is too small for the virtual line")
        signed = dx * (point[1] - start[1]) - dy * (point[0] - start[0])
        margin = self.dead_zone * min(frame_size)
        distance = signed / length
        side = 1 if distance > margin else -1 if distance < -margin else 0
        previous = self.previous.get(track_id)
        if previous is None:
            if side:
                self.previous[track_id] = (point, side, False)
            return None

        old_point, confirmed_side, crossed = previous
        old_signed = dx * (old_point[1] - start[1]) - dy * (old_point[0] - start[0])
        if old_signed * signed <= 0 and old_signed != signed:
            fraction = old_signed / (old_signed - signed)
            crossing = (old_point[0] + fraction * (point[0] - old_point[0]),
                        old_point[1] + fraction * (point[1] - old_point[1]))
            projection = ((crossing[0] - start[0]) * dx +
                          (crossing[1] - start[1]) * dy) / (length * length)
            crossed = crossed or 0 <= projection <= 1

        direction = None
        if side == confirmed_side:
            crossed = False
        elif side == -confirmed_side:
            if crossed:
                direction = "A -> B" if confirmed_side > 0 else "B -> A"
            confirmed_side = side
            crossed = False
        self.previous[track_id] = (point, confirmed_side, crossed)
        return direction
