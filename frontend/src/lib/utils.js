import { clsx } from "clsx";
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

export function sortSelectedFirst(items, selectedId, idKey = 'id') {
  if (!selectedId) return items
  const idx = items.findIndex((i) => i[idKey] === selectedId)
  if (idx <= 0) return items
  return [items[idx], ...items.slice(0, idx), ...items.slice(idx + 1)]
}
