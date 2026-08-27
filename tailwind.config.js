module.exports = {
  content: [
    "./templates/**/*.html",
    "./*/templates/**/*.html",
    "./static/**/*.js",
    "./*/static/**/*.js",
  ],
  safelist: [
    {
      pattern: /^(bg|text|border|ring|from|to|via|shadow)-(primary|secondary|luxury|gold|platinum)$/,
      variants: ["hover", "focus", "active", "group-hover", "peer-checked"],
    },
    {
      pattern: /^(bg|text|border)-(red|green|blue|yellow|orange|purple|gray|slate|emerald|amber|cyan|pink)-(50|100|200|300|400|500|600|700|800|900)$/,
      variants: ["hover", "focus", "active", "group-hover", "peer-checked"],
    },
    "animate-float",
    "animate-glow",
    "animate-shimmer",
    "animate-pulse-luxury",
    "shadow-luxury",
    "shadow-luxury-lg",
    "shadow-luxury-sm",
    "font-luxury",
    "font-premium",
    "font-logo",
    "font-heading",
    "font-mega",
    "gradient-luxury",
    "text-brand",
    "bg-brand",
    "border-brand",
  ],
  theme: {
    extend: {
      colors: {
        primary: "var(--color-primary)",
        secondary: "var(--color-secondary)",
        luxury: "#1a1a1a",
        gold: "#d4af37",
        platinum: "#e8e8e8",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        luxury: ["Montserrat", "Inter", "sans-serif"],
        premium: ["Inter", "system-ui", "sans-serif"],
        logo: ["Montserrat", "Inter", "sans-serif"],
        heading: ["Montserrat", "Inter", "sans-serif"],
        mega: ["Roboto Condensed", "Inter", "sans-serif"],
      },
      boxShadow: {
        luxury: "0 20px 60px rgba(0, 0, 0, 0.15)",
        "luxury-lg": "0 40px 120px rgba(0, 0, 0, 0.25)",
        "luxury-sm": "0 10px 30px rgba(0, 0, 0, 0.1)",
      },
      animation: {
        float: "float 6s ease-in-out infinite",
        glow: "glow 3s ease-in-out infinite",
        shimmer: "shimmer 2s infinite",
        "pulse-luxury": "pulse-luxury 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-10px)" },
        },
        glow: {
          "0%, 100%": { textShadow: "0 0 20px rgba(212, 175, 55, 0.5)" },
          "50%": { textShadow: "0 0 40px rgba(212, 175, 55, 0.8)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-1000px 0" },
          "100%": { backgroundPosition: "1000px 0" },
        },
        "pulse-luxury": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: ".7" },
        },
      },
    },
  },
  plugins: [],
};
