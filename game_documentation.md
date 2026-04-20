# Flappy Bird: Architecture and Codebase Guide

This document is a complete breakdown of how your PyGame + PyOpenGL Flappy Bird clone is built, how the logic works, and what every function does.

---

## 1. How the Game is Made (The Tech Stack)

Your game uses a unique combination of libraries:
- **PyGame**: Usually, PyGame is used to draw 2D pixels, but in this project, it is **only** used to create the window, handle keyboard/mouse inputs, play audio, and manage the frame rate (FPS clock).
- **PyOpenGL**: Instead of PyGame's drawing tools, the game uses raw OpenGL commands to render everything using your computer's graphics card (GPU). 
- **PIL (Pillow)**: Used to load PNG images and convert them into raw bytes so they can be sent to the GPU as OpenGL textures.

Instead of keeping everything in one giant file, the code is split into two files:
- `classes.py`: Contains the "Actors" of the game (Bird, Pipe, Base).
- `main.py`: Contains the "Director" (Main Loop, state machines, input, and score).

---

## 2. What is the Game Logic?

The game is built around a concept called a **State Machine**. At any given time, the game is in exactly one of three states (`GameState` enum):
1. **WELCOME (Menu)**: The bird hovers up and down. Pipes don't spawn. Waiting for user input.
2. **MAIN (Playing)**: Gravity is applied to the bird. Pipes scroll to the left. Collision detection is active.
3. **GAME_OVER**: The bird freezes its wing animation and falls to the ground. Waiting for the user to restart.

### The Main Loop
Every video game runs in an infinite loop called the "Main Loop". It happens dozens of times a second (controlled by `clock.tick()`). In each loop, the game does 3 things:
1. **Process Inputs**: Did the user press SPACE or click the mouse?
2. **Update Game State**: Apply gravity, move pipes left, update score.
3. **Render Scene**: Clear the screen and draw the updated positions of everything using OpenGL.

### The Physics
The physics are incredibly simple:
- **Gravity** is a negative number (e.g., `-0.15`). Every single frame, the bird's `velocity` is updated: `velocity = velocity + gravity`. Since gravity is negative, the velocity keeps getting more and more negative, causing the bird to fall faster and faster.
- **Jumping** simply overrides the bird's velocity with a positive number (e.g., `3.0`). This instantly shoots the bird upward, but gravity immediately starts pulling it back down on the next frame.

---

## 3. Understanding OpenGL "Projection"

In 3D graphics, you have to tell the graphics card how to flatten a 3D world onto a 2D computer screen. This is called **Projection**.

There are two main types of projection:
1. **Perspective Projection**: Objects get smaller as they get further away (like real life or 3D games like Minecraft).
2. **Orthographic Projection**: There is no depth. An object is the exact same size whether it is 1 unit away or 1000 units away. 

> [!NOTE]
> **How your game uses it:**
> The function `glOrtho(0, SCREENWIDTH, 0, SCREENHEIGHT, -3, 3)` sets up an **Orthographic Projection**. 
> It tells the GPU: "Make the bottom-left of my screen X=0, Y=0. Make the top-right X=600, Y=720." 
> Because we use `glOrtho`, we don't have to deal with complex 3D math. We can just say "draw a rectangle at X=100, Y=200" and OpenGL draws it exactly 100 pixels from the left and 200 pixels from the bottom.

---

## 4. Comprehensive Function Breakdown

### From `classes.py` (The Entities)

- **`random_pipe_gap_center_y`**: Calculates a random vertical height (Y-coordinate) for the hole between the top and bottom pipe, ensuring it doesn't go off-screen.
- **`draw_textured_quad`**: The most important drawing function. It uses `glBegin(GL_QUADS)` to draw a rectangle (quad) using 4 vertices, and pastes an image (texture) onto it using Texture Coordinates (`glTexCoord`).
- **`Pipe` (Class)**: 
  - `__init__`: Sets the width, calculates the gap, and positions it on the far right of the screen.
  - `draw`: Draws the bottom pipe and the top pipe (which uses an upside-down texture).
  - `scroll_horizontally`: Subtracts `delta_x` from the pipe's X-coordinates so it moves left.
- **`Bird` (Class)**:
  - `__init__`: Sets the bounding box, starting speed, and gravity.
  - `draw`: Rotates the bird's sprite based on its angle and animates the wings by cycling through 3 textures.
  - `step_physics_and_draw`: Applies gravity to velocity, and applies velocity to the Y-coordinate. It also tilts the bird's beak up when jumping, and down when falling.
  - `step_death_physics_and_draw`: Stops the wing animation and makes the bird plummet straight down when it dies.
- **`Base` (Class)**: The ground. It is drawn as a massive rectangle twice the width of the screen. `scroll_horizontally` moves it left, and when it moves too far, it snaps back to the right to create an infinite scrolling illusion.

### From `main.py` (The Engine)

#### Setup and Assets
- **`load_game_sound_effects`**: Loads the `.ogg` sound files into Pygame's mixer.
- **`load_image_as_rgba_bytes`**: Uses the Pillow library to read a PNG file and convert its pixels into raw byte data that OpenGL can understand.
- **`upload_rgba_image_to_texture_2d`**: Sends the raw image bytes to the GPU, giving it a Texture ID, and generates "Mipmaps" (lower resolution versions of the image to make it look smooth when scaled).
- **`get_text_texture` / `draw_text`**: Because OpenGL cannot natively draw fonts, this function uses Pillow to draw text onto an invisible canvas, converts that canvas into an image, sends it to the GPU as a texture, and draws it as a rectangle.
- **`setup_opengl_and_load_assets`**: Turns on necessary OpenGL features like Depth Testing (drawing things in front of other things) and Blending (allowing transparent backgrounds in PNGs).

#### Game Flow & State
- **`create_initial_entities`**: Clears the screen of old pipes, creates a new Bird, a new Base, and spawns the first pipe.
- **`bird_hits_pipe_or_ground`**: Checks for "AABB" (Axis-Aligned Bounding Box) collision. It checks if the rectangle representing the bird overlaps with the rectangles representing the pipes or the ground.
- **`go_to_next_state_in_flow`**: Simply cycles the state machine forward (WELCOME -> MAIN -> GAME_OVER -> WELCOME).

#### The Frames (The Loops)
- **`run_welcome_frame`**: Draws the background, draws the difficulty buttons using `BUTTONS.items()`, checks if your mouse is hovering over them (`is_hovered`), and bobs the bird up and down.
- **`run_playing_frame`**: The core gameplay. 
  - Calculates the increasing `scroll_speed` and `gravity` based on your level.
  - Moves the pipes.
  - Spawns a new pipe if the last pipe moved far enough left.
  - Checks if the bird passed a pipe, and if so, plays the point sound and adds `1` to your `score`.
  - Runs the collision check to see if you died.
- **`run_game_over_frame`**: Freezes the pipes, makes the bird fall off the screen, and displays your final score and the maximum high score.

#### Input and Main
- **`handle_keyboard`**: Dictates what the SPACEBAR or keys `1, 2, 3` do depending on the current game state. (e.g., if you are in `MAIN`, SPACEBAR makes the bird jump).
- **`handle_mouse_click`**: Maps the mouse click to screen coordinates. If the click hits a difficulty button, it selects it and simulates pressing the spacebar to start the game immediately.
- **`render_scene`**: The master drawing function. It clears the screen, draws the background, and then runs whichever "frame" function matches the current state.
- **`main`**: Initializes Pygame, creates the window, and runs the infinite `while running:` loop. This is where your code begins executing.
