"""Application icon, drawn in code so the window and the installed app share one mark."""

# ================================== Imports ================================== #
# Standard Library
from io import BytesIO

# Third-party
from PIL import Image, ImageDraw

# ================================== Constants ================================ #
_BACKGROUND = (18, 20, 26, 255)
_CELL = (48, 56, 72, 255)
_AMBER = (230, 179, 37, 255)
_GREEN = (61, 214, 140, 255)
_BLUE = (92, 154, 255, 255)
_RED = (255, 107, 107, 255)
# (row, column) of the 3×3 grid that uses a channel color. The rest stay neutral.
_ACCENTS = {(0, 1): _AMBER, (1, 0): _GREEN, (1, 2): _BLUE, (2, 1): _RED}


# ================================== Drawing ================================== #
def render_icon(size: int) -> Image.Image:
    """Draws the Pixel Viewer mark at ``size`` × ``size``.

    Args:
        size: Edge length in pixels. Smaller than 16 is rejected because the grid would collapse.

    Returns:
        An RGBA image with a rounded dark tile and a 3×3 pixel grid.

    Raises:
        ValueError: If ``size`` is below 16.
    """
    if size < 16:
        raise ValueError(f"Icon size must be at least 16, not {size}.")
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = max(3, round(size * 0.22))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=_BACKGROUND)

    count = 3
    margin = size * 0.22
    gap = max(1.0, size * 0.045)
    cell = (size - 2 * margin - (count - 1) * gap) / count
    corner = max(1, round(cell * 0.2))
    for row in range(count):
        for column in range(count):
            left = round(margin + column * (cell + gap))
            top = round(margin + row * (cell + gap))
            right = round(left + cell)
            bottom = round(top + cell)
            draw.rounded_rectangle((left, top, right, bottom), radius=corner, fill=_ACCENTS.get((row, column), _CELL))
    return image


def render_icon_png(size: int) -> bytes:
    """Returns ``render_icon`` encoded as PNG bytes."""
    buffer = BytesIO()
    render_icon(size).save(buffer, format="PNG")
    return buffer.getvalue()
