"""OpenGL texture upload and quad rendering."""

from __future__ import annotations

import ctypes

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_BLEND,
    GL_CLAMP_TO_EDGE,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE,
    GL_FLOAT,
    GL_LINEAR,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_RGBA,
    GL_RGBA8,
    GL_SRC_ALPHA,
    GL_STATIC_DRAW,
    GL_TEXTURE0,
    GL_TEXTURE1,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_TRIANGLES,
    GL_UNSIGNED_BYTE,
    GL_UNSIGNED_INT,
    glActiveTexture,
    glBindBuffer,
    glBindTexture,
    glBindVertexArray,
    glBlendFunc,
    glBufferData,
    glClear,
    glClearColor,
    glDeleteBuffers,
    glDeleteTextures,
    glDeleteVertexArrays,
    glDisable,
    glDrawElements,
    glEnable,
    glEnableVertexAttribArray,
    glGenBuffers,
    glGenTextures,
    glGenVertexArrays,
    glGetUniformLocation,
    glTexImage2D,
    glTexParameteri,
    glTexSubImage2D,
    glUniform1f,
    glUniform1i,
    glUniform3f,
    glUniform4f,
    glUseProgram,
    glVertexAttribPointer,
    glViewport,
)
from OpenGL.GL import GL_COLOR_BUFFER_BIT

from nixchirp.render.shaders import load_shader_program


# Fullscreen quad: positions (x,y) + texcoords (u,v)
# Flipped V so textures aren't upside-down
_QUAD_VERTICES = np.array([
    # x,    y,    u,   v
    -1.0, -1.0,  0.0, 1.0,   # bottom-left
     1.0, -1.0,  1.0, 1.0,   # bottom-right
     1.0,  1.0,  1.0, 0.0,   # top-right
    -1.0,  1.0,  0.0, 0.0,   # top-left
], dtype=np.float32)

_QUAD_INDICES = np.array([0, 1, 2, 2, 3, 0], dtype=np.uint32)


class GLRenderer:
    """Manages OpenGL state for rendering textured quads."""

    def __init__(self) -> None:
        self._vao: int = 0
        self._vbo: int = 0
        self._ebo: int = 0
        self._passthrough_program: int = 0
        self._chroma_program: int = 0
        self._crossfade_program: int = 0
        self._texture_a: int = 0  # Primary texture
        self._texture_b: int = 0  # Secondary texture (for crossfade)
        self._tex_a_width: int = 0
        self._tex_a_height: int = 0
        self._tex_b_width: int = 0
        self._tex_b_height: int = 0

    def init(self) -> None:
        """Set up VAO, VBO, shaders, and textures. Must be called after GL context is created."""
        # Compile shaders
        self._passthrough_program = load_shader_program("passthrough.vert", "passthrough.frag")
        self._chroma_program = load_shader_program("passthrough.vert", "chroma.frag")
        self._crossfade_program = load_shader_program("passthrough.vert", "crossfade.frag")

        # Create VAO
        self._vao = glGenVertexArrays(1)
        glBindVertexArray(self._vao)

        # VBO
        self._vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, _QUAD_VERTICES.nbytes, _QUAD_VERTICES, GL_STATIC_DRAW)

        # EBO
        self._ebo = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, _QUAD_INDICES.nbytes, _QUAD_INDICES, GL_STATIC_DRAW)

        stride = 4 * 4  # 4 floats * 4 bytes
        # Position attribute (location 0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        # TexCoord attribute (location 1)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(8))
        glEnableVertexAttribArray(1)

        glBindVertexArray(0)

        # Create textures
        self._texture_a = self._create_texture()
        self._texture_b = self._create_texture()

    def _create_texture(self) -> int:
        """Create an empty RGBA texture with linear filtering."""
        tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glBindTexture(GL_TEXTURE_2D, 0)
        return tex

    def upload_frame(self, frame: np.ndarray, slot: str = "a") -> None:
        """Upload an RGBA frame (numpy H x W x 4 uint8) to a texture slot.

        Args:
            frame: RGBA image as numpy array with shape (height, width, 4).
            slot: 'a' for primary texture, 'b' for secondary (crossfade).
        """
        h, w = frame.shape[:2]
        tex = self._texture_a if slot == "a" else self._texture_b

        # Track dimensions per slot
        if slot == "a":
            old_w, old_h = self._tex_a_width, self._tex_a_height
        else:
            old_w, old_h = self._tex_b_width, self._tex_b_height

        glBindTexture(GL_TEXTURE_2D, tex)

        # Ensure frame is contiguous in memory
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)

        if w != old_w or h != old_h:
            # Reallocate texture storage
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, frame)
            if slot == "a":
                self._tex_a_width, self._tex_a_height = w, h
            else:
                self._tex_b_width, self._tex_b_height = w, h
        else:
            # Sub-image update (faster, no reallocation)
            glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, frame)

        glBindTexture(GL_TEXTURE_2D, 0)

    def render_passthrough(self, bg_color: tuple[float, float, float, float]) -> None:
        """Render texture A over a background color."""
        glUseProgram(self._passthrough_program)
        glUniform4f(
            glGetUniformLocation(self._passthrough_program, "uBgColor"),
            *bg_color,
        )
        glUniform1i(
            glGetUniformLocation(self._passthrough_program, "uTexture"),
            0,
        )
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._texture_a)
        self._draw_quad()

    def render_chroma(self, chroma_color: tuple[float, float, float]) -> None:
        """Render texture A over a chroma key background."""
        glUseProgram(self._chroma_program)
        glUniform3f(
            glGetUniformLocation(self._chroma_program, "uChromaColor"),
            *chroma_color,
        )
        glUniform1i(
            glGetUniformLocation(self._chroma_program, "uTexture"),
            0,
        )
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._texture_a)
        self._draw_quad()

    def render_crossfade(
        self,
        blend: float,
        bg_color: tuple[float, float, float, float],
    ) -> None:
        """Render a crossfade between texture A and texture B."""
        glUseProgram(self._crossfade_program)
        glUniform1f(
            glGetUniformLocation(self._crossfade_program, "uBlend"),
            blend,
        )
        glUniform4f(
            glGetUniformLocation(self._crossfade_program, "uBgColor"),
            *bg_color,
        )
        glUniform1i(
            glGetUniformLocation(self._crossfade_program, "uTextureA"),
            0,
        )
        glUniform1i(
            glGetUniformLocation(self._crossfade_program, "uTextureB"),
            1,
        )
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._texture_a)
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, self._texture_b)
        self._draw_quad()

    def clear(self, color: tuple[float, float, float, float]) -> None:
        """Clear the framebuffer."""
        glClearColor(*color)
        glClear(GL_COLOR_BUFFER_BIT)

    def set_viewport(self, width: int, height: int) -> None:
        """Update the GL viewport."""
        glViewport(0, 0, width, height)

    def _draw_quad(self) -> None:
        """Draw the fullscreen quad."""
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glBindVertexArray(self._vao)
        glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        glDisable(GL_BLEND)

    def destroy(self) -> None:
        """Release OpenGL resources."""
        if self._texture_a:
            glDeleteTextures(1, [self._texture_a])
        if self._texture_b:
            glDeleteTextures(1, [self._texture_b])
        if self._vao:
            glDeleteVertexArrays(1, [self._vao])
        if self._vbo:
            glDeleteBuffers(1, [self._vbo])
        if self._ebo:
            glDeleteBuffers(1, [self._ebo])
