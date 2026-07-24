import { createContext, useContext, useState, useCallback, useMemo } from 'react';
import { translate } from '../lib/i18n';

const I18nContext = createContext(null);

// UI language is independent from the AI Shorts script/voice language.
// Default 'en'; persisted in localStorage.
export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(() => localStorage.getItem('ui_lang') || 'en');

  const setLang = useCallback((next) => {
    setLangState(next);
    localStorage.setItem('ui_lang', next);
  }, []);

  const t = useCallback((key, vars) => translate(lang, key, vars), [lang]);

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used within I18nProvider');
  return ctx;
}
