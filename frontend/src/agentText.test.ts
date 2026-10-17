import { describe, expect, it } from 'vitest'
import { cleanAgentText } from './agentText'

describe('cleanAgentText', () => {
  it.each([
    ['[calm] Okay, microphone paused.', 'Okay, microphone paused.'],
    ['[calm] : [calm] Okay.', 'Okay.'],
    ['[warmly] Hello! Your balance is $1,234.50.', 'Hello! Your balance is $1,234.50.'],
    ['Hello [calm] there.', 'Hello there.'],
    ['Your [Savings] balance is $1,234.50.', 'Your [Savings] balance is $1,234.50.'],
    ['Account [1234] has $0.05.', 'Account [1234] has $0.05.'],
  ])('cleans audio directions without changing banking text: %s', (input, expected) => {
    expect(cleanAgentText(input)).toBe(expected)
  })
})
