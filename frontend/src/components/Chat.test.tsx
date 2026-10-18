import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Chat } from './Chat'

describe('Chat audio directions', () => {
  it('hides agent audio directions and preserves the customer transcript', () => {
    render(<Chat messages={[
      { role: 'agent', text: '[calm] Your balance is $1,234.50.' },
      { role: 'user', text: 'My note says [calm].' },
    ]} />)
    expect(screen.getByText('Your balance is $1,234.50.')).toBeInTheDocument()
    expect(screen.getByText('My note says [calm].')).toBeInTheDocument()
  })
})
