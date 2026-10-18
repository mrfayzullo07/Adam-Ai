/**
 * Adam transkriptini gaplarga bo'lib, o'zbekcha qismlarni aniqlaydi
 * (UI'da o'zbekcha = italik subtitr, inglizcha = oddiy/qalin mashq).
 */

const UZ_APOSTROPHE = /[oOgG][\u2019'ʻʼ`‘]/;
const CYRILLIC = /[\u0400-\u04FF]/;
const UZ_WORDS = new Set(
  (
    "va bu u men sen siz biz ular nima qanday qachon qayerda nega kerak emas edi bor yoq " +
    "yaxshi rahmat salom assalomu alaykum ha endi keyin oldin uchun bilan lekin ammo " +
    "mening sizning keling takrorlang ayting qiling aytamiz deymiz barakalla zor ajoyib " +
    "kichik xato juda yana bir marta urinib koring mana bunday hechqisi bugun ertaga " +
    "ingliz tilida tilini sozi soz gap gapni javob savol mashq qilamiz boshlaymiz eshiting " +
    "toʻgʻri togri tushundingizmi tushunarli demak masalan ham hamda yoki shunday"
  ).split(/\s+/),
);
const UZ_SUFFIX = /(miz|siz|lar|ning|dagi|ingiz|ganmi|yapti|moqda|amiz|ishni|ishga|ish|dan|ga|da|ni)$/;

export interface TextSegment {
  text: string;
  uz: boolean;
}

export function isUzbek(sentence: string): boolean {
  if (CYRILLIC.test(sentence) || UZ_APOSTROPHE.test(sentence)) return true;
  const words = sentence
    .toLowerCase()
    .replace(/[^a-zʻʼ'\s-]/g, " ")
    .split(/\s+/)
    .filter(Boolean);
  if (words.length === 0) return false;
  let score = 0;
  for (const w of words) {
    if (UZ_WORDS.has(w.replace(/['ʻʼ]/g, ""))) score += 1;
    else if (w.length > 4 && UZ_SUFFIX.test(w)) score += 0.5;
  }
  return score / words.length >= 0.3;
}

/** Matnni gaplarga bo'ladi va har birini til bo'yicha belgilaydi; qo'shni bir xil tillar birlashtiriladi. */
export function segmentByLanguage(text: string): TextSegment[] {
  const parts = text.match(/[^.!?…:]+[.!?…:]*\s*/g) ?? [text];
  const out: TextSegment[] = [];
  for (const raw of parts) {
    if (!raw.trim()) continue;
    const uz = isUzbek(raw);
    const last = out[out.length - 1];
    if (last && last.uz === uz) last.text += raw;
    else out.push({ text: raw, uz });
  }
  return out;
}
