"""
Game entities (bird, pipes, scrolling ground) and low-level OpenGL drawing.

Coordinates: 2D orthographic, origin bottom-left. Y increases upward.
"""

from itertools import cycle
from random import randint

from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *

# Window size and ground height (fraction of screen).
SCREENWIDTH = 600
SCREENHEIGHT = 720
BASEY = SCREENHEIGHT * 0.2


def random_pipe_gap_center_y(gap_size=150):
    """Pick a random vertical center for the gap between top and bottom pipe."""
    margin = int(gap_size / 2) + 95
    return randint(int(BASEY) + margin, SCREENHEIGHT - margin)


def draw_textured_quad(left, right, bottom, top, texture_id, z=0):
    """
    Draw an axis-aligned rectangle with a 2D texture (GL_QUADS).
    Texture coords (0,0)-(1,1) map to the quad corners; z is used for draw order.
    """
    glPushMatrix()
    glBindTexture(GL_TEXTURE_2D, texture_id)
    glBegin(GL_QUADS)
    glTexCoord(0, 0)
    glVertex(left, bottom, z)
    glTexCoord(0, 1)
    glVertex(left, top, z)
    glTexCoord(1, 1)
    glVertex(right, top, z)
    glTexCoord(1, 0)
    glVertex(right, bottom, z)
    glEnd()
    glPopMatrix()


class Pipe:
    """One obstacle: lower segment + upper segment with a vertical gap."""

    def __init__(self, texture_ids, gap_size=150):
        self.gap_size = gap_size
        self.width = 70
        self.gap_y = random_pipe_gap_center_y(gap_size)
        self.left = SCREENWIDTH
        self.right = self.left + self.width
        self.upper_y = self.gap_y + self.gap_size * 0.5
        self.lower_y = self.gap_y - self.gap_size * 0.5
        # True after the bird has passed this pipe and earned one point.
        self.point_awarded = False
        self.tex = texture_ids

    def draw(self):
        """Lower pipe uses tex[0], upper (flipped) uses tex[1]."""
        draw_textured_quad(self.left, self.right, -300, self.lower_y, self.tex[0])
        draw_textured_quad(self.left, self.right, self.upper_y, SCREENHEIGHT + 400, self.tex[1])

    def scroll_horizontally(self, delta_x):
        """Move the pipe left (negative delta_x) with the world scroll."""
        self.left += delta_x
        self.right += delta_x


class Bird:
    """Player: flaps, falls with gravity, wing animation cycles through 3 sprites."""

    WING_FRAME_INTERVAL = 12

    def __init__(self, texture_ids, gravity=0.2, angular_speed=0.5):
        self.height = 40
        self.width = 1.3 * self.height
        self.right = SCREENWIDTH * 0.3
        self.left = self.right - self.width
        self.bottom = SCREENHEIGHT * 0.5
        self.top = self.bottom + self.height
        self.angle = 0

        self.fly_speed = 0.65
        self.velocity = 0
        self.gravity = gravity
        self._initial_gravity = gravity
        self._initial_velocity = 0
        self.angular_s = angular_speed
        self._initial_angular_s = angular_speed

        self.swap = True
        self.tex = texture_ids
        self._wing_frame_cycle = cycle([0, 1, 2, 1])
        self.tex_index = 0
        self._wing_tick = 0

    def _bounding_box_center(self):
        """Center of the bird's axis-aligned box (for rotation around middle)."""
        cx = (self.right + self.left) * 0.5
        cy = (self.bottom + self.top) * 0.5
        return cx, cy

    def draw(self):
        """Draw the bird rotated by self.angle; advance wing frame if animating."""
        cx, cy = self._bounding_box_center()
        glPushMatrix()
        glLoadIdentity()
        glTranslate(cx, cy, 0)
        glRotate(self.angle, 0, 0, 1)
        glTranslate(-cx, -cy, 0)
        draw_textured_quad(self.left, self.right, self.bottom, self.top, self.tex[self.tex_index], 0.8)
        glPopMatrix()

        if self.swap:
            self._wing_tick += 1
            if self._wing_tick % self.WING_FRAME_INTERVAL == 0:
                self.tex_index = next(self._wing_frame_cycle)

    def animate_welcome_hover(self, hover_range=15):
        """
        Title screen only: gentle vertical bob; reverses direction at hover_range from mid-screen.
        """
        self.draw()
        self.bottom += self.fly_speed
        self.top += self.fly_speed
        mid = SCREENHEIGHT * 0.5
        if self.bottom < mid - hover_range or self.bottom > mid + hover_range:
            self.fly_speed *= -1

    def step_physics_and_draw(self):
        """
        One gameplay frame: apply velocity and gravity, tilt sprite with motion, then draw.
        """
        if self.bottom > BASEY:
            self.bottom += self.velocity
            self.top += self.velocity
            if self.velocity >= 0:
                if self.angle < 30:
                    self.angle += self.angular_s
            elif self.angle > -90:
                self.angle -= self.angular_s * 0.3

        if self.top >= SCREENHEIGHT:
            self.velocity = 0

        self.velocity += self.gravity
        self.draw()

    def step_death_physics_and_draw(self):
        """After collision: stop wing animation, fall faster, same physics step as gameplay."""
        self.swap = False
        self.velocity += self.gravity
        self.angular_s += 0.3
        self.step_physics_and_draw()

    def reset_to_start_position(self):
        """Default pose for a new run (welcome or after game over)."""
        self.right = SCREENWIDTH * 0.3
        self.left = self.right - self.width
        self.bottom = SCREENHEIGHT * 0.5
        self.top = self.bottom + self.height
        self.angle = 0
        self.velocity = self._initial_velocity
        self.gravity = self._initial_gravity
        self.angular_s = self._initial_angular_s
        self.swap = True


class Base:
    """Tiled ground strip that scrolls and wraps for an infinite-looking floor."""

    def __init__(self, texture_id, z=0.1):
        self.tex = texture_id
        self.z = z
        self.width = 2 * SCREENWIDTH + 5
        self.right = 2 * SCREENWIDTH
        self.left = self.right - self.width
        self.top = BASEY
        self.bottom = 0

    def draw(self):
        """Repeat texture horizontally (tex coords 0–2) across the wide quad."""
        glPushMatrix()
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glBegin(GL_QUADS)
        glTexCoord(0, 0)
        glVertex(self.left, self.bottom, self.z)
        glTexCoord(0, 1)
        glVertex(self.left, self.top, self.z)
        glTexCoord(2, 1)
        glVertex(self.right, self.top, self.z)
        glTexCoord(2, 0)
        glVertex(self.right, self.bottom, self.z)
        glEnd()
        glPopMatrix()

    def scroll_horizontally(self, delta_x):
        """Move with the world; reset position when the strip has scrolled far enough left."""
        if self.right <= SCREENWIDTH + 1:
            self.right = 2 * SCREENWIDTH
        self.right += delta_x
        self.left = self.right - self.width
