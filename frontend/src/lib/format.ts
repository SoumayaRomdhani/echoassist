import { format, formatDistanceToNow, isValid } from 'date-fns'

export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  return isValid(date) ? format(date, 'MMM d, yyyy · HH:mm') : iso
}

export function formatRelative(iso: string): string {
  const date = new Date(iso)
  return isValid(date) ? formatDistanceToNow(date, { addSuffix: true }) : iso
}

/** "current_role" / "years-experience" -> "Current Role" / "Years Experience". */
export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim()
}

export function shortId(id: string, length = 8): string {
  return id.length > length ? `${id.slice(0, length)}…` : id
}
