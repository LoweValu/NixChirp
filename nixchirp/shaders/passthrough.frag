#version 330 core

in vec2 vTexCoord;
out vec4 fragColor;

uniform sampler2D uTexture;
uniform vec4 uBgColor;

void main() {
    vec4 texel = texture(uTexture, vTexCoord);
    // Blend texture over background color using texture alpha
    fragColor = mix(uBgColor, texel, texel.a);
}
