/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#07090d",
          900: "#0c1018",
          800: "#121826",
          700: "#1a2233",
        },
        ember: {
          400: "#f0a46a",
          500: "#e8893a",
          600: "#c96a1e",
        },
        mint: {
          400: "#6ec9a8",
          500: "#3daf8a",
        },
        mist: {
          100: "#e8eef8",
          300: "#9aabc4",
          500: "#6b7c96",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      backgroundImage: {
        "grid-fade":
          "linear-gradient(to right, rgba(232,238,248,0.04) 1px, transparent 1px), linear-gradient(to bottom, rgba(232,238,248,0.04) 1px, transparent 1px)",
        "hero-glow":
          "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(232,137,58,0.18), transparent 55%), radial-gradient(ellipse 60% 40% at 90% 10%, rgba(110,201,168,0.08), transparent 50%)",
      },
    },
  },
  plugins: [],
};
