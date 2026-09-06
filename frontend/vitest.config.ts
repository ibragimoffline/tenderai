/**
 * XATTI-HARAKAT SINOVLARI — konfiguratsiya.
 *
 * NEGA ALOHIDA FAYL, `vite.config.ts` GA QO'SHILMADI:
 * `vite.config.ts` da QURILMA QO'ROVULI bor (`mahalliymi()` — mahalliy
 * manzil relizga singib qolmasin). U `APP_ENV` va `VITE_*` ni o'qiydi
 * va qurilmani ATAYLAB TO'XTATADI. Sinov muhitida bu qo'rovul o'rinsiz
 * va u sinovlarni o'zining nosozlik xabari bilan yiqitardi.
 *
 * NEGA VITEST, `node --experimental-strip-types` EMAS:
 * mavjud uch sinov (`markdown`, `colors`, `xato`) — SOF MANTIQ va
 * ular uchun runner kerak emas, bu ONGLI qaror va u SAQLANADI.
 * Lekin komponent XATTI-HARAKATI uchun render + hodisa kerak
 * (`@testing-library/react`), va u runner talab qiladi. Vitest
 * tanlandi, chunki u Vite ning o'z konfiguratsiyasini ishlatadi —
 * ikkinchi bundler sozlamasi paydo bo'lmaydi.
 */
import path from 'node:path'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // FAQAT xatti-harakat sinovlari. Sof mantiq sinovlari
    // (`*.test.ts`, node bilan yuriladi) BU YERGA TUSHMAYDI —
    // aks holda ular ikki marta yurardi va ikki xil natija
    // bergan joyda qaysi biri haqiqat ekani noaniq bo'lardi.
    include: ['src/**/*.xulq.test.tsx'],
    // Sinov O'ZI yiqilsin, jimgina o'tmasin.
    passWithNoTests: false,
    restoreMocks: true,
  },
})
