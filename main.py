import json
from enum import IntEnum
from itertools import cycle
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from OpenGL.GL import *
from OpenGL.GLU import *
import pygame
from pygame.locals import DOUBLEBUF, OPENGL, QUIT, KEYDOWN, K_q, K_SPACE, K_1, K_2, K_3, MOUSEBUTTONDOWN

from classes import (
    BASEY,
    Bird,
    Base,
    Pipe,
    SCREENHEIGHT,
    SCREENWIDTH,
    draw_textured_quad,
)

# ---------------------------------------------------------------------------
# Audio: pygame.mixer is absent on some Python builds; use silent no-ops then.
# ---------------------------------------------------------------------------
try:
    import pygame.mixer as mixer

    mixer.init()
except (ImportError, NotImplementedError, ModuleNotFoundError):

    class _SilentSound:
        def __init__(self, path=None):
            pass

        def play(self):
            pass

    class _MixerStub:
        Sound = _SilentSound

        @staticmethod
        def init():
            pass

    mixer = _MixerStub()


# Asset folders (paths are relative to this file).
ROOT = Path(__file__).resolve().parent
SPRITES = ROOT / "assets" / "sprites"
AUDIO = ROOT / "assets" / "audio"


class GameState(IntEnum):
    """Which screen/logic is active."""

    WELCOME = 0
    MAIN = 1
    GAME_OVER = 2


# Order of states when the player presses space to continue (matches original game flow).
_STATE_ORDER = (GameState.MAIN, GameState.GAME_OVER, GameState.WELCOME)
_state_cycle = cycle(_STATE_ORDER)

# --- Difficulty & timing (timer fires every TIMER_MS → one frame update) ---
TIMER_MS = 10
SCROLL_SPEED_START = -1.5
SCROLL_SPEED_MAX = -3.0
SCROLL_RAMP_FRAMES = 500
GRAVITY_EASE_START = -0.12
GRAVITY = -0.22
JUMP_VELOCITY = 4.0
ANGULAR_SPEED = 3

# Spawn a new pipe when the rightmost pipe’s left edge reaches this x.
PIPE_SPAWN_DISTANCE = SCREENWIDTH / 2

# --- Mutable runtime state ---
current_state = GameState.WELCOME
score = 0
max_scores = {"EASY": 0, "MEDIUM": 0, "HARD": 0}
level = 1
points_needed_for_next_level = 4
current_difficulty = None

DIFFICULTIES = {
    "EASY": {"gap": 250, "scroll_speed_start": -1.0, "scroll_speed_max": -1.5, "gravity": -0.12, "jump": 2.5},
    "MEDIUM": {"gap": 180, "scroll_speed_start": -1.2, "scroll_speed_max": -2.0, "gravity": -0.15, "jump": 3.0},
    "HARD": {"gap": 140, "scroll_speed_start": -1.5, "scroll_speed_max": -2.5, "gravity": -0.18, "jump": 3.5},
}

BUTTONS = {
    "EASY": (200, 300, 200, 50),
    "MEDIUM": (200, 230, 200, 50),
    "HARD": (200, 160, 200, 50)
}

def draw_colored_rect(x, y, w, h, color, z=0.8):
    glPushMatrix()
    glDisable(GL_TEXTURE_2D)
    glColor4f(color[0], color[1], color[2], color[3] if len(color) == 4 else 1.0)
    glBegin(GL_QUADS)
    glVertex3f(x, y, z)
    glVertex3f(x, y + h, z)
    glVertex3f(x + w, y + h, z)
    glVertex3f(x + w, y, z)
    glEnd()
    glColor4f(1, 1, 1, 1)
    glEnable(GL_TEXTURE_2D)
    glPopMatrix()

def load_high_score():
    global max_scores
    max_scores = {"EASY": 0, "MEDIUM": 0, "HARD": 0}
    try:
        with open("high_score.txt", "r") as f:
            content = f.read().strip()
            if content.startswith("{"):
                max_scores.update(json.loads(content))
            else:
                max_scores["MEDIUM"] = int(content)
    except Exception:
        pass

def save_high_score():
    try:
        with open("high_score.txt", "w") as f:
            json.dump(max_scores, f)
    except Exception:
        pass

def save_current_score_if_max():
    global max_scores
    if current_difficulty and score > max_scores[current_difficulty]:
        max_scores[current_difficulty] = score
        save_high_score()

