import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MicOrb } from './MicOrb'

describe('MicOrb microphone activity', () => {
  let nextFrame: FrameRequestCallback
  let requestFrame: ReturnType<typeof vi.fn>
  let cancelFrame: ReturnType<typeof vi.fn>

  beforeEach(() => {
    requestFrame = vi.fn((callback: FrameRequestCallback) => {
      nextFrame = callback
      return 1
    })
    cancelFrame = vi.fn()
    vi.stubGlobal('requestAnimationFrame', requestFrame)
    vi.stubGlobal('cancelAnimationFrame', cancelFrame)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('grows with microphone volume and settles during silence', () => {
    const getInputVolume = vi.fn(() => 0)
    render(<MicOrb active blocked={false} onTap={vi.fn()} getAudioLevel={getInputVolume} />)
    const button = screen.getByRole('button')
    const level = () => Number(button.style.getPropertyValue('--mic-level'))

    act(() => nextFrame(0))
    expect(level()).toBe(0)
    getInputVolume.mockReturnValue(0.6)
    act(() => nextFrame(16))
    const speakingLevel = level()
    expect(speakingLevel).toBeGreaterThan(0)
    expect(speakingLevel).toBeLessThanOrEqual(1)
    getInputVolume.mockReturnValue(0)
    act(() => nextFrame(32))
    expect(level()).toBeLessThan(speakingLevel)
  })

  it('stops sampling and resets when the microphone is muted', () => {
    const getInputVolume = vi.fn(() => 0.6)
    const { rerender } = render(<MicOrb active blocked={false} onTap={vi.fn()} getAudioLevel={getInputVolume} />)
    act(() => nextFrame(0))
    expect(getInputVolume).toHaveBeenCalled()
    rerender(<MicOrb active blocked={false} onTap={vi.fn()} />)
    expect(cancelFrame).toHaveBeenCalled()
    expect(screen.getByRole('button').style.getPropertyValue('--mic-level')).toBe('0')
  })

  it.each([{ active: false, blocked: false }, { active: true, blocked: true }])(
    'does not sample while inactive or blocked: %j',
    (props) => {
      render(<MicOrb {...props} onTap={vi.fn()} getAudioLevel={vi.fn(() => 1)} />)
      expect(requestFrame).not.toHaveBeenCalled()
    },
  )

  it('cancels the animation when unmounted', () => {
    const { unmount } = render(<MicOrb active blocked={false} onTap={vi.fn()} getAudioLevel={() => 0} />)
    unmount()
    expect(cancelFrame).toHaveBeenCalledWith(1)
  })
})
