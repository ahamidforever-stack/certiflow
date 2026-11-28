import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Join class names; later Tailwind classes win over earlier conflicting ones. */
export const cn = (...v: ClassValue[]) => twMerge(clsx(v));