main_game_frames = 0
pipes = []
bird = None
base = None
window = None
textures = {}
sounds = {}
text_texture_cache = {}

def get_text_texture(text, font_size=32, color=(255, 255, 255)):
    key = (text, font_size, color)
    if key in text_texture_cache:
        return text_texture_cache[key]
    
    font = ImageFont.load_default()
    
    dummy_img = Image.new("RGBA", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    try:
        bbox = dummy_draw.textbbox((0, 0), text, font=font)
    except AttributeError:
        # Fallback for very old PIL
        w, h = dummy_draw.textsize(text, font=font)
        bbox = (0, 0, w, h)
        
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    
    # Render at native size
    im = Image.new("RGBA", (max(1, w), max(1, h)), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    d.text((-bbox[0], -bbox[1]), text, font=font, fill=(color[0], color[1], color[2], 255))
    
    # Scale it to match requested font_size approximately (default font height is ~11px)
    scale = max(1, font_size // 11)
    if scale > 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
        w, h = im.width, im.height
        
    # Flip vertical for OpenGL
    im = im.transpose(Image.FLIP_TOP_BOTTOM)
    data = im.tobytes()
    
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tid)
    glTexParameter(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
    glTexParameter(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
    
    text_texture_cache[key] = (normalize_gl_texture_name(tid), w, h)
    return text_texture_cache[key]

def draw_text(x, y, text, font_size=32, color=(0, 0, 0), z=0.9):
    tid, w, h = get_text_texture(text, font_size, color)
    
    glPushMatrix()
    glBindTexture(GL_TEXTURE_2D, tid)
    glBegin(GL_QUADS)
    glTexCoord(0, 0); glVertex(x, y, z)
    glTexCoord(0, 1); glVertex(x, y + h, z)
    glTexCoord(1, 1); glVertex(x + w, y + h, z)
    glTexCoord(1, 0); glVertex(x + w, y, z)
    glEnd()
    glPopMatrix()


def path_to_sprite_file(filename: str) -> Path:
    """Full path to a PNG under assets/sprites/."""
    return SPRITES / filename


def load_game_sound_effects():
    """Load die / jump / point clips into the global sounds dict."""
    ext = ".ogg"
    for key in ("die", "jump", "point"):
        sounds[key] = mixer.Sound(str(AUDIO / f"{key}{ext}"))


def load_image_as_rgba_bytes(path: Path, flip_vertical: bool):
    """
    Read an image as raw RGBA bytes for gluBuild2DMipmaps.

    flip_vertical: match legacy pygame row order (OpenGL expects bottom-first for some uploads).
    Returns (width, height, bytes).
    """
    im = Image.open(path).convert("RGBA")
    if flip_vertical:
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
    return im.width, im.height, im.tobytes()


def normalize_gl_texture_name(handle):
    """PyOpenGL may return one GLuint or a length-1 array; always get a Python int."""
    try:
        return int(handle[0])
    except (TypeError, IndexError, ValueError):
        return int(handle)


def upload_rgba_image_to_texture_2d(texture_name, width, height, rgba_bytes, min_filter=GL_LINEAR_MIPMAP_LINEAR):
    """Bind a texture name, set sampling/wrap, upload mipmaps from RGBA byte buffer."""
    glBindTexture(GL_TEXTURE_2D, normalize_gl_texture_name(texture_name))
    glTexParameter(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameter(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, min_filter)
    glTexParameter(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
    glTexParameter(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
    gluBuild2DMipmaps(GL_TEXTURE_2D, 4, width, height, GL_RGBA, GL_UNSIGNED_BYTE, rgba_bytes)


def load_pipe_texture_pair():
    """Two sub-images from one PNG: normal and vertically flipped for upper pipe."""
    path = path_to_sprite_file("pipe-green.png")
    w, h, lower = load_image_as_rgba_bytes(path, flip_vertical=True)
    _, _, upper = load_image_as_rgba_bytes(path, flip_vertical=False)
    ids = glGenTextures(2)
    upload_rgba_image_to_texture_2d(ids[0], w, h, lower)
    upload_rgba_image_to_texture_2d(ids[1], w, h, upper)
    textures["pipe"] = ids


def load_bird_wing_animation_textures():
    """Three frames cycled on the bird (up / mid / down)."""
    paths = [path_to_sprite_file(n) for n in ("up.png", "mid.png", "down.png")]
    layers = [load_image_as_rgba_bytes(p, flip_vertical=True) for p in paths]
    ids = glGenTextures(3)
    for i, (w, h, data) in enumerate(layers):
        upload_rgba_image_to_texture_2d(ids[i], w, h, data)
    textures["bird"] = ids


def load_score_digit_textures():
    """0.png … 9.png for HUD."""
    layers = [load_image_as_rgba_bytes(path_to_sprite_file(f"{i}.png"), True) for i in range(10)]
    ids = glGenTextures(10)
    for i, (w, h, data) in enumerate(layers):
        upload_rgba_image_to_texture_2d(ids[i], w, h, data)
    textures["numbers"] = {str(i): ids[i] for i in range(10)}


def load_single_sprite_texture(cache_key: str, filename: str, *, use_full_mipmap_chain=True):
    """One-off UI or world sprite stored under textures[cache_key]."""
    w, h, data = load_image_as_rgba_bytes(path_to_sprite_file(filename), True)
    tid = glGenTextures(1)
    min_filter = GL_LINEAR_MIPMAP_LINEAR if use_full_mipmap_chain else GL_LINEAR
    upload_rgba_image_to_texture_2d(tid, w, h, data, min_filter)
    textures[cache_key] = normalize_gl_texture_name(tid)


def load_all_sprite_textures():
    """Populate global textures dict once at startup."""
    load_pipe_texture_pair()
    load_bird_wing_animation_textures()
    load_single_sprite_texture("background", "background-day.png")
    load_score_digit_textures()
    load_single_sprite_texture("base", "base.png")
    load_single_sprite_texture("msg", "message.png")
    load_single_sprite_texture("game_over", "gameover.png")
    load_single_sprite_texture("start", "start.png", use_full_mipmap_chain=False)
    load_single_sprite_texture("restart", "res.png", use_full_mipmap_chain=False)


def configure_orthographic_projection():
    """2D view: x in [0, SCREENWIDTH], y in [0, SCREENHEIGHT]."""
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    glOrtho(0, SCREENWIDTH, 0, SCREENHEIGHT, -3, 3)
    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()


def setup_opengl_and_load_assets():
    """Clear color, depth, blending, textures, entities, projection."""
    glClearColor(1, 1, 1, 0)
    glEnable(GL_DEPTH_TEST)
    glEnable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    load_all_sprite_textures()
    create_initial_entities()
    configure_orthographic_projection()


def create_initial_entities():
    """First pipe, bird, and ground; clears the pipe list."""
    global bird, base
    pipes.clear()
    diff_key = current_difficulty if current_difficulty is not None else "MEDIUM"
    diff_conf = DIFFICULTIES[diff_key]
    pipes.append(Pipe(textures["pipe"], gap_size=diff_conf["gap"]))
    bird = Bird(textures["bird"], diff_conf["gravity"], ANGULAR_SPEED)
    base = Base(textures["base"], 0.1)


def go_to_next_state_in_flow():
    """Advance the shared cycle (used after space on welcome / after death / after game over)."""
    global current_state
    current_state = next(_state_cycle)


def handle_keyboard(key, _mouse_x, _mouse_y):
    """Space: jump or advance menus. Q: quit."""
    global score, pipes, main_game_frames, current_difficulty, level, points_needed_for_next_level

    if key == b"q":
        return

    if current_state == GameState.WELCOME:
        if key == b"1":
            current_difficulty = "EASY"
            sounds["jump"].play()
            return
        elif key == b"2":
            current_difficulty = "MEDIUM"
            sounds["jump"].play()
            return
        elif key == b"3":
            current_difficulty = "HARD"
            sounds["jump"].play()
            return

    if key != b" ":
        return

    if current_state == GameState.MAIN:
        sounds["jump"].play()
        bird.velocity = DIFFICULTIES[current_difficulty].get("jump", JUMP_VELOCITY)
    elif current_state == GameState.WELCOME:
        if current_difficulty is None:
            return
        sounds["jump"].play()
        bird.reset_to_start_position()
        bird.velocity = DIFFICULTIES[current_difficulty].get("jump", JUMP_VELOCITY)
        main_game_frames = 0
        level = 1
        points_needed_for_next_level = 4
        create_initial_entities()
        go_to_next_state_in_flow()
    elif current_state == GameState.GAME_OVER:
        current_difficulty = None
        create_initial_entities()
        bird.reset_to_start_position()
        score = 0
        level = 1
        points_needed_for_next_level = 4
        go_to_next_state_in_flow()

def handle_mouse_click(mouse_x, mouse_y):
    global current_difficulty
    if current_state == GameState.WELCOME:
        gl_y = SCREENHEIGHT - mouse_y
        for diff, (bx, by, bw, bh) in BUTTONS.items():
            if bx <= mouse_x <= bx + bw and by <= gl_y <= by + bh:
                current_difficulty = diff
                sounds["jump"].play()
                # Start the game immediately upon selection
                handle_keyboard(b" ", 0, 0)
                return
        
        # If they click anywhere else and difficulty is selected, start the game
        if current_difficulty is not None:
            handle_keyboard(b" ", 0, 0)
    elif current_state == GameState.MAIN:
        handle_keyboard(b" ", 0, 0)
    elif current_state == GameState.GAME_OVER:
        handle_keyboard(b" ", 0, 0)


def draw_parallax_background():
    """Full-screen day background (slightly taller than screen to hide seams)."""
    draw_textured_quad(0, SCREENWIDTH, 0, SCREENHEIGHT + 5, textures["background"], -1)


def draw_score_overlay(digit_string: str):
    """Centered digit sprites near the top for the current score."""
    digit_width = 40
    digit_height = int(digit_width * 1.5)
    glPushMatrix()
    glTranslate(-(len(digit_string) / 2 + 1) * digit_width, 0, 0)
    for ch in digit_string:
        glTranslate(digit_width, 0, 0)
        draw_textured_quad(
            0.5 * SCREENWIDTH,
            0.5 * SCREENWIDTH + digit_width,
            0.85 * SCREENHEIGHT,
            0.85 * SCREENHEIGHT + digit_height,
            textures["numbers"][ch],
            0.5,
        )
    glPopMatrix()


def draw_welcome_screen_sprites():
    """Logo + tap-to-start hint on the ground band."""
    draw_textured_quad(50, 550, 420, 720, textures["msg"], 0.5) 
    # Removed textures["start"] because it overlaps with the new difficulty buttons


def draw_game_over_screen_sprites():
    """Game over banner + restart hint."""
    draw_textured_quad(100, 500, 400, 600, textures["game_over"], 0.5)
    draw_textured_quad(0, SCREENWIDTH, 0, BASEY + 200, textures["restart"], 0.9)


def run_welcome_frame():
    """Title state: UI + idle bird motion."""
    draw_welcome_screen_sprites()
    bird.animate_welcome_hover()
    
    if current_difficulty:
        draw_text(10, SCREENHEIGHT - 40, f"Max Score: {max_scores[current_difficulty]}", 36, (0, 0, 0))
    else:
        scores_str = f"Max Scores - E:{max_scores['EASY']} M:{max_scores['MEDIUM']} H:{max_scores['HARD']}"
        draw_text(10, SCREENHEIGHT - 40, scores_str, 24, (0, 0, 0))
    
    mouse_x, mouse_y = pygame.mouse.get_pos()
    gl_y = SCREENHEIGHT - mouse_y
    
    for diff, (bx, by, bw, bh) in BUTTONS.items():
        is_hovered = bx <= mouse_x <= bx + bw and by <= gl_y <= by + bh
        
        if current_difficulty == diff:
            color = (0.2, 0.8, 0.2, 1.0)
        elif is_hovered:
            color = (0.5, 0.9, 0.5, 1.0)  # Light green for hover
        else:
            color = (0.7, 0.7, 0.7, 1.0)
        
        draw_colored_rect(bx, by, bw, bh, color)
        
        text_w = len(diff) * 16
        draw_text(bx + bw/2 - text_w/2, by + 10, diff, 32, (0,0,0), z=0.9)

    if current_difficulty is None:
        draw_text(120, 100, "Select a difficulty to play!", 32, (1, 0, 0), z=0.9)
    else:
        draw_text(150, 100, "Press SPACE to start", 32, (0, 0, 0), z=0.9)


def run_playing_frame():
    """
    Playing state: ramp scroll speed and gravity, move pipes, score, physics, collision check.
    """
    global current_state, score, main_game_frames, level, points_needed_for_next_level

    main_game_frames += 1
    difficulty_t = min(1.0, main_game_frames / float(SCROLL_RAMP_FRAMES))
    
    diff_conf = DIFFICULTIES[current_difficulty]
    target_gravity = diff_conf["gravity"] - (level - 1) * 0.01
    target_scroll_speed = diff_conf["scroll_speed_max"] - (level - 1) * 0.1
    
    if current_difficulty in ("EASY", "MEDIUM"):
        speed_boost = (score // 5) * 0.2
        target_scroll_speed -= speed_boost
    
    start_scroll = diff_conf.get("scroll_speed_start", SCROLL_SPEED_START)
    
    scroll_speed = start_scroll + difficulty_t * (target_scroll_speed - start_scroll)
    bird.gravity = GRAVITY_EASE_START + difficulty_t * (target_gravity - GRAVITY_EASE_START)

    base.scroll_horizontally(scroll_speed)
    for pipe in pipes:
        pipe.scroll_horizontally(scroll_speed)
        pipe.draw()

    if pipes[0].right < 0:
        pipes.pop(0)
    if pipes[-1].left <= PIPE_SPAWN_DISTANCE:
        pipes.append(Pipe(textures["pipe"], gap_size=diff_conf["gap"]))

    front_pipe = pipes[0]
    if not front_pipe.point_awarded and front_pipe.right - (front_pipe.width / 2) <= bird.right:
        score += 1
        sounds["point"].play()
        front_pipe.point_awarded = True
        
        if score >= points_needed_for_next_level:
            level += 1
            points_needed_for_next_level += level * 4

    draw_score_overlay(str(score))
    draw_text(10, SCREENHEIGHT - 40, f"Level: {level}", 36, (0, 0, 0))
    
    bird.step_physics_and_draw()

    if bird_hits_pipe_or_ground():
        sounds["die"].play()
        save_current_score_if_max()
        go_to_next_state_in_flow()


def run_game_over_frame():
    """Frozen pipes, bird falls with death animation, score + UI."""
    for pipe in pipes:
        pipe.draw()
    bird.step_death_physics_and_draw()
    draw_score_overlay(str(score))
    draw_text(10, SCREENHEIGHT - 40, f"Level: {level}", 36, (0, 0, 0))
    draw_text(SCREENWIDTH - 200, SCREENHEIGHT - 40, f"Max: {max_scores[current_difficulty]}", 36, (0, 0, 0))
    draw_game_over_screen_sprites()


def bird_hits_pipe_or_ground():
    """AABB overlap with front pipe gap, or bird at/below the ground line."""
    pipe = pipes[0]
    if bird.right > pipe.left and bird.left < pipe.right:
        if bird.bottom < pipe.lower_y or bird.top > pipe.upper_y:
            return True
    if bird.bottom <= BASEY:
        return True
    return False


def render_scene():
    """GLUT display callback: clear, draw world for current_state, swap buffers."""
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glLoadIdentity()

    draw_parallax_background()
    base.draw()

    if current_state == GameState.WELCOME:
        run_welcome_frame()
    elif current_state == GameState.MAIN:
        run_playing_frame()
    else:
        run_game_over_frame()


def main():
    global window

    pygame.init()
    pygame.display.set_caption("Flappy Bird")
    window = pygame.display.set_mode((SCREENWIDTH, SCREENHEIGHT), DOUBLEBUF | OPENGL)

    load_high_score()
    load_game_sound_effects()
    setup_opengl_and_load_assets()

    clock = pygame.time.Clock()
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == QUIT:
                running = False
            elif event.type == KEYDOWN:
                if event.key == K_q:
                    running = False
                elif event.key == K_SPACE:
                    handle_keyboard(b" ", 0, 0)
                elif event.key == K_1:
                    handle_keyboard(b"1", 0, 0)
                elif event.key == K_2:
                    handle_keyboard(b"2", 0, 0)
                elif event.key == K_3:
                    handle_keyboard(b"3", 0, 0)
            elif event.type == MOUSEBUTTONDOWN:
                if event.button == 1:
                    handle_mouse_click(event.pos[0], event.pos[1])

        render_scene()
        pygame.display.flip()
        clock.tick(1000 // TIMER_MS)

    pygame.quit()


if __name__ == "__main__":
    main()
