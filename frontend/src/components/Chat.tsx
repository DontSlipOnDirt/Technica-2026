import { useEffect, useRef } from 'react'
import { cleanAgentText } from '../agentText'
import type { ChatMessage } from '../session/screenState'

/** The live transcript, newest at the bottom. */
export function Chat({ messages }: { messages: ChatMessage[] }) {
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    end.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [messages.length])

  return (
    <div className="chat" aria-live="polite">
      {messages.map((m, i) => (
        <p key={i} className={`chat__msg chat__msg--${m.role}`}>{m.role === 'agent' ? cleanAgentText(m.text) : m.text}</p>
      ))}
      <div ref={end} className="chat__end" aria-hidden="true" />
    </div>
  )
}
