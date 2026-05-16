/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./src/**/*.py",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#1a1a1a',
        secondary: '#D7FF00',
        accent: '#D7FF00',
        owner: '#6366f1',
        admin: '#6366f1',
      },
    },
  },
  plugins: [],
}
