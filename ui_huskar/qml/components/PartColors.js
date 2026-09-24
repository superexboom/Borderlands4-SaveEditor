.pragma library

// The data palette is intentionally vivid for dark glass panels. On a light
// panel those same pastel colors disappear, so reduce brightness only there.
function visible(value, darkMode) {
    var color = Qt.color(value || "#B0BEC5");
    if (darkMode)
        return color;
    var luminance = 0.2126 * color.r + 0.7152 * color.g + 0.0722 * color.b;
    var factor = luminance > 0.68 ? 0.48 : (luminance > 0.45 ? 0.62 : 0.74);
    return Qt.rgba(color.r * factor, color.g * factor, color.b * factor, color.a);
}
