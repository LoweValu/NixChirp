#version 330 core

in vec2 vTexCoord;
out vec4 fragColor;

uniform sampler2D uTexture;
uniform vec3 uChromaColor;

void main() {
    vec4 texel = texture(uTexture, vTexCoord);
    // Blend texture over chroma key color
    fragColor = vec4(mix(uChromaColor, texel.rgb, texel.a), 1.0);
}
