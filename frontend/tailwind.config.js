/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: '#FDFBF7',
        surface: '#FFFFFF',
        'surface-hover': '#F5F3ED',
        'text-primary': '#1C1C1A',
        'text-secondary': '#7A7873',
        brand: '#C36B58',
        'brand-hover': '#B25F4D',
        sage: '#8A9A86',
        accent: '#D69E4A',
        'border-default': '#EAE8E3',
        'border-active': '#C36B58',
      },
      fontFamily: {
        heading: ['Outfit', 'sans-serif'],
        body: ['Manrope', 'sans-serif'],
      },
      borderRadius: {
        '2xl': '1rem',
      },
      keyframes: {
        shimmer: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        shimmer: 'shimmer 1.5s infinite',
      },
    },
  },
  plugins: [],
}
