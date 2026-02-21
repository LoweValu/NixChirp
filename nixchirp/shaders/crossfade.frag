#version 330 core

in vec2 vTexCoord;
out vec4 fragColor;

uniform sampler2D uTextureA;
uniform sampler2D uTextureB;
uniform float uBlend;  // 0.0 = fully A, 1.0 = fully B
uniform vec4 uBgColor;

void main() {
    vec4 texelA = texture(uTextureA, vTexCoord);
    vec4 texelB = texture(uTextureB, vTexCoord);
    vec4 blended = mix(texelA, texelB, uBlend);
    fragColor = mix(uBgColor, blended, blended.a);
}
