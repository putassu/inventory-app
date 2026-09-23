import { createContext, useContext, useState, useEffect } from 'react'
const ThemeContext = createContext()
export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => localStorage.getItem('inventory_theme') || 'system')
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)')
    const update = () =>
      document.documentElement.classList.toggle(
        'dark',
        theme === 'dark' || (theme === 'system' && media.matches),
      )
    update()
    media.addEventListener('change', update)
    localStorage.setItem('inventory_theme', theme)
    return () => media.removeEventListener('change', update)
  }, [theme])
  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}
export const useTheme = () => useContext(ThemeContext)
