import { describe, expect, it } from 'vitest'
import { shortId, titleCase } from '@/lib/format'

describe('format helpers', () => {
  it('titleCase humanizes slot keys', () => {
    expect(titleCase('candidate_name')).toBe('Candidate Name')
    expect(titleCase('years-experience')).toBe('Years Experience')
  })

  it('shortId truncates long ids and leaves short ones intact', () => {
    expect(shortId('abcdefghijklmnop', 8)).toBe('abcdefgh…')
    expect(shortId('abc', 8)).toBe('abc')
  })
})
