/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#10263e",
        teal: "#087f8c",
        mist: "#f4f7fa",
      },
    },
  },
  plugins: [],
};
