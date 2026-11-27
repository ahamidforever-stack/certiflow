/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { 50: "#eef3fb", 100: "#d9e2f3", 500: "#2d5aa0", 600: "#1f3864", 700: "#182c4f" },
        accent: { 500: "#c2185b" },
      },
      fontFamily: {
        sans: ["Segoe UI", "system-ui", "-apple-system", "Noto Sans Arabic", "Tahoma", "sans-serif"],
      },
    },
  },
  plugins: [],
};
