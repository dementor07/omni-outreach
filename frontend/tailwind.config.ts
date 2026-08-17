import type { Config } from 'tailwindcss'

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Brand palette. Rose. The style-guide swatch "rose" is the
        // canonical brand from 2026-05-15 forward. Values match
        // Tailwind's stock rose ramp 50→900 so every dark-mode and
        // utility class that references the stock palette stays
        // consistent with the brand-* tokens.
        brand: {
          50:  '#fff1f2',
          100: '#ffe4e6',
          200: '#fecdd3',
          300: '#fda4af',
          400: '#fb7185',
          500: '#f43f5e',
          600: '#e11d48',
          700: '#be123c',
          800: '#9f1239',
          900: '#881337',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      // Whisper-soft, layered elevation — quiet depth over the gradient-mesh
      // page, never heavy. Restraint is the point: cards float a hair off the
      // page, hover lifts a touch more. No coloured glows in the default scale.
      boxShadow: {
        soft: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 2px -1px rgb(15 23 42 / 0.05)',
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 2px 8px -3px rgb(15 23 42 / 0.06)',
        elevated: '0 4px 10px -3px rgb(15 23 42 / 0.07), 0 10px 24px -8px rgb(15 23 42 / 0.10)',
      },
      backgroundImage: {
        // A single restrained gradient, reserved for one hero surface — not buttons.
        'brand-gradient': 'linear-gradient(135deg, #f43f5e 0%, #e11d48 100%)',
      },
      keyframes: {
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-in-up': 'fade-in-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both',
      },
    },
  },
  plugins: [],
} satisfies Config
