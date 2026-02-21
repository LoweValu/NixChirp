"""GLSL shader compilation and program management."""

from __future__ import annotations

from importlib import resources

from OpenGL.GL import (
    GL_COMPILE_STATUS,
    GL_FRAGMENT_SHADER,
    GL_LINK_STATUS,
    GL_VERTEX_SHADER,
    glAttachShader,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glDeleteShader,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glLinkProgram,
    glShaderSource,
)

_SHADER_PKG = "nixchirp.shaders"


def _compile_shader(source: str, shader_type: int) -> int:
    """Compile a single shader from source."""
    shader = glCreateShader(shader_type)
    glShaderSource(shader, source)
    glCompileShader(shader)
    if not glGetShaderiv(shader, GL_COMPILE_STATUS):
        log = glGetShaderInfoLog(shader).decode()
        raise RuntimeError(f"Shader compile error: {log}")
    return shader


def _link_program(vertex: int, fragment: int) -> int:
    """Link vertex and fragment shaders into a program."""
    program = glCreateProgram()
    glAttachShader(program, vertex)
    glAttachShader(program, fragment)
    glLinkProgram(program)
    if not glGetProgramiv(program, GL_LINK_STATUS):
        log = glGetProgramInfoLog(program).decode()
        raise RuntimeError(f"Shader link error: {log}")
    glDeleteShader(vertex)
    glDeleteShader(fragment)
    return program


def load_shader_program(vert_filename: str, frag_filename: str) -> int:
    """Load and compile a shader program from files in the shaders package."""
    vert_source = resources.files(_SHADER_PKG).joinpath(vert_filename).read_text()
    frag_source = resources.files(_SHADER_PKG).joinpath(frag_filename).read_text()
    vert = _compile_shader(vert_source, GL_VERTEX_SHADER)
    frag = _compile_shader(frag_source, GL_FRAGMENT_SHADER)
    return _link_program(vert, frag)
